"""Fluxo do atendente com as credenciais de desenvolvimento do `.env.example`.

Os testes usam os tokens fictícios do `.env.example`, os mesmos citados no
README, para garantir que um avaliador consiga reproduzir o fluxo documentado.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.human_handoff import is_attendant_user
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")

CUSTOMER_TOKEN = "demo-token-cliente1988"
OTHER_CUSTOMER_TOKEN = "demo-token-cliente2001"
ATTENDANT_TOKEN = "demo-token-atendente_01"


def example_tokens() -> dict[str, str]:
    match = re.search(r"^GETNET_DEMO_AUTH_TOKENS=(.+)$", ENV_EXAMPLE, re.MULTILINE)
    assert match, "GETNET_DEMO_AUTH_TOKENS ausente do .env.example"
    return json.loads(match.group(1).strip().strip("'\""))


@pytest.fixture
def example_auth(monkeypatch):
    monkeypatch.setenv("GETNET_DEMO_AUTH_TOKENS", json.dumps(example_tokens()))


def as_user(token: str) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def open_ticket(session_id: str) -> str:
    response = as_user(CUSTOMER_TOKEN).post(
        "/chat",
        json={
            "message": "Preciso falar com um humano sobre dados sensíveis do meu cadastro.",
            "user_id": "cliente1988",
            "session_id": session_id,
        },
    )
    assert response.status_code == 200
    handoff = response.json()["handoff"]
    assert handoff["status"] == "pending"
    return handoff["id"]


def test_env_example_declares_a_development_only_attendant():
    tokens = example_tokens()

    assert tokens[ATTENDANT_TOKEN] == "atendente_01"
    assert is_attendant_user(tokens[ATTENDANT_TOKEN])
    assert [user for user in tokens.values() if is_attendant_user(user)] == ["atendente_01"]
    assert tokens[CUSTOMER_TOKEN] == "cliente1988"
    assert tokens[OTHER_CUSTOMER_TOKEN] == "cliente2001"
    assert "Development only" in ENV_EXAMPLE


def test_readme_only_uses_tokens_declared_in_env_example():
    documented = set(re.findall(r"Bearer (demo-token-[\w-]+)", README))

    assert ATTENDANT_TOKEN in documented
    assert documented <= set(example_tokens())


def test_attendant_token_authenticates_and_lists_all_tickets(example_auth):
    ticket_id = open_ticket("session-attendant-list")

    response = as_user(ATTENDANT_TOKEN).get("/human-handoff")

    assert response.status_code == 200
    assert ticket_id in {record["id"] for record in response.json()}


def test_documented_attendant_flow(example_auth):
    attendant = as_user(ATTENDANT_TOKEN)
    ticket_id = open_ticket("session-attendant-flow")

    pending = attendant.get(f"/human-handoff/{ticket_id}")
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"
    assert pending.json()["assignee"] is None

    assumed = attendant.post(
        f"/human-handoff/{ticket_id}/assume", json={"assignee": "atendente_01"}
    )
    assert assumed.status_code == 200

    assigned = attendant.get(f"/human-handoff/{ticket_id}")
    assert assigned.json()["status"] == "assigned"
    assert assigned.json()["assignee"] == "atendente_01"

    completed = attendant.post(
        f"/human-handoff/{ticket_id}/complete",
        json={"resolution": "Cadastro revisado com o cliente."},
    )
    assert completed.status_code == 200

    final = attendant.get(f"/human-handoff/{ticket_id}")
    assert final.json()["status"] == "completed"
    assert final.json()["resolution"] == "Cadastro revisado com o cliente."

    owner_view = as_user(CUSTOMER_TOKEN).get(f"/human-handoff/{ticket_id}")
    assert owner_view.status_code == 200
    assert owner_view.json()["status"] == "completed"


def test_customer_cannot_assume_or_complete_even_their_own_ticket(example_auth):
    customer = as_user(CUSTOMER_TOKEN)
    ticket_id = open_ticket("session-customer-admin")

    assert customer.post(
        f"/human-handoff/{ticket_id}/assume", json={"assignee": "cliente1988"}
    ).status_code == 403
    assert customer.post(
        f"/human-handoff/{ticket_id}/complete", json={"resolution": "Resolvido"}
    ).status_code == 403
    assert customer.get(f"/human-handoff/{ticket_id}").json()["status"] == "pending"


def test_other_customer_cannot_operate_or_read_the_ticket(example_auth):
    other = as_user(OTHER_CUSTOMER_TOKEN)
    ticket_id = open_ticket("session-other-customer")

    assert other.get(f"/human-handoff/{ticket_id}").status_code == 403
    assert other.post(
        f"/human-handoff/{ticket_id}/assume", json={"assignee": "cliente2001"}
    ).status_code == 403
    assert other.post(
        f"/human-handoff/{ticket_id}/complete", json={"resolution": "Resolvido"}
    ).status_code == 403


def test_attendant_cannot_assume_on_behalf_of_someone_else(example_auth):
    attendant = as_user(ATTENDANT_TOKEN)
    ticket_id = open_ticket("session-assume-other")

    response = attendant.post(
        f"/human-handoff/{ticket_id}/assume", json={"assignee": "atendente_02"}
    )

    assert response.status_code == 403
    assert attendant.get(f"/human-handoff/{ticket_id}").json()["status"] == "pending"


def test_ticket_must_be_assumed_before_completion(example_auth):
    attendant = as_user(ATTENDANT_TOKEN)
    ticket_id = open_ticket("session-complete-early")

    too_early = attendant.post(
        f"/human-handoff/{ticket_id}/complete", json={"resolution": "Resolvido"}
    )
    assert too_early.status_code == 400
    assert attendant.get(f"/human-handoff/{ticket_id}").json()["status"] == "pending"

    attendant.post(f"/human-handoff/{ticket_id}/assume", json={"assignee": "atendente_01"})
    completed = attendant.post(
        f"/human-handoff/{ticket_id}/complete", json={"resolution": "Resolvido"}
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_invalid_or_missing_token_is_rejected(example_auth):
    assert TestClient(app).get("/human-handoff").status_code == 401
    assert as_user("token-invalido").get("/human-handoff").status_code == 401
