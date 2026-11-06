#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app
from scripts.env_bootstrap import load_local_env


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Consulta o agente local e imprime a resposta exata em JSON. "
            "Opcionalmente salva o resultado em um arquivo .txt."
        )
    )
    parser.add_argument(
        "message",
        nargs="+",
        help="Mensagem do usuário para enviar ao agente.",
    )
    parser.add_argument(
        "--user-id",
        default="cliente1988",
        help="Identificador do cliente para a API.",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Salva a resposta em um arquivo .txt no diretório logs/.",
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="Diretório onde o arquivo de log será salvo.",
    )
    return parser


def main() -> None:
    load_local_env()
    args = build_parser().parse_args()
    message = " ".join(args.message)

    headers = _build_auth_headers(args.user_id)
    client = TestClient(app, headers=headers)
    response = client.post(
        "/chat",
        json={"message": message, "user_id": args.user_id},
    )

    if response.status_code == 401:
        raise RuntimeError("Falha de autenticação (401) ao chamar /chat.")
    if response.status_code == 403:
        raise RuntimeError("Falha de autorização (403) ao chamar /chat.")
    if response.status_code >= 400:
        raise RuntimeError(f"Falha HTTP {response.status_code} ao chamar /chat.")

    payload = response.json()
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.log:
        log_dir = Path(args.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = log_dir / f"agent_probe_{timestamp}.txt"
        file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[LOG] Resposta salva em: {file_path}")


def run_cli() -> int:
    try:
        main()
    except RuntimeError as error:
        print(f"ERRO DE CONFIGURACAO: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
