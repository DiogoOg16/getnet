#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app


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
    args = build_parser().parse_args()
    message = " ".join(args.message)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={"message": message, "user_id": args.user_id},
    )

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


if __name__ == "__main__":
    main()
