from app.agents.router import RoutingDecision
from app.orchestrator import ChatOrchestrator, ExecutionPlan, PlanStep


def test_simple_question_uses_only_the_routed_agent():
    orchestrator = ChatOrchestrator()

    decision, plan = orchestrator.create_plan("Como funciona o Pix da Getnet?")

    assert len(plan.steps) == 1
    assert plan.steps[0].agent == decision.agent == "knowledge"
    assert plan.max_steps > 0


def test_declined_transaction_with_guidance_creates_two_step_plan():
    orchestrator = ChatOrchestrator()

    decision, plan = orchestrator.create_plan(
        "Por que a transação txn2001 foi recusada e como resolver?"
    )

    assert decision.agent == "customer_support"
    assert [step.agent for step in plan.steps] == [
        "customer_support",
        "knowledge",
    ]


def test_two_agents_cooperate_and_merge_results(monkeypatch):
    orchestrator = ChatOrchestrator()
    calls = []

    def fake_support(*, message, user_id):
        calls.append(("customer_support", message, user_id))
        return {
            "agent": "customer_support",
            "response": "A transação txn2001 está recusada. Valor: R$ 250,00.",
            "tool_used": "lookup_transaction",
            "sources": [],
        }

    def fake_knowledge(message):
        calls.append(("knowledge", message))
        return {
            "agent": "knowledge",
            "response": "Consulte os possíveis status documentados das vendas.",
            "tool_used": "retrieval_only",
            "sources": ["Status das vendas"],
            "source_sections": {"Vendas": ["Status das vendas"]},
        }

    monkeypatch.setattr(orchestrator.support, "answer", fake_support)
    monkeypatch.setattr(orchestrator.knowledge, "answer", fake_knowledge)

    message = "Por que a transação txn2001 foi recusada e como resolver?"
    execution = orchestrator.handle(message, "cliente2001")

    assert execution.executed_steps == ("customer_support", "knowledge")
    assert calls == [
        ("customer_support", message, "cliente2001"),
        ("knowledge", message),
    ]
    assert execution.result["agent"] == "multi_agent"
    assert "R$ 250,00" in execution.result["response"]
    assert "Orientações da base de conhecimento" in execution.result["response"]
    assert execution.result["sources"] == ["Status das vendas"]
    assert execution.result["tool_used"] == "lookup_transaction, retrieval_only"


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
    assert execution.result["agent"] == "multi_agent"


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
        lambda *, message, user_id: {
            "agent": "customer_support",
            "response": "Transação consultada.",
            "tool_used": "lookup_transaction",
            "sources": [],
        },
    )
    monkeypatch.setattr(
        orchestrator.knowledge,
        "answer",
        lambda message: {
            "agent": "knowledge",
            "response": "Orientação documentada.",
            "tool_used": "retrieval_only",
            "sources": [],
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
    assert execution.trace[1].tool_used == "retrieval_only"
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
