import pytest

from app.agents.router import RoutingDecision
from app.verified_facts import make_verified_fact
from app.orchestrator import (
    DECLINED_SALE_HEADING,
    DECLINED_SALE_QUERY,
    DECLINED_SALE_TERM,
    ChatOrchestrator,
    ExecutionPlan,
    PlanStep,
)


def test_simple_question_uses_only_the_routed_agent():
    orchestrator = ChatOrchestrator()

    decision, plan = orchestrator.create_plan("Como funciona o Pix da Getnet?")

    assert len(plan.steps) == 1
    assert plan.steps[0].agent == decision.agent == "knowledge"
    assert plan.max_steps > 0


def test_declined_transaction_question_plans_support_only():
    # O Knowledge não entra pelo texto da mensagem: é acrescentado na execução,
    # se a consulta mostrar a transação negada sem motivo registrado (P1).
    orchestrator = ChatOrchestrator()

    decision, plan = orchestrator.create_plan(
        "Por que a transação txn2001 foi recusada e como resolver?"
    )

    assert decision.agent == "customer_support"
    assert [step.agent for step in plan.steps] == ["customer_support"]


def declined_without_reason(transaction_id, response):
    """Resultado do Support como o de lookup_transaction: negada, sem motivo registrado."""
    return {
        "agent": "customer_support",
        "response": response,
        "tool_used": "lookup_transaction",
        "sources": [],
        "step_status": "success",
        "decline_reason_recorded": False,
        "verified_facts": [
            make_verified_fact(
                entity=transaction_id, name="status", value="declined",
                source_agent="customer_support", source_tool="lookup_transaction",
            )
        ],
    }


def test_two_agents_cooperate_and_merge_results(monkeypatch):
    orchestrator = ChatOrchestrator()
    calls = []

    def fake_support(*, message, user_id):
        calls.append(("customer_support", message, user_id))
        return declined_without_reason("txn2001", "A transação txn2001 está recusada. Valor: R$ 250,00.")

    def fake_quote(query, term):
        calls.append(("knowledge", query, term))
        return {
            "agent": "knowledge",
            "response": "“Negada: Venda não autorizada pelo emissor/ bandeira do cartão.” (Fonte: Status das vendas)",
            "tool_used": "retrieval_quote",
            "sources": ["Status das vendas"],
            "source_sections": {"Vendas": ["Status das vendas"]},
        }

    def no_generation(*args, **kwargs):
        raise AssertionError("a etapa de venda recusada cita a base; não gera texto (P2)")

    monkeypatch.setattr(orchestrator.support, "answer", fake_support)
    monkeypatch.setattr(orchestrator.knowledge, "quote", fake_quote)
    monkeypatch.setattr(orchestrator.knowledge, "answer", no_generation)

    message = "Por que a transação txn2001 foi recusada e como resolver?"
    execution = orchestrator.handle(message, "cliente2001")

    assert execution.executed_steps == ("customer_support", "knowledge")
    # O Knowledge recebe a pergunta geral sobre venda negada, não a mensagem com a transação.
    assert calls == [
        ("customer_support", message, "cliente2001"),
        ("knowledge", DECLINED_SALE_QUERY, DECLINED_SALE_TERM),
    ]
    # Contrato multi-etapa: agent e tool_used representam a etapa principal;
    # o trace registra todos os agentes e ferramentas.
    assert execution.result["agent"] == "customer_support"
    assert "R$ 250,00" in execution.result["response"]
    assert DECLINED_SALE_HEADING in execution.result["response"]
    assert execution.result["sources"] == ["Status das vendas"]
    assert execution.result["tool_used"] == "lookup_transaction"
    assert [(step.agent, step.tool_used) for step in execution.trace] == [
        ("customer_support", "lookup_transaction"),
        ("knowledge", "retrieval_quote"),
    ]


def test_orchestrator_continues_when_next_step_is_valid_even_after_success(monkeypatch):
    orchestrator = ChatOrchestrator()
    custom_plan = ExecutionPlan(
        steps=(
            PlanStep(agent="customer_support", reason="support"),
            PlanStep(agent="knowledge", reason="knowledge"),
            PlanStep(agent="web_search", reason="web"),
        ),
        max_steps=3,
    )

    monkeypatch.setattr(
        orchestrator,
        "create_plan",
        lambda message: (
            RoutingDecision(agent="customer_support", reason="support"),
            custom_plan,
        ),
    )
    monkeypatch.setattr(
        orchestrator.support,
        "answer",
        lambda *, message, user_id: {
            "agent": "customer_support",
            "response": "A transação foi consultada.",
            "tool_used": "lookup_transaction",
            "sources": [],
        },
    )
    monkeypatch.setattr(
        orchestrator.knowledge,
        "answer",
        lambda message: {
            "agent": "knowledge",
            "response": "Acesso à Get Conta confirmado pela documentação oficial.",
            "tool_used": "retrieval_only",
            "sources": ["Portal Minha Conta"],
            "resolved": True,
            "source_sections": {"Portal": ["Portal Minha Conta"]},
        },
    )
    monkeypatch.setattr(
        orchestrator.web_search,
        "answer",
        lambda message: {
            "agent": "web_search",
            "response": "Não deveria ser executado.",
            "tool_used": "search",
            "sources": [],
        },
    )

    execution = orchestrator.handle("Como acesso a minha Get Conta?", "cliente2001")

    assert execution.executed_steps == (
        "customer_support",
        "knowledge",
        "web_search",
    )
    assert "Get Conta" in execution.result["response"]
    assert execution.result["agent"] == "customer_support"
    assert [step.agent for step in execution.trace] == [
        "customer_support",
        "knowledge",
        "web_search",
    ]


def test_transaction_lookup_respects_customer_ownership():
    orchestrator = ChatOrchestrator()

    execution = orchestrator.handle(
        "Qual o status da transação txn2001?",
        "cliente1988",
    )

    assert execution.executed_steps == ("customer_support",)
    assert "Não encontrei essa transação" in execution.result["response"]


def test_human_handoff_stops_the_execution():
    orchestrator = ChatOrchestrator()

    execution = orchestrator.handle(
        "Preciso de atendimento humano para dados pessoais sensíveis.",
        "cliente1988",
    )

    assert execution.executed_steps == ("human_escalation",)
    assert execution.result["handoff_required"] is True
    assert execution.result["step_status"] == "handoff"


def test_execution_trace_records_each_agent_and_tool(monkeypatch):
    orchestrator = ChatOrchestrator()

    monkeypatch.setattr(
        orchestrator.support,
        "answer",
        lambda *, message, user_id: declined_without_reason("txn2001", "Transação consultada."),
    )
    monkeypatch.setattr(
        orchestrator.knowledge,
        "quote",
        lambda query, term: {
            "agent": "knowledge",
            "response": "“Negada: ...” (Fonte: Status)",
            "tool_used": "retrieval_quote",
            "sources": [],
            "step_status": "success",
        },
    )

    execution = orchestrator.handle(
        "Por que a transação txn2001 foi recusada e como resolver?",
        "cliente2001",
    )

    assert len(execution.trace) == 2
    assert execution.trace[0].agent == "customer_support"
    assert execution.trace[0].status == "success"
    assert execution.trace[0].tool_used == "lookup_transaction"
    assert execution.trace[1].agent == "knowledge"
    assert execution.trace[1].status == "success"
    assert execution.trace[1].tool_used == "retrieval_quote"
    assert all(step.reason for step in execution.trace)


def test_agent_exception_is_traced_and_stops_execution(monkeypatch):
    orchestrator = ChatOrchestrator()
    knowledge_called = []

    def failing_support(*, message, user_id):
        raise RuntimeError("internal details must not reach the user")

    def fake_knowledge(message):
        knowledge_called.append(message)
        return {
            "agent": "knowledge",
            "response": "Orientação.",
            "tool_used": "retrieval_only",
            "sources": [],
        }

    monkeypatch.setattr(orchestrator.support, "answer", failing_support)
    monkeypatch.setattr(orchestrator.knowledge, "answer", fake_knowledge)

    execution = orchestrator.handle(
        "Por que a transação txn2001 foi recusada e como resolver?",
        "cliente2001",
    )

    assert execution.trace[0].agent == "customer_support"
    assert execution.trace[0].status == "error"
    assert execution.trace[0].tool_used is None
    assert execution.executed_steps == ()
    assert knowledge_called == []
    assert execution.result["handoff_required"] is False
    assert execution.result["step_status"] == "failed"
    assert "internal details" not in execution.result["response"]


def test_intermediate_success_does_not_block_valid_next_step(monkeypatch):
    orchestrator = ChatOrchestrator()

    custom_plan = ExecutionPlan(
        steps=(
            PlanStep(agent="customer_support", reason="support"),
            PlanStep(agent="knowledge", reason="knowledge"),
        ),
        max_steps=2,
    )

    monkeypatch.setattr(
        orchestrator,
        "create_plan",
        lambda message: (
            RoutingDecision(agent="customer_support", reason="support"),
            custom_plan,
        ),
    )
    monkeypatch.setattr(
        orchestrator.support,
        "answer",
        lambda *, message, user_id: {
            "agent": "customer_support",
            "response": "A transação foi localizada.",
            "tool_used": "lookup_transaction",
            "sources": [],
            "flow_completed": True,
            "response_delivered": True,
            "issue_resolved": True,
            "awaiting_user_input": False,
            "step_status": "success",
        },
    )
    monkeypatch.setattr(
        orchestrator.knowledge,
        "answer",
        lambda message: {
            "agent": "knowledge",
            "response": "Orientação adicional da base.",
            "tool_used": "retrieval_only",
            "sources": ["Guia"],
            "flow_completed": True,
            "response_delivered": True,
            "issue_resolved": False,
            "awaiting_user_input": False,
            "step_status": "success",
        },
    )

    execution = orchestrator.handle("msg", "cliente2001")

    assert execution.executed_steps == ("customer_support", "knowledge")


@pytest.mark.parametrize(
    "support_result",
    [
        {"status": "approved", "decline_reason_recorded": None},
        {"status": "declined", "decline_reason_recorded": True},
    ],
    ids=["aprovada", "negada-com-motivo"],
)
def test_declined_question_about_a_transaction_that_does_not_need_knowledge_runs_support_only(monkeypatch, support_result):
    # "Por que foi recusada?" sobre uma transação aprovada, ou negada com motivo registrado:
    # o texto não acrescenta o Knowledge; só o resultado da consulta decidiria.
    orchestrator = ChatOrchestrator()
    result = declined_without_reason("txn2001", "Transação consultada.")
    result["verified_facts"][0]["value"] = support_result["status"]
    result["decline_reason_recorded"] = support_result["decline_reason_recorded"]
    monkeypatch.setattr(orchestrator.support, "answer", lambda *, message, user_id: result)

    def no_knowledge(*args, **kwargs):
        raise AssertionError("o Knowledge não deveria rodar")

    monkeypatch.setattr(orchestrator.knowledge, "quote", no_knowledge)
    monkeypatch.setattr(orchestrator.knowledge, "answer", no_knowledge)

    execution = orchestrator.handle("Por que a transação txn2001 foi recusada?", "cliente2001")

    assert execution.executed_steps == ("customer_support",)
