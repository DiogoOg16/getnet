"""ARCH-02: o orquestrador decide a próxima etapa a partir do resultado
verificado de lookup_transaction.

| Resultado | Próxima etapa |
|---|---|
| aprovada ou pendente | nenhuma |
| negada com motivo registrado | nenhuma (motivo verificado vem do Support) |
| negada sem motivo registrado | Knowledge, com o significado geral de venda negada |
| erro de ferramenta | nenhuma |

Usa o Customer Support real com o cliente LLM falso do conftest e a
recuperação real; a geração do Knowledge é capturada, sem Ollama.
"""

import json
import re

import pytest

from app.agents.knowledge import KnowledgeAgent
from app.orchestrator import (
    DECLINED_SALE_HEADING,
    DECLINED_SALE_QUERY,
    DECLINED_SALE_TERM,
    ChatOrchestrator,
    PlanStep,
)

L48_SNIPPET = "Negada: Venda não autorizada pelo emissor/ bandeira do cartão"
PIX_STATUS_SNIPPET = "Qr Code Expirado"


@pytest.fixture
def knowledge_calls(monkeypatch):
    """Captura cada chamada ao Knowledge (geração ou citação) e o que o LLM recebe."""
    calls = []
    original_answer = KnowledgeAgent.answer
    original_quote = KnowledgeAgent.quote

    def recording_answer(self, message, **kwargs):
        calls.append({"kind": "answer", "message": message, "kwargs": kwargs})
        return original_answer(self, message, **kwargs)

    def recording_quote(self, query, term):
        result = original_quote(self, query, term)
        calls.append({"kind": "quote", "message": query, "term": term, "result": result})
        return result

    def recording_generate(self, message, context):
        calls[-1]["context"] = context
        calls[-1]["generated"] = True
        return "Uma venda negada é uma venda não autorizada pelo emissor ou pela bandeira do cartão."

    monkeypatch.setattr(KnowledgeAgent, "answer", recording_answer)
    monkeypatch.setattr(KnowledgeAgent, "quote", recording_quote)
    monkeypatch.setattr(KnowledgeAgent, "_generate", recording_generate)
    return calls


def handle(message: str, user_id: str = "cliente1988"):
    return ChatOrchestrator().handle(message, user_id, request_id="req-test")


@pytest.mark.parametrize(
    ("message", "status_text"),
    [
        ("Qual o status da transação txn1001?", "aprovada"),
        ("Qual o status da transação txn1002?", "pendente"),
    ],
)
def test_approved_or_pending_transaction_runs_support_only(knowledge_calls, message, status_text):
    execution = handle(message)

    assert execution.executed_steps == ("customer_support",)
    assert knowledge_calls == []
    assert status_text in execution.result["response"]


def test_declined_with_recorded_reason_uses_the_verified_reason_only(knowledge_calls):
    execution = handle("Qual o status da transação txn2001?", user_id="cliente2001")

    assert execution.executed_steps == ("customer_support",)
    assert knowledge_calls == []
    assert "Motivo da recusa: Cartão bloqueado pelo emissor." in execution.result["response"]


def test_declined_without_reason_adds_knowledge_quoting_l48(knowledge_calls):
    execution = handle("The transaction is txn1003.")
    result = execution.result

    # Plano: Support e depois Knowledge, decidido pelo resultado da ferramenta.
    assert execution.executed_steps == ("customer_support", "knowledge")
    assert [step.agent for step in execution.plan.steps] == ["customer_support", "knowledge"]
    assert execution.trace[1].reason.startswith(
        "lookup_transaction returned a declined transaction with no recorded reason"
    )
    assert [(step.agent, step.tool_used, step.status) for step in execution.trace] == [
        ("customer_support", "lookup_transaction", "success"),
        ("knowledge", "retrieval_quote", "success"),
    ]

    # O Knowledge cita, não gera: consulta fixa, termo "Negada", sem LLM e sem
    # os fatos da transação.
    assert len(knowledge_calls) == 1
    call = knowledge_calls[0]
    assert call["kind"] == "quote"
    assert call["message"] == DECLINED_SALE_QUERY
    assert call["term"] == DECLINED_SALE_TERM
    assert "generated" not in call
    assert PIX_STATUS_SNIPPET not in call["result"]["response"]

    # Campos principais representam a etapa principal (compatibilidade com S08).
    assert result["agent"] == "customer_support"
    assert result["tool_used"] == "lookup_transaction"
    assert result["step_status"] == "success"

    # Resposta em partes distinguíveis: fato verificado, depois o trecho citado.
    facts_part, general_part = result["response"].split(DECLINED_SALE_HEADING)
    assert "txn1003" in facts_part and "recusada" in facts_part
    assert re.search(r"n[aã]o h[aá].{0,40}motivo", facts_part.lower())
    assert general_part.strip() == (
        f"“{L48_SNIPPET}.” (Fonte: Quais são os possíveis status das minhas vendas? - Getnet)"
    )
    assert "txn1003" not in general_part
    for invented in ("Cartão bloqueado", "AUTH_DECLINED", "saldo insuficiente", "limite", "fraude"):
        assert invented not in result["response"]
    facts = {(fact["entity"], fact["name"]): fact["value"] for fact in result["verified_facts"]}
    assert facts[("txn1003", "status")] == "declined"


def test_tool_error_does_not_add_knowledge(monkeypatch, knowledge_calls):
    orchestrator = ChatOrchestrator()
    monkeypatch.setattr(
        orchestrator.support,
        "answer",
        lambda *, message, user_id: {
            "agent": "customer_support",
            "response": "Não foi possível consultar a transação neste momento porque o serviço de ferramentas falhou.",
            "tool_used": None,
            "function_call_status": "tool_call_error",
            "awaiting_user_input": True,
            "step_status": "tool_call_error",
            "verified_facts": [],
        },
    )

    execution = orchestrator.handle("The transaction is txn1003.", "cliente1988")

    assert execution.executed_steps == ("customer_support",)
    assert knowledge_calls == []
    assert "motivo" not in execution.result["response"].lower()


def test_transaction_not_found_does_not_add_knowledge(knowledge_calls):
    execution = handle("Qual o status da transação txn2001?", user_id="cliente1988")

    assert execution.executed_steps == ("customer_support",)
    assert knowledge_calls == []


def test_followup_respects_max_steps_and_does_not_duplicate_agents(knowledge_calls):
    orchestrator = ChatOrchestrator()
    declined = {
        "step_status": "success",
        "tool_used": "lookup_transaction",
        "decline_reason_recorded": False,
        "verified_facts": [
            {"name": "status", "value": "declined", "source_tool": "lookup_transaction"},
        ],
    }
    support = PlanStep(agent="customer_support", reason="support")

    assert orchestrator._followup_step(support, declined).agent == "knowledge"
    assert orchestrator._followup_step(PlanStep(agent="knowledge", reason="k"), declined) is None
    assert orchestrator._followup_step(support, {**declined, "decline_reason_recorded": True}) is None
    assert orchestrator._followup_step(support, {**declined, "step_status": "tool_call_error"}) is None

    # A mensagem já pede orientação: o plano estático tem Support + Knowledge e a
    # decisão pelo resultado não acrescenta um segundo Knowledge.
    execution = orchestrator.handle("Por que a transação txn1003 foi recusada?", "cliente1988")
    assert execution.executed_steps == ("customer_support", "knowledge")
    assert len(execution.plan.steps) <= execution.plan.max_steps == 3


def test_official_s08_conversation_now_quotes_l48(knowledge_calls):
    """Os dois turnos do S08 pela API: o segundo cita a definição de L48."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, headers={"Authorization": "Bearer test-token-cliente1988"})
    turns = ["My card machine is showing a transaction decline error.", "The transaction is txn1003."]
    payloads = [
        client.post("/chat", json={"message": turn, "user_id": "cliente1988", "session_id": "arch02"}).json()
        for turn in turns
    ]

    assert payloads[0]["awaiting_user_input"] is True
    assert [step["agent"] for step in payloads[1]["trace"]] == ["customer_support", "knowledge"]
    assert payloads[1]["agent"] == "customer_support"
    assert payloads[1]["tool_used"] == "lookup_transaction"
    assert L48_SNIPPET in payloads[1]["response"]
    assert [call["kind"] for call in knowledge_calls] == ["quote"]
    assert json.dumps(payloads[1], ensure_ascii=False).count("Cartão bloqueado") == 0


# --- P2: citação literal no Knowledge -----------------------------------------

L48_CONTENT_EXAMPLE = (
    "Entenda os status. • Autorizada: Venda aprovada pelo emissor. "
    "• Negada: Venda não autorizada pelo emissor/ bandeira do cartão. "
    "• Desfeita: Ocorre quando a transação não é aprovada dentro do prazo."
)


@pytest.mark.parametrize("term", ["Negada", "negada", "NEGADA"])
def test_find_passage_returns_the_item_text(term):
    assert KnowledgeAgent._find_passage(L48_CONTENT_EXAMPLE, term) == (
        "Negada: Venda não autorizada pelo emissor/ bandeira do cartão."
    )


@pytest.mark.parametrize("term", ["Neg", "Recusada", "emissor"])
def test_find_passage_requires_the_exact_label(term):
    assert KnowledgeAgent._find_passage(L48_CONTENT_EXAMPLE, term) is None


def test_quote_never_calls_the_llm(monkeypatch):
    def no_llm(self, message, context):
        raise AssertionError("a citação não pode chamar o LLM")

    monkeypatch.setattr(KnowledgeAgent, "_generate", no_llm)

    result = KnowledgeAgent().quote(DECLINED_SALE_QUERY, DECLINED_SALE_TERM)

    assert result["tool_used"] == "retrieval_quote"
    assert result["response"].startswith(f"“{L48_SNIPPET}.”")
    assert result["sources"] == ["Quais são os possíveis status das minhas vendas?\xa0 - Getnet"]


NO_DEFINITION = [{"title": "Outro documento", "content": "Texto sem a definição do status."}]


def test_quote_reports_no_evidence_when_no_document_defines_the_term(monkeypatch, caplog):
    import logging

    caplog.set_level(logging.WARNING, logger="getnet_knowledge")
    monkeypatch.setattr("app.agents.knowledge.retrieve", lambda query, limit=3: NO_DEFINITION)

    result = KnowledgeAgent().quote("qualquer", "Negada")

    assert result["step_status"] == "no_evidence"
    assert result["issue_resolved"] is False
    assert result["sources"] == []
    assert result["response"] == (
        "A documentação recuperada não traz a definição desse status, então não há trecho para citar."
    )
    assert any("knowledge_quote_not_found term=Negada retrieved=1" in r.getMessage() for r in caplog.records)


def test_quote_miss_is_visible_in_the_trace_but_keeps_the_verified_answer(monkeypatch):
    monkeypatch.setattr("app.agents.knowledge.retrieve", lambda query, limit=3: NO_DEFINITION)

    execution = handle("The transaction is txn1003.")
    result = execution.result

    assert [(step.agent, step.tool_used, step.status) for step in execution.trace] == [
        ("customer_support", "lookup_transaction", "success"),
        ("knowledge", "retrieval_quote", "no_evidence"),
    ]
    # A pergunta (status da transação) foi respondida pelo fato verificado.
    assert result["step_status"] == "success"
    assert result["agent"] == "customer_support"
    facts_part, general_part = result["response"].split(DECLINED_SALE_HEADING)
    assert "txn1003" in facts_part and "recusada" in facts_part
    assert "não traz a definição desse status" in general_part
    for invented in ("limite", "fraude", "bloqueado", "saldo"):
        assert invented not in result["response"]


def test_trace_reports_a_failed_step_as_failed(monkeypatch):
    from app.agents import web_search

    monkeypatch.setattr(web_search, "get_forecast", lambda city, tomorrow=False: {"found": False, "error": "unavailable"})

    execution = handle("What's the weather forecast in Porto Alegre tomorrow?")

    assert [(step.agent, step.status) for step in execution.trace] == [("web_search", "failed")]
    assert execution.result["step_status"] == "failed"
