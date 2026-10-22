"""Roda os 10 cenários do desafio contra a API em execução e resume o resultado.

Uso:  python check_scenarios.py [URL]     (padrão: http://localhost:8000)
"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

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


def chat(message, user_id="cliente1988"):
    request = urllib.request.Request(
        f"{BASE}/chat",
        data=json.dumps({"message": message, "user_id": user_id}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


for number, message in enumerate(SCENARIOS, start=1):
    print("=" * 72)
    print(f"[{number}] {message}")
    try:
        data = chat(message)
    except Exception as error:  # noqa: BLE001
        print("   ERRO:", error)
        continue
    text = " ".join(data["response"].split())
    print(f"   agent={data['agent']} | tool={data.get('tool_used')} | "
          f"handoff={data.get('handoff_required')}")
    print(f"   fontes={len(data.get('sources', []))}")
    print(f"   resposta: {text[:220]}{'…' if len(text) > 220 else ''}")
