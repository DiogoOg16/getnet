"""REL-02 (exceções registradas com stack trace, sem dados pessoais) e
REL-01 (timeout do Ollama configurável)."""

import logging

import pytest
import requests

from app.agents.knowledge import KnowledgeAgent
from app.agents.web_search import WebSearchAgent
from app.llm.ollama_client import DEFAULT_TIMEOUT_SECONDS, OllamaClient, OllamaTimeoutError
from app.logging_utils import log_exception
from app.orchestrator import ChatOrchestrator

RAW_CPF = "123.456.789-09"
RAW_EMAIL = "joao.silva@empresa.com.br"


# --- REL-02 -----------------------------------------------------------------

def test_log_exception_keeps_type_and_traceback_and_masks_personal_data(caplog):
    logger = logging.getLogger("test_reliability")
    caplog.set_level(logging.ERROR, logger="test_reliability")

    try:
        raise ValueError(f"falha ao processar {RAW_CPF} de {RAW_EMAIL}")
    except ValueError as exc:
        log_exception(logger, "evento_teste", exc, request_id="req-1")

    record = caplog.records[-1]
    text = record.getMessage()
    assert record.levelno == logging.ERROR
    assert text.startswith("evento_teste request_id=req-1 error_type=ValueError")
    assert "Traceback (most recent call last)" in text
    assert "test_log_exception_keeps_type_and_traceback" in text
    assert "[CPF]" in text and "[EMAIL]" in text
    assert RAW_CPF not in text and RAW_EMAIL not in text


def test_agent_exception_is_logged_with_traceback_without_leaking(monkeypatch, caplog):
    orchestrator = ChatOrchestrator()
    caplog.set_level(logging.INFO, logger="getnet_orchestrator")

    def failing_support(*, message, user_id):
        raise RuntimeError(f"erro interno com {RAW_CPF}")

    monkeypatch.setattr(orchestrator.support, "answer", failing_support)

    execution = orchestrator.handle("Qual o status da transação txn1001?", "cliente1988", request_id="req-2")

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    logged = errors[0].getMessage()
    assert "orchestrator_step_error request_id=req-2 agent=customer_support error_type=RuntimeError" in logged
    assert "Traceback" in logged and "failing_support" in logged
    assert RAW_CPF not in logged and "[CPF]" in logged
    # A resposta ao usuário continua genérica.
    assert execution.result["step_status"] == "failed"
    assert "erro interno" not in execution.result["response"]


def test_knowledge_fallback_is_logged(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="getnet_knowledge")

    def timing_out(self, message, context):
        raise OllamaTimeoutError("Ollama request timed out after 60 seconds.")

    monkeypatch.setattr(KnowledgeAgent, "_generate", timing_out)

    result = KnowledgeAgent().answer("Qual a diferença entre a Get Clássica e a Get Smart?")

    assert result["tool_used"] == "retrieval_only"
    logged = [r.getMessage() for r in caplog.records if r.name == "getnet_knowledge"]
    assert any(
        "knowledge_generation_fallback" in m and "error_type=OllamaTimeoutError" in m for m in logged
    )


def test_web_search_unavailable_is_logged(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="getnet_web_search")

    def failing_post(*args, **kwargs):
        raise requests.ConnectionError("rede indisponível")

    monkeypatch.setattr(requests, "post", failing_post)

    result = WebSearchAgent().answer("notícias sobre maquininhas")

    assert result["step_status"] == "failed"
    assert any(
        "web_search_unavailable" in r.getMessage() and "error_type=ConnectionError" in r.getMessage()
        for r in caplog.records
    )


# --- REL-01 -----------------------------------------------------------------

def test_ollama_timeout_defaults_to_60_seconds(monkeypatch):
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)

    assert OllamaClient().timeout == DEFAULT_TIMEOUT_SECONDS == 60.0


@pytest.mark.parametrize(("raw", "expected"), [("12", 12.0), ("12.5", 12.5), (" 90 ", 90.0)])
def test_ollama_timeout_comes_from_environment(monkeypatch, raw, expected):
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", raw)

    assert OllamaClient().timeout == expected


@pytest.mark.parametrize("raw", ["abc", "0", "-3", "nan", "inf", ""])
def test_invalid_ollama_timeout_falls_back_to_default(monkeypatch, caplog, raw):
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", raw)
    caplog.set_level(logging.WARNING, logger="getnet_ollama")

    assert OllamaClient().timeout == DEFAULT_TIMEOUT_SECONDS
    if raw:
        assert any("ollama_timeout_invalid" in r.getMessage() for r in caplog.records)


def test_explicit_timeout_argument_wins_over_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "90")

    assert OllamaClient(timeout=7).timeout == 7


def test_timeout_is_sent_to_the_http_call(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "15")
    seen = {}

    def fake_post(url, json, timeout):
        seen["timeout"] = timeout
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(OllamaTimeoutError, match="15.0 seconds"):
        OllamaClient().chat([{"role": "user", "content": "Oi"}])
    assert seen["timeout"] == 15.0


@pytest.mark.parametrize(
    ("module_path", "call", "logger_name", "event"),
    [
        ("app.tools.weather", lambda m: m.get_forecast("Porto Alegre"), "getnet_weather", "weather_unavailable"),
        ("app.tools.exchange_rate", lambda m: m.get_exchange_rate("EUR"), "getnet_exchange_rate", "exchange_rate_unavailable"),
    ],
)
def test_external_tool_unavailability_is_logged(monkeypatch, caplog, module_path, call, logger_name, event):
    import importlib

    module = importlib.import_module(module_path)
    caplog.set_level(logging.WARNING, logger=logger_name)

    def failing_get(*args, **kwargs):
        raise requests.ConnectionError("rede indisponível")

    monkeypatch.setattr(requests, "get", failing_get)

    result = call(module)

    assert result == {"found": False, "error": "unavailable"}
    assert any(event in r.getMessage() and "error_type=ConnectionError" in r.getMessage() for r in caplog.records)
