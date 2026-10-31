from unittest.mock import patch

import pytest

from app.agents.customer_support import CustomerSupportAgent
from app.agents.knowledge import KnowledgeAgent
from app.orchestrator import ChatOrchestrator
from app.session_memory import SessionMemory
from app.verified_facts import (
    consolidate_verified_facts,
    is_valid_verified_fact,
    make_verified_fact,
    public_fact_conflicts,
    public_verified_facts,
)


def test_customer_support_exports_verified_facts_for_transaction_lookup():
    result = CustomerSupportAgent().answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["verified_facts"]
    fact = result["verified_facts"][0]
    assert fact["entity"] == "txn1001"
    assert fact["name"] == "status"
    assert fact["value"] == "approved"
    assert fact["verified"] is True
    assert fact["source_tool"] == "lookup_transaction"


def test_customer_support_does_not_invent_verified_fact_when_tool_fails():
    result = CustomerSupportAgent().answer(
        "Qual o status da transação txn9999?",
        "cliente1988",
    )

    assert result["verified_facts"] == []
    assert result["step_status"] == "waiting_for_user_input"


def test_knowledge_agent_consumes_verified_facts_without_creating_new_ones():
    verified_facts = [{
        "entity": "txn1001",
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_tool": "lookup_transaction",
        "source_agent": "customer_support",
    }]

    result = KnowledgeAgent().answer(
        "Por que a transação txn1001 foi recusada?",
        verified_facts=verified_facts,
    )

    assert "verified_facts" not in result
    assert result["response"]


def test_orchestrator_detects_conflicting_verified_facts_and_keeps_conflict_visible():
    orchestrator = ChatOrchestrator()
    result = orchestrator._combine_results([
        {
            "agent": "customer_support",
            "response": "Transação aprovada.",
            "source_sections": {},
            "sources": [],
            "tool_used": "lookup_transaction",
            "verified_facts": [{
                "entity": "txn1001",
                "name": "status",
                "value": "approved",
                "verified": True,
                "source_tool": "lookup_transaction",
                "source_agent": "customer_support",
            }],
            "issue_resolved": True,
            "resolved": True,
            "step_status": "success",
        },
        {
            "agent": "customer_support",
            "response": "Transação recusada.",
            "source_sections": {},
            "sources": [],
            "tool_used": "lookup_transaction",
            "verified_facts": [{
                "entity": "txn1001",
                "name": "status",
                "value": "declined",
                "verified": True,
                "source_tool": "lookup_transaction",
                "source_agent": "customer_support",
            }],
            "issue_resolved": True,
            "resolved": True,
            "step_status": "success",
        },
    ])

    assert result["fact_conflicts"]
    assert result["issue_resolved"] is False
    assert result["resolved"] is False
    assert result["step_status"] == "conflict"
    assert "conflito" in result["response"].lower()


def test_verified_facts_are_not_persisted_in_session_memory():
    session_memory = SessionMemory(storage_path="/tmp/getnet_verified_facts_test.json")
    session_memory.clear_session(user_id="cliente1988", session_id="session-verified-facts")
    session_memory.add_message(
        user_id="cliente1988",
        session_id="session-verified-facts",
        message="Qual o status da transação txn1001?",
        response="Resposta confirmada.",
    )

    assert session_memory.get_recent_context(
        user_id="cliente1988",
        session_id="session-verified-facts",
    )
    stored = session_memory._store.get("cliente1988:session-verified-facts")
    assert not any("verified_facts" in str(entry) for entry in stored)


def test_customer_support_followup_knowledge_cannot_upgrade_to_verified_facts():
    validated = [{
        "entity": "txn2001",
        "name": "status",
        "value": "declined",
        "verified": True,
        "source_tool": "lookup_transaction",
        "source_agent": "customer_support",
    }]

    result = KnowledgeAgent().answer(
        "Por que a transação txn2001 foi recusada e como resolver?",
        verified_facts=validated,
    )

    assert result.get("verified_facts") is None
    assertion_text = result["response"].lower()
    assert (
        "recusada" in assertion_text
        or "recusa" in assertion_text
        or "documentos" in assertion_text
    )


def test_consolidate_same_value_from_different_authorized_tools_is_not_a_conflict():
    facts = [
        {
            "entity": "txn1001",
            "name": "status",
            "value": "approved",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
        {
            "entity": "txn1001",
            "name": "status",
            "value": "approved",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_settlement",
        },
    ]

    unique, conflicts = consolidate_verified_facts(facts)

    assert len(unique) == 1
    assert unique[0]["value"] == "approved"
    assert unique[0]["source_provenance"] == [
        {"source_agent": "customer_support", "source_tool": "lookup_transaction"},
        {"source_agent": "customer_support", "source_tool": "lookup_settlement"},
    ]
    assert len(conflicts) == 0


def test_public_sanitization_rejects_invalid_origin_and_hides_sensitive_payloads():
    facts = [{
        "entity": "txn1001",
        "name": "status",
        "value": {
            "status": "approved",
            "customer_id": "cli-123",
            "internal_note": "secret",
        },
        "verified": True,
        "source_agent": "knowledge",
        "source_tool": "retrieval_only",
    }]

    assert public_verified_facts(facts) == []

    valid_fact = [{
        "entity": "txn1001",
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "lookup_transaction",
    }]

    sanitized = public_verified_facts(valid_fact)
    assert sanitized == [{
        "entity": "txn1001",
        "name": "status",
        "value": "approved",
        "verified": True,
    }]

    sensitive_fact = [{
        "entity": "txn1001",
        "name": "status",
        "value": {
            "status": "approved",
            "customer_id": "cli-123",
            "internal_note": "secret",
            "reason": "manual review",
        },
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "lookup_transaction",
    }]
    assert public_verified_facts(sensitive_fact) == []


def test_consolidate_rejects_unauthorized_tool_origin():
    facts = [{
        "entity": "txn1001",
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "remote_tool",
    }]

    unique, conflicts = consolidate_verified_facts(facts)

    assert unique == []
    assert conflicts == []


def test_consolidate_rejects_unauthorized_agent_origin():
    facts = [{
        "entity": "txn1001",
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_agent": "knowledge",
        "source_tool": "retrieval_only",
    }]

    unique, conflicts = consolidate_verified_facts(facts)

    assert unique == []
    assert conflicts == []


def test_make_verified_fact_rejects_empty_entity_name_and_invalid_values():
    with pytest.raises(ValueError):
        make_verified_fact(
            entity="",
            name="status",
            value="approved",
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="",
            value="approved",
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="status",
            value="",
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="amount",
            value=float("nan"),
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="amount",
            value=True,
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="currency",
            value="XYZ",
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )


def test_knowledge_agent_rejects_unauthorized_tool_in_context():
    facts = [{
        "entity": "txn1001",
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "invented_tool",
    }]

    assert KnowledgeAgent._verified_fact_context(facts) == ""


def test_consolidate_rejects_malformed_and_invalid_values():
    facts = [
        {
            "entity": "txn1001",
            "name": "status",
            "value": "",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
        {
            "entity": "txn1001",
            "name": "amount",
            "value": float("inf"),
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
        {
            "entity": "",
            "name": "currency",
            "value": "BRL",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
        {
            "entity": "txn1002",
            "name": "currency",
            "value": "XYZ",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
        {
            "entity": "txn1003",
            "name": "customer_id",
            "value": "cliente1988",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_customer",
        },
    ]

    unique, conflicts = consolidate_verified_facts(facts)
    assert unique == []
    assert conflicts == []


def test_make_verified_fact_rejects_invalid_entity_and_source_types():
    with pytest.raises(ValueError):
        make_verified_fact(
            entity=None,
            name="status",
            value="approved",
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity=123,
            name="status",
            value="approved",
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="status",
            value="approved",
            source_agent=None,
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="status",
            value="approved",
            source_agent="customer_support",
            source_tool=None,
        )


def test_is_valid_verified_fact_rejects_non_string_entity():
    assert not is_valid_verified_fact({
        "entity": None,
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "lookup_transaction",
    })

    assert not is_valid_verified_fact({
        "entity": 123,
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "lookup_transaction",
    })


def test_make_verified_fact_rejects_non_string_source_agent_and_tool():
    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="status",
            value="approved",
            source_agent=object(),
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="status",
            value="approved",
            source_agent="customer_support",
            source_tool=object(),
        )


def test_make_verified_fact_rejects_extremely_large_amount_and_invalid_currency():
    huge_integer = 10 ** 1000
    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="amount",
            value=huge_integer,
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="currency",
            value="XYZ",
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )

    with pytest.raises(ValueError):
        make_verified_fact(
            entity="txn1001",
            name="status",
            value="" * 200,
            source_agent="customer_support",
            source_tool="lookup_transaction",
        )


def test_consolidate_ignores_invalid_facts_and_preserves_only_valid_entries():
    valid = {
        "entity": "txn1001",
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "lookup_transaction",
    }
    invalid_entity = {
        "entity": 42,
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "lookup_transaction",
    }
    invalid_amount = {
        "entity": "txn1002",
        "name": "amount",
        "value": float("nan"),
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "lookup_transaction",
    }

    unique, conflicts = consolidate_verified_facts([valid, invalid_entity, invalid_amount])
    assert len(unique) == 1
    assert unique[0]["entity"] == "txn1001"
    assert conflicts == []


def test_consolidate_preserves_three_conflicting_values_and_type_safety():
    facts = [
        {
            "entity": "txn1001",
            "name": "status",
            "value": "approved",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
        {
            "entity": "txn1001",
            "name": "status",
            "value": "declined",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
        {
            "entity": "txn1001",
            "name": "status",
            "value": "pending",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
    ]

    unique, conflicts = consolidate_verified_facts(facts)

    assert unique == []
    assert len(conflicts) == 1
    assert {entry["value"] for entry in conflicts[0]["values"]} == {
        "approved",
        "declined",
        "pending",
    }

    type_sensitive_facts = [
        {
            "entity": "txn9999",
            "name": "amount",
            "value": 1,
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
        {
            "entity": "txn9999",
            "name": "amount",
            "value": 1.0,
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
        {
            "entity": "txn9999",
            "name": "amount",
            "value": 2,
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
    ]

    unique_type, conflicts_type = consolidate_verified_facts(type_sensitive_facts)

    assert unique_type == []
    assert len(conflicts_type) == 1
    assert len(conflicts_type[0]["values"]) == 3


def test_knowledge_agent_context_omits_personal_fields():
    facts = [
        {
            "entity": "cliente1988",
            "name": "customer_id",
            "value": "cliente1988",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_customer",
        },
        {
            "entity": "cliente1988",
            "name": "name",
            "value": "Maria da Silva",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_customer",
        },
        {
            "entity": "txn1001",
            "name": "status",
            "value": "approved",
            "verified": True,
            "source_agent": "customer_support",
            "source_tool": "lookup_transaction",
        },
    ]

    context = KnowledgeAgent._verified_fact_context(facts)
    assert "customer_id" not in context.lower()
    assert "maria da silva" not in context.lower()
    assert "status" in context.lower()


def test_knowledge_agent_cannot_present_approved_transaction_as_declined():
    approved_facts = [{
        "entity": "txn1001",
        "name": "status",
        "value": "approved",
        "verified": True,
        "source_agent": "customer_support",
        "source_tool": "lookup_transaction",
    }]

    result = KnowledgeAgent().answer(
        "Qual é o status da transação txn1001?",
        verified_facts=approved_facts,
    )
    response = result["response"].lower()

    assert "recusada" not in response
    assert "declined" not in response
    assert "aprovada" in response or "documentos" in response


def test_public_fact_conflicts_filters_invalid_sources_and_values():
    from app.verified_facts import public_fact_conflicts

    valid_conflict = {
        "entity": "txn1001",
        "name": "status",
        "values": [
            {"value": "approved", "verified": True, "source_agent": "customer_support", "source_tool": "lookup_transaction"},
            {"value": "declined", "verified": True, "source_agent": "customer_support", "source_tool": "lookup_transaction"},
        ],
    }
    invalid_origin = {
        "entity": "txn1001",
        "name": "status",
        "values": [
            {"value": "pending", "verified": True, "source_agent": "knowledge", "source_tool": "retrieval_only"},
        ],
    }
    invalid_scalar = {
        "entity": "txn1001",
        "name": "amount",
        "values": [
            {"value": float("nan"), "verified": True, "source_agent": "customer_support", "source_tool": "lookup_transaction"},
        ],
    }
    without_provenance = {
        "entity": "txn1001",
        "name": "currency",
        "values": [
            {"value": "USD", "verified": True},
        ],
    }
    non_scalar = {
        "entity": "txn1001",
        "name": "currency",
        "values": [
            {"value": {"code": "USD"}, "verified": True, "source_agent": "customer_support", "source_tool": "lookup_transaction"},
        ],
    }

    public = public_fact_conflicts([
        valid_conflict,
        invalid_origin,
        invalid_scalar,
        without_provenance,
        non_scalar,
    ])

    assert public == [{
        "entity": "txn1001",
        "name": "status",
        "values": ["approved", "declined"],
    }]


def test_public_fact_conflicts_do_not_duplicate_values_across_multiple_provenances():
    conflict = {
        "entity": "txn1001",
        "name": "status",
        "values": [
            {"value": "approved", "verified": True, "source_agent": "customer_support", "source_tool": "lookup_transaction"},
            {"value": "approved", "verified": True, "source_agent": "customer_support", "source_tool": "lookup_settlement"},
            {"value": "declined", "verified": True, "source_agent": "customer_support", "source_tool": "lookup_transaction"},
        ],
    }

    assert public_verified_facts([]) == []
    public = public_fact_conflicts([conflict])
    assert public == [{
        "entity": "txn1001",
        "name": "status",
        "values": ["approved", "declined"],
    }]


def test_customer_support_account_lookup_does_not_emit_sensitive_verified_facts():
    result = CustomerSupportAgent().answer(
        "Qual o status da minha conta?",
        "cliente1988",
    )

    assert result["verified_facts"] == []
    assert "customer_id" not in str(result["verified_facts"])
    assert "cliente1988" not in str(result["verified_facts"])


def test_two_consecutive_execution_calls_do_not_share_verified_facts():
    orchestrator = ChatOrchestrator()

    first = orchestrator.handle(
        "Qual o status da transação txn1001?",
        "cliente1988",
        request_id="req-1",
    )
    second = orchestrator.handle(
        "Qual o status da transação txn1002?",
        "cliente1988",
        request_id="req-2",
    )

    assert first.result["verified_facts"]
    assert second.result["verified_facts"]
    assert first.result["verified_facts"][0]["entity"] == "txn1001"
    assert second.result["verified_facts"][0]["entity"] == "txn1002"
    assert first.result["verified_facts"][0] not in second.result["verified_facts"]


def test_real_customer_support_to_orchestrator_to_knowledge_flow_preserves_verified_facts():
    orchestrator = ChatOrchestrator()
    with patch.object(KnowledgeAgent, "answer", wraps=KnowledgeAgent().answer) as knowledge_spy:
        execution = orchestrator.handle(
            "Por que a transação txn1001 foi recusada?",
            "cliente1988",
            request_id="req-flow",
        )

    assert execution.result["verified_facts"]
    assert knowledge_spy.call_count == 1
    called_kwargs = knowledge_spy.call_args.kwargs
    assert called_kwargs["verified_facts"]
    assert any(fact["name"] == "status" for fact in called_kwargs["verified_facts"])
    assert all(fact.get("source_agent") == "customer_support" for fact in called_kwargs["verified_facts"])
    assert any(fact["entity"] == "txn1001" for fact in execution.result["verified_facts"])


def test_chat_http_response_exposes_only_public_fields_without_sensitive_data():
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app, headers={"Authorization": "Bearer test-token-cliente1988"})
    response = client.post(
        "/chat",
        json={
            "message": "Qual o status da transação txn1001?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified_facts"]
    assert payload["verified_facts"] == [
        {"entity": "txn1001", "name": "status", "value": "approved", "verified": True},
        {"entity": "txn1001", "name": "amount", "value": 149.9, "verified": True},
        {"entity": "txn1001", "name": "currency", "value": "BRL", "verified": True},
    ]
    assert payload["fact_conflicts"] == []
    assert all("source_agent" not in fact for fact in payload["verified_facts"])
    assert all("source_tool" not in fact for fact in payload["verified_facts"])
    assert all("customer_id" not in fact["name"] for fact in payload["verified_facts"])


def test_conflict_prevents_final_response_from_confirming_an_arbitrary_value():
    orchestrator = ChatOrchestrator()
    result = orchestrator._combine_results([
        {
            "response": "Aprovada",
            "issue_resolved": True,
            "resolved": True,
            "step_status": "success",
            "verified_facts": [{
                "entity": "txn1001",
                "name": "status",
                "value": "approved",
                "verified": True,
                "source_agent": "customer_support",
                "source_tool": "lookup_transaction",
            }],
        },
        {
            "response": "Recusada",
            "issue_resolved": True,
            "resolved": True,
            "step_status": "success",
            "verified_facts": [{
                "entity": "txn1001",
                "name": "status",
                "value": "declined",
                "verified": True,
                "source_agent": "customer_support",
                "source_tool": "lookup_transaction",
            }],
        },
    ])

    assert result["issue_resolved"] is False
    assert result["resolved"] is False
    assert result["step_status"] == "conflict"
    assert "conflito" in result["response"].lower()
    assert "approved" in result["response"].lower() or "declined" in result["response"].lower()
