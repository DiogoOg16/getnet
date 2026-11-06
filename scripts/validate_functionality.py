#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app
from scripts.env_bootstrap import load_local_env

SCENARIOS = [
    {
        "name": "knowledge_pix",
        "message": "Como funciona o Pix?",
        "user_id": "cliente1988",
        "expect_agent": "knowledge",
    },
    {
        "name": "knowledge_error_adq",
        "message": "Qual é o significado do erro ADQ 4-83 na maquininha?",
        "user_id": "cliente1988",
        "expect_agent": "knowledge",
    },
    {
        "name": "web_search_weather",
        "message": "Qual é a previsão do tempo em Porto Alegre amanhã?",
        "user_id": "cliente1988",
        "expect_agent": "web_search",
    },
    {
        "name": "customer_support_transaction",
        "message": "Minha transação txn1001 foi recusada e eu quero saber o status.",
        "user_id": "cliente1988",
        "expect_agent": "customer_support",
    },
    {
        "name": "human_escalation",
        "message": "Preciso falar com um humano sobre dados sensíveis do meu cadastro.",
        "user_id": "cliente1988",
        "expect_agent": "human_escalation",
    },
]


def _load_auth_tokens() -> dict[str, str]:
    raw_tokens = os.getenv("GETNET_DEMO_AUTH_TOKENS", "")
    if not raw_tokens:
        raise RuntimeError("GETNET_DEMO_AUTH_TOKENS não está definido.")

    try:
        token_map = json.loads(raw_tokens)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GETNET_DEMO_AUTH_TOKENS deve conter um JSON válido.") from exc

    if not isinstance(token_map, dict):
        raise RuntimeError("GETNET_DEMO_AUTH_TOKENS deve mapear tokens para user_id.")

    cleaned: dict[str, str] = {}
    for token, user_id in token_map.items():
        if isinstance(token, str) and token and isinstance(user_id, str) and user_id:
            cleaned[token] = user_id

    if not cleaned:
        raise RuntimeError("GETNET_DEMO_AUTH_TOKENS não possui pares token/user_id válidos.")

    return cleaned


def _resolve_token_for_user(user_id: str) -> str:
    for token, mapped_user_id in _load_auth_tokens().items():
        if mapped_user_id == user_id:
            return token
    raise RuntimeError(f"Nenhum token configurado para user_id '{user_id}'.")


def _build_auth_headers(user_id: str) -> dict[str, str]:
    token = _resolve_token_for_user(user_id)
    return {"Authorization": f"Bearer {token}"}


def run_validation() -> list[dict]:
    client = TestClient(app)
    results = []
    run_id = uuid.uuid4().hex[:8]

    for scenario in SCENARIOS:
        headers = _build_auth_headers(scenario["user_id"])
        # Sessão exclusiva por padrão. Cenários com vários turnos podem
        # compartilhar sessão declarando o mesmo "session_id" explicitamente.
        session_id = scenario.get("session_id") or f"validation-{run_id}-{scenario['name']}"
        response = client.post(
            "/chat",
            json={
                "message": scenario["message"],
                "user_id": scenario["user_id"],
                "session_id": session_id,
            },
            headers=headers,
        )

        is_success = 200 <= response.status_code < 300
        body = response.json() if is_success else {}
        auth_error = response.status_code in (401, 403)
        http_error = not is_success and not auth_error
        record = {
            "name": scenario["name"],
            "input": {
                "message": scenario["message"],
                "user_id": scenario["user_id"],
                "session_id": session_id,
            },
            "http_status": response.status_code,
            "auth_error": auth_error,
            "http_error": http_error,
            "expected_agent": scenario["expect_agent"],
            "actual_agent": body.get("agent"),
            "tool_used": body.get("tool_used"),
            "handoff_required": body.get("handoff_required"),
            "response": body.get("response"),
        }
        results.append(record)

    return results


def main() -> None:
    load_local_env()
    results = run_validation()
    output_dir = ROOT / "logs"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"validation_{timestamp}.json"
    output_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n[LOG] Resultados salvos em: {output_file}")


def run_cli() -> int:
    try:
        main()
    except RuntimeError as error:
        print(f"ERRO DE CONFIGURACAO: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
