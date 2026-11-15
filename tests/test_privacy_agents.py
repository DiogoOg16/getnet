"""SEC-01 no processamento: depois do roteamento, os agentes (e o LLM, as
ferramentas e a busca externa) só recebem a mensagem mascarada.

Os payloads são capturados em clientes LLM falsos; nenhum teste chama o Ollama.
"""

import json

from fastapi.testclient import TestClient

from app.agents.knowledge import KnowledgeAgent
from app.main import app, orchestrator, session_memory

# Capturado na importação, antes de o conftest trocar _generate pelo falso.
REAL_GENERATE = KnowledgeAgent._generate

USER_EMAIL = "joao.silva@empresa.com.br"
USER_PHONE = "(11) 98765-4321"
USER_CPF = "123.456.789-09"
RAW_USER_VALUES = (USER_EMAIL, USER_PHONE, "98765-4321", USER_CPF)


def chat(message: str, session_id: str) -> dict:
    client = TestClient(app, headers={"Authorization": "Bearer test-token-cliente1988"})
    response = client.post(
        "/chat",
        json={"message": message, "user_id": "cliente1988", "session_id": session_id},
    )
    assert response.status_code == 200
    return response.json()


def assert_no_raw_user_values(text: str) -> None:
    for raw in RAW_USER_VALUES:
        assert raw not in text, f"dado pessoal {raw!r} presente: {text!r}"


def record_knowledge_llm(monkeypatch) -> list:
    """Usa o _generate real e um cliente que devolve tudo o que recebeu.

    Se o modelo recebesse o dado original, a resposta ecoada o conteria.
    """
    sent = []
    monkeypatch.setattr(KnowledgeAgent, "_generate", REAL_GENERATE)

    def fake_chat(messages, tools=None):
        sent.append(messages)
        echoed = "\n".join(message["content"] for message in messages)
        return {"message": {"role": "assistant", "content": echoed}}

    monkeypatch.setattr(orchestrator.knowledge.client, "chat", fake_chat)
    return sent


def test_knowledge_llm_never_receives_user_email_or_phone(monkeypatch):
    sent = record_knowledge_llm(monkeypatch)

    payload = chat(
        "Como os lojistas fazem a contratação do Link de Pagamento? "
        f"Meu e-mail é {USER_EMAIL} e meu celular é {USER_PHONE}",
        session_id="llm-knowledge",
    )

    assert payload["agent"] == "knowledge"
    assert len(sent) == 1
    llm_payload = json.dumps(sent, ensure_ascii=False)
    assert_no_raw_user_values(llm_payload)
    assert "Meu e-mail é [EMAIL] e meu celular é [TELEFONE]" in llm_payload
    # A resposta do modelo ecoa o payload e mesmo assim não tem o dado original.
    assert_no_raw_user_values(payload["response"])


def test_official_contacts_in_retrieved_documents_reach_the_llm(monkeypatch):
    sent = record_knowledge_llm(monkeypatch)

    payload = chat(
        f"Como os lojistas fazem a contratação do Link de Pagamento? Meu e-mail é {USER_EMAIL}",
        session_id="llm-official-contacts",
    )

    context = sent[0][1]["content"]
    # L192: contatos oficiais da Getnet, que não são dados do usuário.
    assert "suporte@edigital.com.br" in context
    assert "atendimento_atacado@getnet.com.br" in context
    assert "telefone 4002-4009" in context
    assert "4002-4000" in context
    assert "suporte@edigital.com.br" in payload["response"]
    assert USER_EMAIL not in context


def test_support_llm_gets_masked_message_and_tool_gets_identifiers(monkeypatch):
    fake_client = orchestrator.support.loop.client
    original_chat = fake_client.chat
    sent = []

    def recording_chat(messages, tools=None):
        sent.append(json.loads(json.dumps(messages)))
        return original_chat(messages, tools=tools)

    monkeypatch.setattr(fake_client, "chat", recording_chat)

    payload = chat(
        f"Qual o status da transação txn1001? Meu e-mail é {USER_EMAIL}, celular {USER_PHONE}",
        session_id="llm-support",
    )

    assert sent, "o loop de function calling deveria ter chamado o LLM"
    llm_payload = json.dumps(sent, ensure_ascii=False)
    assert_no_raw_user_values(llm_payload)
    assert "txn1001" in llm_payload
    # A ferramenta recebeu o identificador da transação e o user_id autenticado.
    assert payload["agent"] == "customer_support"
    assert payload["tool_used"] == "lookup_transaction"
    assert "txn1001" in payload["response"]
    assert "aprovada" in payload["response"]
    assert "149.90" in payload["response"]
    facts = {(fact["entity"], fact["name"]): fact["value"] for fact in payload["verified_facts"]}
    assert facts[("txn1001", "status")] == "approved"
    assert facts[("txn1001", "amount")] == 149.90


def test_web_search_agent_receives_masked_message(monkeypatch):
    received = []

    def fake_answer(message):
        received.append(message)
        return {
            "agent": "web_search",
            "response": "Previsão simulada.",
            "sources": [],
            "tool_used": "open_meteo",
            "step_status": "success",
        }

    monkeypatch.setattr(orchestrator.web_search, "answer", fake_answer)

    payload = chat(
        f"What's the weather forecast in Porto Alegre tomorrow? my email is {USER_EMAIL}",
        session_id="llm-web",
    )

    assert payload["agent"] == "web_search"
    assert received == ["What's the weather forecast in Porto Alegre tomorrow? my email is [EMAIL]"]


def test_router_still_sees_the_original_message_and_escalates_cpf():
    payload = chat(f"Meu CPF é {USER_CPF}, quero saber da minha conta", session_id="router-raw")

    assert payload["agent"] == "human_escalation"
    assert payload["handoff_required"] is True


# --- continuidade de conversa com referência curta -------------------------

def test_short_reference_after_cpf_keeps_context_without_the_cpf(monkeypatch):
    received = []
    original_answer = orchestrator.support.answer

    def recording_answer(message, user_id):
        received.append(message)
        return original_answer(message=message, user_id=user_id)

    monkeypatch.setattr(orchestrator.support, "answer", recording_answer)

    first = chat(f"Meu CPF é {USER_CPF}, quero saber da minha conta", session_id="short-ref-cpf")
    second = chat("e essa?", session_id="short-ref-cpf")

    assert first["agent"] == "human_escalation"
    # Mesmo roteamento do baseline 0c2d00f: a referência curta é resolvida para a
    # pergunta anterior e segue para o Customer Support.
    assert second["agent"] == "customer_support"
    assert second["routing_reason"] == (
        "The message uses recent support context to clarify the current request."
    )
    # O agente recebe a pergunta anterior, com o CPF mascarado.
    assert received == ["Meu CPF é [CPF], quero saber da minha conta"]
    for text in (
        json.dumps(first, ensure_ascii=False),
        json.dumps(second, ensure_ascii=False),
        session_memory.storage_path.read_text(encoding="utf-8"),
    ):
        assert USER_CPF not in text


def test_short_reference_after_email_keeps_the_knowledge_topic(monkeypatch):
    received = []

    def recording_generate(self, message, context):
        received.append(message)
        return "Resposta simulada baseada nos documentos recuperados."

    monkeypatch.setattr(KnowledgeAgent, "_generate", recording_generate)

    first = chat(
        f"Qual a diferença entre a Get Clássica e a Get Smart? meu email é {USER_EMAIL}",
        session_id="short-ref-email",
    )
    second = chat("e essa?", session_id="short-ref-email")

    assert first["agent"] == "knowledge"
    assert second["agent"] == "knowledge"
    assert second["routing_reason"] == (
        "The message references a recent Getnet topic and should use that contextual intent."
    )
    expected = "Qual a diferença entre a Get Clássica e a Get Smart? meu email é [EMAIL]"
    assert received[-1] == expected
    assert all(USER_EMAIL not in message for message in received)
