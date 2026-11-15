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
    ChatOrchestrator,
    PlanStep,
)

L48_SNIPPET = "Negada: Venda não autorizada pelo emissor/ bandeira do cartão"
PIX_STATUS_SNIPPET = "Qr Code Expirado"


@pytest.fixture
def knowledge_calls(monkeypatch):
    """Captura a pergunta, o contexto e os kwargs que chegam ao Knowledge."""
    calls = []
    original_answer = KnowledgeAgent.answer

    def recording_answer(self, message, **kwargs):
        calls.append({"message": message, "kwargs": kwargs})
        return original_answer(self, message, **kwargs)

    def recording_generate(self, message, context):
        calls[-1]["context"] = context
        return "Uma venda negada é uma venda não autorizada pelo emissor ou pela bandeira do cartão."

    monkeypatch.setattr(KnowledgeAgent, "answer", recording_answer)
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


def test_declined_without_reason_adds_knowledge_with_general_meaning(knowledge_calls):
    execution = handle("The transaction is txn1003.")
    result = execution.result

    # Plano: Support e depois Knowledge, decidido pelo resultado da ferramenta.
    assert execution.executed_steps == ("customer_support", "knowledge")
    assert [step.agent for step in execution.plan.steps] == ["customer_support", "knowledge"]
    assert execution.trace[1].reason.startswith(
        "lookup_transaction returned a declined transaction with no recorded reason"
    )
    assert [(step.agent, step.status) for step in execution.trace] == [
        ("customer_support", "success"),
        ("knowledge", "success"),
    ]

    # O Knowledge recebe a consulta fixa, sem os fatos da transação, e o contexto
    # tem o documento de status de vendas com cartão (L48), sem o de Pix.
    assert len(knowledge_calls) == 1
    call = knowledge_calls[0]
    assert call["message"] == DECLINED_SALE_QUERY
    assert "verified_facts" not in call["kwargs"]
    assert L48_SNIPPET in call["context"]
    assert PIX_STATUS_SNIPPET not in call["context"]
    assert "txn1003" not in call["message"] + call["context"]

    # Campos principais representam a etapa principal (compatibilidade com S08).
    assert result["agent"] == "customer_support"
    assert result["tool_used"] == "lookup_transaction"
    assert result["step_status"] == "success"

    # Resposta em partes distinguíveis: fato verificado, depois explicação geral.
    facts_part, general_part = result["response"].split(DECLINED_SALE_HEADING)
    assert "txn1003" in facts_part and "recusada" in facts_part
    assert re.search(r"n[aã]o h[aá].{0,40}motivo", facts_part.lower())
    assert "emissor" in general_part
    assert "txn1003" not in general_part
    assert "explicação geral; não é o motivo registrado desta transação" in DECLINED_SALE_HEADING
    for invented in ("Cartão bloqueado", "AUTH_DECLINED", "saldo insuficiente"):
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


def test_official_s08_conversation_now_reaches_l48(knowledge_calls):
    """Os dois turnos do S08 pela API: o segundo agora aciona o Knowledge."""
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
    assert L48_SNIPPET in knowledge_calls[-1]["context"]
    assert json.dumps(payloads[1], ensure_ascii=False).count("Cartão bloqueado") == 0
