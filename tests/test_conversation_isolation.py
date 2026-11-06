"""Regressão: o histórico da sessão não pode contaminar busca, roteamento ou ferramentas."""

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.agents.knowledge as knowledge_module
from app.agents.knowledge import KnowledgeAgent
from app.agents.web_search import WebSearchAgent
from app.agents.router import RoutingDecision
from app.main import app, handoff_store, orchestrator
from app.orchestrator import ChatOrchestrator
from app.session_memory import SessionMemory

client = TestClient(app, headers={"Authorization": "Bearer test-token-cliente1988"})

OFFICIAL_SCENARIOS = [
    "What's the difference between the Get Clássica and the Get Smart?",
    "What's the weather forecast in Porto Alegre tomorrow?",
    "When will the money from yesterday's sales be deposited?",
    "Do I need a bank account to receive my sales via Pix?",
    "My card machine won't connect to the internet, what should I do?",
    "How does receivables advance (antecipação) work with Getnet?",
    "What's the euro exchange rate today?",
    "My card machine is showing a transaction decline error.",
    "How many installments can I split a sale into with the crediário?",
    "Can I sell through WhatsApp using the Payment Link?",
]


def _chat(message: str, session_id: str) -> dict:
    response = client.post(
        "/chat",
        json={"message": message, "user_id": "cliente1988", "session_id": session_id},
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def retrieval_queries(monkeypatch):
    queries = []
    original = knowledge_module.retrieve

    def spy(query, *args, **kwargs):
        queries.append(query)
        return original(query, *args, **kwargs)

    monkeypatch.setattr(knowledge_module, "retrieve", spy)
    return queries


@pytest.fixture
def executed_tools(monkeypatch):
    calls = []
    original = orchestrator.support.executor.execute

    def spy(tool_name, *args, **kwargs):
        calls.append(tool_name)
        return original(tool_name, *args, **kwargs)

    monkeypatch.setattr(orchestrator.support.executor, "execute", spy)
    return calls


def test_a_crediario_after_package_costs_question(retrieval_queries):
    _chat("Quais os custos desses dois pacotes?", "isolation-a")
    question = "O crediário parcela em quantas vezes?"

    payload = _chat(question, "isolation-a")

    assert retrieval_queries[-1] == question
    assert payload["agent"] == "knowledge"
    assert any("crediário" in source.lower() for source in payload["sources"])
    assert not any("pacotes" in source.lower() for source in payload["sources"])


def test_b_pix_after_card_machine_question(retrieval_queries):
    _chat("Quais os diferenciais de uma Get Smart?", "isolation-b")
    question = "Do I need a bank account to receive my sales via Pix?"

    payload = _chat(question, "isolation-b")

    assert retrieval_queries[-1] == question
    assert payload["agent"] == "knowledge"
    assert any("pix" in source.lower() for source in payload["sources"])
    assert not any("get smart" in source.lower() for source in payload["sources"])


def test_c_receivables_advance_after_other_product(retrieval_queries):
    _chat("Can I sell through WhatsApp using the Payment Link?", "isolation-c")
    question = "How does receivables advance (antecipação) work with Getnet?"

    payload = _chat(question, "isolation-c")

    assert retrieval_queries[-1] == question
    assert payload["agent"] == "knowledge"
    assert any("antecip" in source.lower() for source in payload["sources"])
    assert not any("link de pagamento" in source.lower() for source in payload["sources"])


def test_d_support_followup_continues_without_customer_tools(executed_tools):
    first = _chat("Minha maquininha está sem internet.", "isolation-d")
    assert first["agent"] == "customer_support"
    assert first["awaiting_user_input"] is True

    second = _chat("Já reiniciei e continua igual.", "isolation-d")

    assert second["agent"] == "customer_support"
    assert second["awaiting_user_input"] is False
    assert second["step_status"] == "handoff"
    assert second["handoff_required"] is True
    assert second["tool_used"] is None
    assert "continues a support flow" in second["routing_reason"]
    assert executed_tools == []
    ticket_message = second["handoff"]["message"]
    assert "sem internet" in ticket_message
    assert "reiniciei" in ticket_message


def test_d_connectivity_followup_does_not_generate_instructions(monkeypatch):
    def forbidden(self, message, context):
        raise AssertionError("o follow-up não deve chamar o LLM")

    monkeypatch.setattr(KnowledgeAgent, "_generate", forbidden)
    _chat("My card machine won't connect to the internet, what should I do?", "isolation-d2")

    payload = _chat("The wifi shows as available and the screen says network error", "isolation-d2")

    assert payload["agent"] == "customer_support"
    assert payload["handoff_required"] is True


def test_e_scenarios_in_distinct_sessions_do_not_share_state(retrieval_queries):
    ticket = _chat("Preciso falar com um atendente humano.", "isolation-e1")
    assert ticket["handoff_required"] is True

    payload = _chat("Minha transação txn1001 tem qual status?", "isolation-e2")

    assert payload["agent"] == "customer_support"
    assert payload["tool_used"] == "lookup_transaction"
    assert payload["handoff"] is None
    assert handoff_store.find_active_for_session(
        user_id="cliente1988", session_id="isolation-e2"
    ) is None


def test_official_scenarios_in_one_session_keep_retrieval_queries_clean(
    monkeypatch, retrieval_queries
):
    web_messages = []

    def fake_web_answer(self, message):
        web_messages.append(message)
        return {
            "agent": "web_search",
            "response": "Resposta externa simulada.",
            "sources": [],
            "tool_used": "fake_web",
        }

    monkeypatch.setattr(WebSearchAgent, "answer", fake_web_answer)

    results = [_chat(message, "isolation-official") for message in OFFICIAL_SCENARIOS]

    assert set(retrieval_queries) <= set(OFFICIAL_SCENARIOS)
    assert web_messages == [OFFICIAL_SCENARIOS[1], OFFICIAL_SCENARIOS[6]]
    for index in (0, 3, 5, 8, 9):
        assert results[index]["agent"] == "knowledge"
        assert results[index]["sources"], OFFICIAL_SCENARIOS[index]
    assert results[7]["handoff_required"] is False


def test_new_question_generation_ignores_history(monkeypatch):
    contexts = []

    def fake_generate(self, message, context):
        contexts.append(context)
        return "Resposta gerada."

    monkeypatch.setattr(KnowledgeAgent, "_generate", fake_generate)

    _chat("Quais os diferenciais de uma Get Smart?", "isolation-new-generation")
    _chat("Como funciona a antecipação de vendas?", "isolation-new-generation")

    assert "Histórico recente da conversa" not in contexts[-1]
    assert "diferenciais de uma Get Smart" not in contexts[-1]


def test_short_reference_history_reaches_generation_not_retrieval(monkeypatch, retrieval_queries):
    contexts = []

    def fake_generate(self, message, context):
        contexts.append(context)
        return "Resposta gerada."

    monkeypatch.setattr(KnowledgeAgent, "_generate", fake_generate)

    question = "Como funciona a antecipação de vendas?"
    _chat(question, "isolation-generation")
    _chat("E essa?", "isolation-generation")

    assert retrieval_queries[-1] == question
    assert "Histórico recente da conversa" in contexts[-1]
    assert f"Usuário: {question}" in contexts[-1]
    assert "Assistente:" not in contexts[-1]


def test_support_receives_only_current_message(monkeypatch):
    seen = []
    original = orchestrator.support.answer

    def spy(message, user_id):
        seen.append(message)
        return original(message=message, user_id=user_id)

    monkeypatch.setattr(orchestrator.support, "answer", spy)

    _chat("Minha transação txn1001 foi recusada.", "isolation-support")
    _chat("Qual o status da transação txn1002?", "isolation-support")

    assert seen[-1] == "Qual o status da transação txn1002?"


def test_short_reference_still_uses_previous_question(retrieval_queries):
    _chat("Como funciona a antecipação de vendas?", "isolation-reference")

    payload = _chat("E essa?", "isolation-reference")

    assert payload["agent"] == "knowledge"
    assert retrieval_queries[-1] == "Como funciona a antecipação de vendas?"


def test_new_question_wins_over_pending_support_flow():
    _chat("Minha maquininha está sem internet.", "isolation-new-intent")

    payload = _chat("Como funciona o Pix?", "isolation-new-intent")

    assert payload["agent"] == "knowledge"


def test_unrelated_reply_does_not_open_ticket_from_pending_flow():
    _chat("Minha maquininha está sem internet.", "isolation-thanks")

    payload = _chat("Obrigado", "isolation-thanks")

    assert payload["agent"] == "fallback"
    assert payload["handoff_required"] is False


PENDING_ISSUE = "Minha maquininha está sem internet."


@pytest.mark.parametrize(
    "message, expected_agent",
    [
        ("Meu saldo continua errado", "customer_support"),
        ("O pagamento continua pendente", "fallback"),
        ("Quero saber se a taxa continua igual", "knowledge"),
        ("I still want to know about Pix", "knowledge"),
        ("Obrigado, resolvi reiniciando", "fallback"),
        ("Reiniciei e voltou a funcionar, já está conectando", "fallback"),
        ("Já resolveu, obrigado", "fallback"),
        ("It's working now after a restart", "fallback"),
    ],
)
def test_independent_or_resolved_message_does_not_resume_flow(message, expected_agent):
    session = f"isolation-negative-{abs(hash(message))}"
    _chat(PENDING_ISSUE, session)

    payload = _chat(message, session)

    assert payload["agent"] == expected_agent
    assert payload["handoff"] is None
    assert handoff_store.find_active_for_session(
        user_id="cliente1988", session_id=session
    ) is None


@pytest.mark.parametrize(
    "message",
    [
        "Já reiniciei e continua igual.",
        "Reiniciei e não resolveu",
        "Não funcionou",
        "Ainda não conecta, continua sem sinal",
        "Obrigado, mas continua igual",
        "Erro na tela",
        "The wifi shows as available and the screen says network error",
        "Restarted it and it still didn't work",
    ],
)
def test_real_continuation_resumes_flow(message):
    session = f"isolation-positive-{abs(hash(message))}"
    _chat(PENDING_ISSUE, session)

    payload = _chat(message, session)

    assert payload["agent"] == "customer_support"
    assert "continues a support flow" in payload["routing_reason"]
    assert payload["handoff_required"] is True


def test_routed_connectivity_continuation_resumes_flow():
    _chat(PENDING_ISSUE, "isolation-routed")

    payload = _chat("A maquininha continua sem funcionar", "isolation-routed")

    assert "continues a support flow" in payload["routing_reason"]
    assert payload["handoff_required"] is True


@pytest.mark.parametrize(
    "message",
    ["Minha transação txn1001 continua recusada", "A txn1001 continua igual"],
)
def test_transaction_id_wins_over_pending_flow(message, executed_tools):
    session = f"isolation-txn-{abs(hash(message))}"
    _chat(PENDING_ISSUE, session)

    payload = _chat(message, session)

    assert payload["tool_used"] == "lookup_transaction"
    assert payload["handoff_required"] is False
    assert executed_tools == ["lookup_transaction"]


def test_question_wins_over_pending_flow():
    _chat(PENDING_ISSUE, "isolation-question")

    payload = _chat("A maquininha continua aceitando Pix?", "isolation-question")

    assert payload["agent"] == "knowledge"
    assert payload["handoff_required"] is False


def test_web_search_never_receives_history(monkeypatch):
    local = ChatOrchestrator()
    seen = []
    monkeypatch.setattr(
        local.router,
        "route",
        lambda message, routing_context=None: RoutingDecision(
            agent="web_search", reason="test"
        ),
    )

    def fake_web(message):
        seen.append(message)
        return {"agent": "web_search", "response": "ok", "sources": []}

    monkeypatch.setattr(local.web_search, "answer", fake_web)

    local.handle(
        "E essa?",
        "cliente1988",
        routing_context="Qual a cotação do euro?",
        conversation_context=["Usuário: Como funciona o Pix?"],
    )

    assert seen == ["Qual a cotação do euro?"]


def _open_connectivity_ticket(session: str) -> dict:
    _chat(PENDING_ISSUE, session)
    return _chat("Já reiniciei e continua igual.", session)


def _tickets(session: str) -> list[dict]:
    return [
        record for record in handoff_store._records.values()
        if record["session_id"] == session
    ]


def test_active_ticket_is_reused_for_same_flow_and_session():
    first = _open_connectivity_ticket("isolation-dedupe")
    second = _open_connectivity_ticket("isolation-dedupe")

    assert second["handoff"]["id"] == first["handoff"]["id"]
    assert first["handoff"]["id"] in second["response"]
    assert second["handoff_required"] is True
    assert len(_tickets("isolation-dedupe")) == 1


def test_completed_ticket_allows_new_ticket_for_same_flow():
    first = _open_connectivity_ticket("isolation-reopen")
    handoff_store.assume(first["handoff"]["id"], "atendente_01")
    handoff_store.complete(first["handoff"]["id"], "Resolvido pelo atendente.")

    second = _open_connectivity_ticket("isolation-reopen")

    assert second["handoff"]["id"] != first["handoff"]["id"]
    assert len(_tickets("isolation-reopen")) == 2


def test_active_ticket_is_not_shared_between_sessions():
    first = _open_connectivity_ticket("isolation-dedupe-a")
    second = _open_connectivity_ticket("isolation-dedupe-b")

    assert second["handoff"]["id"] != first["handoff"]["id"]


def test_ticket_from_other_flow_does_not_block_connectivity_ticket():
    other = _chat("Preciso falar com um atendente humano.", "isolation-other-flow")

    connectivity = _open_connectivity_ticket("isolation-other-flow")

    assert connectivity["handoff"]["id"] != other["handoff"]["id"]
    assert len(_tickets("isolation-other-flow")) == 2


def test_pending_followup_lasts_one_turn_and_survives_reload(tmp_path):
    path = tmp_path / "memory.json"
    memory = SessionMemory(storage_path=str(path))
    pending = {"flow": "terminal_connectivity", "original_message": "Sem internet"}
    memory.add_message(
        user_id="u", session_id="s", message="m", response="r", pending_followup=pending
    )

    reloaded = SessionMemory(storage_path=str(path))
    assert reloaded.get_pending_followup(user_id="u", session_id="s") == pending

    reloaded.add_message(user_id="u", session_id="s", message="m2", response="r2")
    assert reloaded.get_pending_followup(user_id="u", session_id="s") is None


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"isolation_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_scenarios_uses_exclusive_session_per_scenario(monkeypatch):
    module = _load_script("check_scenarios.py")
    sessions = []

    def fake_chat(message, user_id="cliente1988", session_id=None):
        sessions.append(session_id)
        return {"response": "ok", "agent": "knowledge"}

    monkeypatch.setattr(module, "chat", fake_chat)
    monkeypatch.setattr(module, "load_local_env", lambda: None)

    module.main()

    assert len(sessions) == len(module.SCENARIOS)
    assert len(set(sessions)) == len(sessions)
    assert all(sessions)


def test_validate_functionality_isolates_and_allows_explicit_shared_session(monkeypatch):
    module = _load_script("validate_functionality.py")
    scenario = {"message": "Oi", "user_id": "cliente1988", "expect_agent": "fallback"}
    monkeypatch.setattr(module, "SCENARIOS", [
        {**scenario, "name": "a"},
        {**scenario, "name": "b"},
        {**scenario, "name": "c", "session_id": "multi-turn"},
        {**scenario, "name": "d", "session_id": "multi-turn"},
    ])

    sessions = [record["input"]["session_id"] for record in module.run_validation()]

    assert sessions[0] != sessions[1]
    assert sessions[2] == sessions[3] == "multi-turn"
