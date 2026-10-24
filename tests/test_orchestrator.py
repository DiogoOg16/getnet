from app.orchestrator import ChatOrchestrator


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
