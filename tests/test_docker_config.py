"""O docker-compose.yml repassa ao container todas as variáveis que a aplicação lê.

O Compose só entrega ao processo as variáveis listadas em `environment`. Uma
variável lida com `os.getenv` e ausente dessa lista é ignorada em Docker sem
nenhum aviso (foi o caso de OLLAMA_TIMEOUT_SECONDS, REL-01).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def variables_read_by_the_app() -> set[str]:
    names = set()
    for path in (ROOT / "app").rglob("*.py"):
        names.update(re.findall(r"os\.getenv\(\s*\"([A-Z][A-Z0-9_]*)\"", path.read_text(encoding="utf-8")))
    return names


def api_environment() -> dict[str, str]:
    api = COMPOSE[COMPOSE.index("\n  api:"):COMPOSE.index("\n  ollama:")]
    block = api[api.index("environment:"):api.index("volumes:")]
    return dict(re.findall(r"^\s*-\s*([A-Z][A-Z0-9_]*)=(.*)$", block, flags=re.M))


def test_every_variable_read_by_the_app_is_passed_to_the_api_container():
    read = variables_read_by_the_app()

    assert {"OLLAMA_URL", "OLLAMA_MODEL", "OLLAMA_TIMEOUT_SECONDS", "GETNET_DEMO_AUTH_TOKENS"} <= read
    assert read - set(api_environment()) == set()


def test_ollama_timeout_is_configurable_with_default_60():
    assert api_environment()["OLLAMA_TIMEOUT_SECONDS"] == "${OLLAMA_TIMEOUT_SECONDS:-60}"
