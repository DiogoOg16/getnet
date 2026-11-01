import importlib.util
from pathlib import Path

import pytest
import requests

from app.llm.ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaHTTPError,
    OllamaRequestError,
    OllamaResponseFormatError,
    OllamaTimeoutError,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, reason="OK", json_error=False):
        self.payload = payload
        self.status_code = status_code
        self.reason = reason
        self._json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self.payload


def test_client_sends_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse({"message": {"content": "ok"}})

    monkeypatch.setattr(requests, "post", fake_post)

    client = OllamaClient(base_url="http://localhost:11434", model="qwen2.5:7b", timeout=12)
    result = client.chat([
        {"role": "user", "content": "Olá"},
    ])

    assert result["message"]["content"] == "ok"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["model"] == "qwen2.5:7b"
    assert captured["json"]["stream"] is False
    assert captured["json"]["messages"] == [{"role": "user", "content": "Olá"}]
    assert "tools" not in captured["json"]
    assert captured["timeout"] == 12


def test_client_uses_environment_configuration(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11435")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")

    client = OllamaClient()

    assert client.base_url == "http://localhost:11435"
    assert client.model == "llama3.1"


def test_client_returns_valid_response(monkeypatch):
    def fake_post(url, json, timeout):
        return FakeResponse({"message": {"content": "Resposta válida"}})

    monkeypatch.setattr(requests, "post", fake_post)

    client = OllamaClient()
    result = client.chat([{"role": "user", "content": "Teste"}])

    assert result == {"message": {"content": "Resposta válida"}}


def test_client_raises_timeout(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(OllamaTimeoutError, match="timed out"):
        OllamaClient(timeout=7).chat([{"role": "user", "content": "Test"}])


def test_client_raises_connection_error(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(OllamaConnectionError, match="Could not connect"):
        OllamaClient().chat([{"role": "user", "content": "Test"}])


def test_client_raises_generic_request_error(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.exceptions.SSLError("ssl failure")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(OllamaRequestError, match="transport request failed"):
        OllamaClient().chat([{"role": "user", "content": "Test"}])


def test_client_raises_http_error(monkeypatch):
    def fake_post(url, json, timeout):
        return FakeResponse(status_code=500, reason="Server Error")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(OllamaHTTPError, match="Ollama HTTP error"):
        OllamaClient().chat([{"role": "user", "content": "Test"}])


def test_client_raises_for_invalid_json(monkeypatch):
    def fake_post(url, json, timeout):
        return FakeResponse(json_error=True)

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(OllamaResponseFormatError, match="invalid JSON"):
        OllamaClient().chat([{"role": "user", "content": "Test"}])


def test_client_message_missing_is_rejected(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: FakeResponse({}))

    with pytest.raises(OllamaResponseFormatError, match="missing 'message'"):
        OllamaClient.parse_message_content({})


def test_client_message_invalid_type_is_rejected(monkeypatch):
    with pytest.raises(OllamaResponseFormatError, match="message.*dictionary"):
        OllamaClient.parse_message_content({"message": "not a dict"})


def test_client_missing_content_is_rejected():
    with pytest.raises(OllamaResponseFormatError, match="message.content"):
        OllamaClient.parse_message_content({"message": {}})


def test_client_invalid_content_type_is_rejected():
    with pytest.raises(OllamaResponseFormatError, match="must be a string"):
        OllamaClient.parse_message_content({"message": {"content": 123}})


def test_client_accepts_optional_tools(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResponse({"message": {"content": "with tools"}})

    monkeypatch.setattr(requests, "post", fake_post)

    tools = [{"type": "function", "function": {"name": "lookup_customer", "parameters": {"type": "object"}}}]
    client = OllamaClient(base_url="http://localhost:11434", model="qwen2.5:7b")
    result = client.chat([{"role": "user", "content": "Quem sou eu?"}], tools=tools)

    assert result["message"]["content"] == "with tools"
    assert captured["json"]["tools"] == tools


def test_knowledge_agent_preserves_behavior_with_client_parsing(monkeypatch):
    module_path = Path(__file__).resolve().parents[1] / "app" / "agents" / "knowledge.py"
    spec = importlib.util.spec_from_file_location("real_knowledge_test_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)

    class DummyClient:
        def __init__(self):
            self.parse_calls = 0
            self.last_messages = None

        def chat(self, messages, tools=None):
            self.last_messages = messages
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert "Como funciona a antecipação de recebíveis?" in messages[1]["content"]
            assert "Documento:" in messages[1]["content"]
            assert tools is None
            return {"message": {"content": "Resposta de teste"}}

        def parse_message_content(self, response):
            self.parse_calls += 1
            assert response["message"]["content"] == "Resposta de teste"
            return response["message"]["content"].strip()

    monkeypatch.setattr(
        module,
        "retrieve",
        lambda message: [{
            "title": "Antecipação de recebíveis",
            "content": "Para antecipar recebíveis, a empresa pode receber adiantado o valor de vendas futuras.",
            "section": "Geral",
        }],
    )

    agent = module.KnowledgeAgent()
    agent.client = DummyClient()

    result = agent.answer("Como funciona a antecipação de recebíveis?", None)

    assert result["agent"] == "knowledge"
    assert result["response"] == "Resposta de teste"
    assert result["tool_used"] == "ollama"
    assert agent.client.parse_calls == 1
    assert agent.client.last_messages[0]["role"] == "system"
    assert agent.client.last_messages[1]["role"] == "user"
