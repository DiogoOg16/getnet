"""Latência por chamada (LLM, ferramenta, recuperação, serviço externo) no trace."""

import logging

import pytest
import requests
from fastapi.testclient import TestClient

from app.agents.knowledge import KnowledgeAgent
from app.main import app
from app.observability import collect_calls, record_call
from app.orchestrator import ChatOrchestrator

REAL_GENERATE = KnowledgeAgent._generate


class FakeOllamaResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.reason = "OK"

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def kinds(calls):
    return [(call["kind"], call["name"], call["status"]) for call in calls]


# --- coletor ------------------------------------------------------------------

def test_record_call_measures_and_marks_errors():
    with collect_calls() as calls:
        with record_call("tool", "ok_tool"):
            pass
        with pytest.raises(ValueError):
            with record_call("llm", "failing_model"):
                raise ValueError("falhou")

    assert kinds(calls) == [("tool", "ok_tool", "ok"), ("llm", "failing_model", "error")]
    assert all(isinstance(call["duration_ms"], int) and call["duration_ms"] >= 0 for call in calls)


def test_record_call_without_collector_is_a_no_op():
    with record_call("tool", "ignored"):
        value = 42
    assert value == 42


def test_collectors_do_not_leak_between_steps():
    with collect_calls() as first:
        with record_call("tool", "a"):
            pass
    with collect_calls() as second:
        with record_call("tool", "b"):
            pass
    assert kinds(first) == [("tool", "a", "ok")] and kinds(second) == [("tool", "b", "ok")]


# --- fluxos reais ---------------------------------------------------------------

def test_knowledge_step_records_retrieval_and_llm_calls(monkeypatch):
    monkeypatch.setattr(KnowledgeAgent, "_generate", REAL_GENERATE)
    monkeypatch.setattr(
        requests, "post",
        lambda *args, **kwargs: FakeOllamaResponse({"message": {"role": "assistant", "content": "Resposta."}}),
    )

    execution = ChatOrchestrator().handle("Qual a diferença entre a Get Clássica e a Get Smart?", "cliente1988")

    assert execution.trace[0].agent == "knowledge"
    assert kinds(execution.trace[0].calls) == [("retrieval", "bm25", "ok"), ("llm", "qwen2.5:7b", "ok")]


def test_llm_failure_is_recorded_as_an_error_call(monkeypatch):
    monkeypatch.setattr(KnowledgeAgent, "_generate", REAL_GENERATE)

    def unreachable(*args, **kwargs):
        raise requests.ConnectionError("sem Ollama")

    monkeypatch.setattr(requests, "post", unreachable)

    execution = ChatOrchestrator().handle("Qual a diferença entre a Get Clássica e a Get Smart?", "cliente1988")

    assert execution.result["tool_used"] == "retrieval_only"
    assert kinds(execution.trace[0].calls) == [("retrieval", "bm25", "ok"), ("llm", "qwen2.5:7b", "error")]


def test_s08_quote_step_makes_no_llm_call():
    execution = ChatOrchestrator().handle("The transaction is txn1003.", "cliente1988")

    support, knowledge = execution.trace
    assert ("tool", "lookup_transaction", "ok") in kinds(support.calls)
    # A etapa de citação só recupera documentos: nenhuma chamada ao LLM.
    assert kinds(knowledge.calls) == [("retrieval", "bm25", "ok")]


def test_external_service_calls_are_recorded(monkeypatch):
    class Geo:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"name": "Porto Alegre", "admin1": "RS", "country": "Brasil",
                                 "latitude": -30.0, "longitude": -51.2, "timezone": "America/Sao_Paulo"}]}

    class Forecast(Geo):
        def json(self):
            return {"daily": {"time": ["2026-11-15", "2026-11-16"], "temperature_2m_max": [30, 31],
                              "temperature_2m_min": [20, 21], "precipitation_probability_max": [10, 40]}}

    responses = iter([Geo(), Forecast()])
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: next(responses))

    execution = ChatOrchestrator().handle("What's the weather forecast in Porto Alegre tomorrow?", "cliente1988")

    assert kinds(execution.trace[0].calls) == [
        ("external", "open_meteo_geocoding", "ok"),
        ("external", "open_meteo_forecast", "ok"),
    ]


def test_api_trace_and_log_expose_the_calls(caplog):
    caplog.set_level(logging.INFO, logger="getnet_orchestrator")
    client = TestClient(app, headers={"Authorization": "Bearer test-token-cliente1988"})

    payload = client.post(
        "/chat", json={"message": "Qual o status da transação txn1001?", "user_id": "cliente1988", "session_id": "obs"}
    ).json()

    calls = payload["trace"][0]["calls"]
    assert {"kind", "name", "duration_ms", "status"} <= set(calls[0])
    assert ("tool", "lookup_transaction", "ok") in kinds(calls)
    assert any("calls=" in record.getMessage() and "tool:lookup_transaction:" in record.getMessage()
               for record in caplog.records)
