"""Roda os 10 cenários do desafio contra a API em execução e resume o resultado.

Uso:  python check_scenarios.py [URL]     (padrão: http://localhost:8000)
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.env_bootstrap import load_local_env

BASE = (
    sys.argv[1]
    if len(sys.argv) > 1 and sys.argv[1].startswith(("http://", "https://"))
    else "http://localhost:8000"
)

SCENARIOS = [
    "What's the difference between the Get Clássica and the Get Smart?",
    "What's the weather forecast in Porto Alegre tomorrow?",
    "When will the money from yesterday's sales be deposited?",
    "Do I need a bank account to receive my sales via Pix?",
    "My card machine won't connect to the internet, what should I do?",
    "How does receivables advance (antecipação) work with Getnet?",
    "What's the euro exchange rate today?",
    "My card machine is showing a transaction decline error.",
    "How many installments can I split a sale into with the crediário?",
    "Can I sell through WhatsApp using the Payment Link?",
]


def chat(message, user_id="cliente1988", session_id=None):
    token = _resolve_token_for_user(user_id)
    payload = {"message": message, "user_id": user_id}
    if session_id:
        payload["session_id"] = session_id
    request = urllib.request.Request(
        f"{BASE}/chat",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


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
    for token, mapped_user_id in token_map.items():
        if isinstance(token, str) and token and isinstance(mapped_user_id, str) and mapped_user_id:
            cleaned[token] = mapped_user_id

    if not cleaned:
        raise RuntimeError("GETNET_DEMO_AUTH_TOKENS não possui pares token/user_id válidos.")

    return cleaned


def _resolve_token_for_user(user_id: str) -> str:
    for token, mapped_user_id in _load_auth_tokens().items():
        if mapped_user_id == user_id:
            return token
    raise RuntimeError(f"Nenhum token configurado para user_id '{user_id}'.")


def main() -> None:
    load_local_env()
    try:
        _load_auth_tokens()
    except RuntimeError as error:
        print(f"ERRO DE CONFIGURAÇÃO: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    run_id = uuid.uuid4().hex[:8]
    for number, message in enumerate(SCENARIOS, start=1):
        # Sessão exclusiva: nenhum histórico ou ticket herdado de outro cenário.
        session_id = f"scenario-{run_id}-{number:02d}"
        print("=" * 72)
        print(f"[{number}] {message}")
        print(f"   session_id={session_id}")
        try:
            data = chat(message, session_id=session_id)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                print("   ERRO HTTP 401: autenticação inválida ou ausente.")
            elif error.code == 403:
                print("   ERRO HTTP 403: usuário sem permissão para a operação.")
            else:
                print(f"   ERRO HTTP {error.code}: falha ao chamar /chat.")
            continue
        except Exception as error:  # noqa: BLE001
            print("   ERRO:", error)
            continue
        text = " ".join(data["response"].split())
        print(f"   agent={data['agent']} | tool={data.get('tool_used')} | "
              f"handoff={data.get('handoff_required')}")
        print(f"   fontes={len(data.get('sources', []))}")
        print(f"   resposta: {text[:220]}{'…' if len(text) > 220 else ''}")


def run_cli() -> int:
    try:
        main()
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
