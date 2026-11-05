import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def _load_script_module(file_name: str, module_name: str):
    module_path = SCRIPTS_DIR / file_name
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_agent_probe_selects_token_by_user_id(monkeypatch):
    module = _load_script_module("agent_probe.py", "agent_probe_mod_token")
    monkeypatch.setenv(
        "GETNET_DEMO_AUTH_TOKENS",
        json.dumps(
            {
                "token-a": "cliente1",
                "token-b": "cliente2",
            }
        ),
    )

    assert module._resolve_token_for_user("cliente2") == "token-b"


def test_agent_probe_sends_bearer_header(monkeypatch, capsys):
    module = _load_script_module("agent_probe.py", "agent_probe_mod_headers")
    monkeypatch.setenv(
        "GETNET_DEMO_AUTH_TOKENS",
        json.dumps({"demo-token": "cliente1988"}),
    )

    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"agent": "knowledge", "response": "ok"}

    class FakeClient:
        def __init__(self, _app, headers=None):
            captured["init_headers"] = headers

        def post(self, _path, json=None):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(module, "TestClient", FakeClient)
    monkeypatch.setattr(sys, "argv", ["agent_probe.py", "olá"])

    module.main()

    assert captured["init_headers"]["Authorization"] == "Bearer demo-token"
    output = capsys.readouterr().out
    assert "demo-token" not in output


@pytest.mark.parametrize(
    ("status_code", "expected_message"),
    [
        (401, "autenticação"),
        (403, "autorização"),
        (500, "HTTP 500"),
    ],
)
def test_agent_probe_handles_http_errors(monkeypatch, status_code, expected_message):
    module = _load_script_module("agent_probe.py", f"agent_probe_mod_http_{status_code}")
    monkeypatch.setenv(
        "GETNET_DEMO_AUTH_TOKENS",
        json.dumps({"demo-token": "cliente1988"}),
    )

    class FakeResponse:
        def __init__(self, code):
            self.status_code = code

        @staticmethod
        def json():
            return {"detail": "erro"}

    class FakeClient:
        def __init__(self, _app, headers=None):
            self.headers = headers

        def post(self, _path, json=None):
            return FakeResponse(status_code)

    monkeypatch.setattr(module, "TestClient", FakeClient)
    monkeypatch.setattr(sys, "argv", ["agent_probe.py", "teste"])

    with pytest.raises(RuntimeError, match=expected_message):
        module.main()


def test_agent_probe_fails_without_token_config(monkeypatch):
    module = _load_script_module("agent_probe.py", "agent_probe_mod_missing_env")
    monkeypatch.delenv("GETNET_DEMO_AUTH_TOKENS", raising=False)

    with pytest.raises(RuntimeError, match="GETNET_DEMO_AUTH_TOKENS"):
        module._load_auth_tokens()


def test_validate_functionality_uses_bearer_and_classifies_401(monkeypatch):
    module = _load_script_module("validate_functionality.py", "validate_mod_401")
    monkeypatch.setenv(
        "GETNET_DEMO_AUTH_TOKENS",
        json.dumps({"demo-token": "cliente1988"}),
    )

    seen_headers = []

    class FakeResponse:
        status_code = 401

        @staticmethod
        def json():
            return {"detail": "Credenciais ausentes ou inválidas."}

    class FakeClient:
        def __init__(self, _app):
            pass

        def post(self, _path, json=None, headers=None):
            seen_headers.append(headers)
            return FakeResponse()

    monkeypatch.setattr(module, "TestClient", FakeClient)

    results = module.run_validation()

    assert results
    assert all(item["http_status"] == 401 for item in results)
    assert all(item["auth_error"] is True for item in results)
    assert all(item["http_error"] is False for item in results)
    assert all(item["actual_agent"] is None for item in results)
    assert all(headers["Authorization"] == "Bearer demo-token" for headers in seen_headers)


def test_validate_functionality_classifies_403_and_500(monkeypatch):
    module = _load_script_module("validate_functionality.py", "validate_mod_http_multi")
    monkeypatch.setenv(
        "GETNET_DEMO_AUTH_TOKENS",
        json.dumps({"demo-token": "cliente1988"}),
    )

    class FakeResponse:
        def __init__(self, code):
            self.status_code = code

        @staticmethod
        def json():
            return {"detail": "erro"}

    class FakeClient:
        def __init__(self, _app):
            self.calls = 0

        def post(self, _path, json=None, headers=None):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse(403)
            return FakeResponse(500)

    monkeypatch.setattr(module, "TestClient", FakeClient)

    results = module.run_validation()

    assert results[0]["http_status"] == 403
    assert results[0]["auth_error"] is True
    assert results[0]["http_error"] is False

    assert any(item["http_status"] == 500 for item in results[1:])
    assert all(item["actual_agent"] is None for item in results)


def test_validate_functionality_classifies_3xx_as_http_error(monkeypatch):
    module = _load_script_module("validate_functionality.py", "validate_mod_http_3xx")
    monkeypatch.setenv(
        "GETNET_DEMO_AUTH_TOKENS",
        json.dumps({"demo-token": "cliente1988"}),
    )

    class FakeResponse:
        status_code = 302

        @staticmethod
        def json():
            return {"agent": "knowledge", "response": "should-not-be-used"}

    class FakeClient:
        def __init__(self, _app):
            pass

        def post(self, _path, json=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr(module, "TestClient", FakeClient)

    results = module.run_validation()

    assert results
    assert all(item["http_status"] == 302 for item in results)
    assert all(item["auth_error"] is False for item in results)
    assert all(item["http_error"] is True for item in results)
    assert all(item["actual_agent"] is None for item in results)
    assert all(item["response"] is None for item in results)


def test_validate_functionality_does_not_persist_token_in_results(monkeypatch):
    module = _load_script_module("validate_functionality.py", "validate_mod_no_leak")
    secret_token = "super-secret-token"
    monkeypatch.setenv(
        "GETNET_DEMO_AUTH_TOKENS",
        json.dumps({secret_token: "cliente1988"}),
    )

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "agent": "knowledge",
                "tool_used": "ollama",
                "handoff_required": False,
                "response": "ok",
            }

    class FakeClient:
        def __init__(self, _app):
            pass

        def post(self, _path, json=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr(module, "TestClient", FakeClient)

    results = module.run_validation()
    serialized = json.dumps(results, ensure_ascii=False)
    assert secret_token not in serialized


def test_validate_functionality_fails_without_token_config(monkeypatch):
    module = _load_script_module("validate_functionality.py", "validate_mod_missing_env")
    monkeypatch.delenv("GETNET_DEMO_AUTH_TOKENS", raising=False)

    with pytest.raises(RuntimeError, match="GETNET_DEMO_AUTH_TOKENS"):
        module.run_validation()


def test_check_scenarios_chat_sends_bearer_header(monkeypatch):
    module = _load_script_module("check_scenarios.py", "check_scenarios_mod_headers")
    monkeypatch.setenv(
        "GETNET_DEMO_AUTH_TOKENS",
        json.dumps({"demo-token": "cliente1988"}),
    )

    captured = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout=120):
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.json, "load", lambda _resp: {"response": "ok", "agent": "knowledge"})

    _ = module.chat("teste", user_id="cliente1988")

    assert captured["authorization"] == "Bearer demo-token"


@pytest.mark.parametrize(
    ("status_code", "expected_text"),
    [
        (401, "ERRO HTTP 401"),
        (403, "ERRO HTTP 403"),
        (500, "ERRO HTTP 500"),
    ],
)
def test_check_scenarios_reports_http_diagnostics(monkeypatch, capsys, status_code, expected_text):
    module = _load_script_module("check_scenarios.py", f"check_scenarios_mod_http_{status_code}")

    def failing_chat(_message, user_id="cliente1988"):
        raise urllib.error.HTTPError(
            url="http://localhost:8000/chat",
            code=status_code,
            msg="error",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(module, "chat", failing_chat)

    module.main()

    output = capsys.readouterr().out
    assert expected_text in output


def test_check_scenarios_fails_without_token_config(monkeypatch):
    module = _load_script_module("check_scenarios.py", "check_scenarios_mod_missing_env")
    monkeypatch.delenv("GETNET_DEMO_AUTH_TOKENS", raising=False)

    with pytest.raises(RuntimeError, match="GETNET_DEMO_AUTH_TOKENS"):
        module._load_auth_tokens()


def test_check_scenarios_main_fails_fast_without_token_config(monkeypatch, capsys):
    module = _load_script_module("check_scenarios.py", "check_scenarios_mod_main_missing_env")
    monkeypatch.delenv("GETNET_DEMO_AUTH_TOKENS", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code != 0
    err_output = capsys.readouterr().err
    assert "ERRO DE CONFIGURAÇÃO" in err_output
    assert "GETNET_DEMO_AUTH_TOKENS" in err_output
