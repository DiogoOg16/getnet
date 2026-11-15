"""SEC-01 e SEC-02: mascaramento de dados pessoais antes de persistir e de
enviar texto a serviços externos.

Os testes de persistência leem o conteúdo efetivamente gravado em disco; o de
busca inspeciona o argumento efetivamente enviado ao provedor (mock).
"""

import json

import pytest
import requests
from fastapi.testclient import TestClient

from app.agents.router import RouterAgent
from app.agents.web_search import WebSearchAgent
from app.human_handoff import HumanHandoffStore
from app.main import app, handoff_store, session_memory
from app.privacy import contains_card_number, mask_sensitive, mask_sensitive_data
from app.session_memory import SessionMemory

RAW_VALUES = (
    "123.456.789-09",
    "12345678909",
    "12.345.678/0001-90",
    "4111 1111 1111 1111",
    "4111111111111111",
    "joao.silva@empresa.com.br",
    "98765-4321",
)


def assert_no_raw_values(text: str) -> None:
    for raw in RAW_VALUES:
        assert raw not in text, f"dado pessoal {raw!r} presente: {text!r}"


# --- mascaramento: casos positivos -----------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Meu CPF é 123.456.789-09", "Meu CPF é [CPF]"),
        ("cpf 12345678909", "cpf [CPF]"),
        ("cpf 123 456 789 09", "cpf [CPF]"),
        ("cpf 123456789-09", "cpf [CPF]"),
        ("CNPJ 12.345.678/0001-90", "CNPJ [CNPJ]"),
        ("cnpj 12345678000190", "cnpj [CNPJ]"),
        ("cartão 4111 1111 1111 1111", "cartão [CARTAO]"),
        ("cartão 4111-1111-1111-1111", "cartão [CARTAO]"),
        ("cartão 4111111111111111", "cartão [CARTAO]"),
        ("cartão 4111.1111.1111.1111", "cartão [CARTAO]"),
        ("amex 378282246310005", "amex [CARTAO]"),
        ("amex 3782 822463 10005", "amex [CARTAO]"),
        ("diners 3056-930902-5904", "diners [CARTAO]"),
        ("cartão de 13 dígitos 4222222222222", "cartão de 13 dígitos [CARTAO]"),
        ("cartão de 19 dígitos 6011 0009 9013 9424 123", "cartão de 19 dígitos [CARTAO]"),
        ("e-mail joao.silva@empresa.com.br", "e-mail [EMAIL]"),
        ("escreva para joao.silva+teste@empresa.com.br.", "escreva para [EMAIL]."),
        ("ligue +55 11 98765-4321", "ligue [TELEFONE]"),
        ("ligue (11) 98765-4321", "ligue [TELEFONE]"),
        ("fixo (11)3456-7890", "fixo [TELEFONE]"),
        ("meu celular é 11 98765-4321", "meu celular é [TELEFONE]"),
        ("telefone: 1134567890", "telefone: [TELEFONE]"),
        ("whatsapp 11987654321", "whatsapp [TELEFONE]"),
        ("telefone 3456-7890", "telefone [TELEFONE]"),
        ("ligue 98765-4321", "ligue [TELEFONE]"),
        ("ligue para (11) 3456-7890", "ligue para [TELEFONE]"),
        ("meu número é 11 98765-4321", "meu número é [TELEFONE]"),
        ("meu celular é 98765 4321", "meu celular é [TELEFONE]"),
        ("meus telefones: 3456-7890", "meus telefones: [TELEFONE]"),
    ],
)
def test_masks_personal_data(text, expected):
    assert mask_sensitive(text) == expected


def test_masks_several_values_in_the_same_message():
    text = (
        "Sou joao.silva@empresa.com.br, CPF 123.456.789-09, "
        "cartão 4111 1111 1111 1111, celular (11) 98765-4321."
    )

    masked = mask_sensitive(text)

    assert masked == "Sou [EMAIL], CPF [CPF], cartão [CARTAO], celular [TELEFONE]."
    assert_no_raw_values(masked)


def test_masks_strings_inside_nested_structures():
    data = {"flow": "terminal_connectivity", "original_message": "CPF 12345678909", "n": 3,
            "items": ["cartão 4111111111111111"]}

    assert mask_sensitive_data(data) == {
        "flow": "terminal_connectivity",
        "original_message": "CPF [CPF]",
        "n": 3,
        "items": ["cartão [CARTAO]"],
    }


# --- mascaramento: casos negativos (falsos positivos) -----------------------

@pytest.mark.parametrize(
    "text",
    [
        "Qual o status da transação txn1003?",
        "A transação txn1003 está recusada. Valor: R$ 75.00.",
        "Valor de R$ 1.500,00 e de R$ 149,90",
        "Venda de 20/10/2026, liquidação em 2026-10-21",
        "Recusada em 2026-10-20T12:40:00Z",
        "Código de autorização 123456",
        "Erro ADQ 4-91 na maquininha",
        "Parcelar em até 48 vezes no cartão de crédito",
        "Ticket: a1b2c3d4e5f6",
        "Ticket: 123456789012",
        "Meu nome é Diogo",
        "Get Smart custa R$ 129,90/mês, isenção acima de R$ 40 mil",
        # datas e listas de valores não formam grupos de cartão
        "Liquidações de 2026-11-11 2026-11-13",
        "vendas de 10 20 30 40 50 60 70 reais",
        "Valor de R$ 1.234.567,89",
        # número sem palavra de contexto não é telefone
        "número do pedido 1234567890",
        "número da transação txn1003",
        "Central de atendimento 4002-4000",
        "Pedido 98765-4321 enviado",
    ],
)
def test_does_not_mask_identifiers_amounts_dates_or_short_codes(text):
    assert mask_sensitive(text) == text


def test_router_still_detects_cpf_and_card_with_the_shared_patterns():
    router = RouterAgent()

    assert router.route("Meu CPF é 123.456.789-09").agent == "human_escalation"
    assert router.route("Meu cartão é 4111 1111 1111 1111").agent == "human_escalation"
    assert router.route("Qual o status da transação txn1003?").agent == "customer_support"


# --- persistência: conteúdo efetivamente gravado ---------------------------

def test_session_memory_file_contains_no_personal_data(tmp_path):
    path = tmp_path / "memory.json"
    memory = SessionMemory(storage_path=str(path))

    memory.add_message(
        user_id="cliente1988",
        session_id="s1",
        message="Meu CPF é 123.456.789-09 e meu e-mail joao.silva@empresa.com.br",
        response="Recebi o cartão 4111 1111 1111 1111.",
        pending_followup={
            "flow": "terminal_connectivity",
            "original_message": "Minha maquininha não conecta, celular (11) 98765-4321",
        },
    )

    stored = path.read_text(encoding="utf-8")
    assert_no_raw_values(stored)
    entry = json.loads(stored)["cliente1988:s1"][0]
    assert entry["message"] == "Meu CPF é [CPF] e meu e-mail [EMAIL]"
    assert entry["response"] == "Recebi o cartão [CARTAO]."
    assert entry["pending_followup"] == {
        "flow": "terminal_connectivity",
        "original_message": "Minha maquininha não conecta, celular [TELEFONE]",
    }


def test_session_memory_keeps_non_personal_facts(tmp_path):
    path = tmp_path / "memory.json"
    memory = SessionMemory(storage_path=str(path))

    memory.add_message(
        user_id="cliente1988",
        session_id="s1",
        message="Qual o status da transação txn1003?",
        response="A transação txn1003 está recusada. Valor: R$ 75.00.",
    )

    assert memory.get_recent_context(user_id="cliente1988", session_id="s1") == [
        "Usuário: Qual o status da transação txn1003?",
        "Assistente: A transação txn1003 está recusada. Valor: R$ 75.00.",
    ]


def test_ticket_file_contains_no_personal_data(tmp_path):
    path = tmp_path / "tickets.json"
    store = HumanHandoffStore(storage_path=str(path))

    ticket = store.create(
        user_id="cliente1988",
        session_id="s1",
        message="Preciso de ajuda, CPF 12345678909, cartão 4111-1111-1111-1111",
    )
    store.assume(ticket["id"], "atendente_01")
    store.complete(
        ticket["id"],
        "Contato feito pelo e-mail joao.silva@empresa.com.br",
        actor="atendente_01",
    )

    stored = path.read_text(encoding="utf-8")
    assert "4111-1111-1111-1111" not in stored
    assert_no_raw_values(stored)
    record = json.loads(stored)[ticket["id"]]
    assert record["message"] == "Preciso de ajuda, CPF [CPF], cartão [CARTAO]"
    assert record["resolution"] == "Contato feito pelo e-mail [EMAIL]"


def test_chat_with_personal_data_never_persists_or_echoes_it():
    client = TestClient(app, headers={"Authorization": "Bearer test-token-cliente1988"})
    message = (
        "Meu CPF é 123.456.789-09 e meu cartão 4111 1111 1111 1111, "
        "e-mail joao.silva@empresa.com.br, preciso de ajuda"
    )

    response = client.post(
        "/chat",
        json={"message": message, "user_id": "cliente1988", "session_id": "sec01-e2e"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent"] == "human_escalation"
    assert payload["handoff"]["status"] == "pending"
    # resposta HTTP: eco da pergunta e ticket sem o dado original
    assert_no_raw_values(json.dumps(payload, ensure_ascii=False))
    assert payload["message"] == (
        "Meu CPF é [CPF] e meu cartão [CARTAO], e-mail [EMAIL], preciso de ajuda"
    )
    assert payload["handoff"]["message"] == payload["message"]
    # arquivos gravados pela própria API
    assert_no_raw_values(handoff_store.storage_path.read_text(encoding="utf-8"))
    assert_no_raw_values(session_memory.storage_path.read_text(encoding="utf-8"))

    attendant = TestClient(app, headers={"Authorization": "Bearer test-token-atendente_01"})
    listed = attendant.get("/human-handoff").json()
    assert_no_raw_values(json.dumps(listed, ensure_ascii=False))


def test_chat_without_personal_data_echoes_message_unchanged():
    client = TestClient(app, headers={"Authorization": "Bearer test-token-cliente1988"})
    message = "Qual o status da transação txn1001?"

    response = client.post(
        "/chat",
        json={"message": message, "user_id": "cliente1988", "session_id": "sec01-plain"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == message


# --- busca externa: argumento enviado ao provedor --------------------------

class FakeSearchResponse:
    text = """
    <div class="result">
      <a class="result__a" href="https://www.bcb.gov.br/conversao">Banco Central</a>
      <a class="result__snippet">Conversor oficial.</a>
    </div>
    """

    def raise_for_status(self):
        return None


def capture_search(monkeypatch) -> list:
    sent = []

    def fake_post(*args, **kwargs):
        sent.append(kwargs.get("data"))
        return FakeSearchResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    return sent


def test_external_search_never_receives_personal_data(monkeypatch):
    sent = capture_search(monkeypatch)

    WebSearchAgent().answer(
        "notícias sobre joao.silva@empresa.com.br celular (11) 98765-4321 cpf 123.456.789-09"
    )

    assert sent == [{"q": "notícias sobre [EMAIL] celular [TELEFONE] cpf [CPF]"}]
    assert_no_raw_values(json.dumps(sent, ensure_ascii=False))


def test_external_search_without_personal_data_is_unchanged_and_works(monkeypatch):
    sent = capture_search(monkeypatch)
    query = "indicadores economia Brasil 2026 txn1003 R$ 149,90 em 20/10/2026"

    result = WebSearchAgent().answer(query)

    assert sent == [{"q": query}]
    assert result["tool_used"] == "duckduckgo_search"
    assert result["sources"] == ["https://www.bcb.gov.br/conversao"]


# --- A.2: cartão em agrupamento incomum, só com palavra de cartão ----------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cartão 4111 1111 1111 111", "cartão [CARTAO]"),
        ("cartão de crédito 41111 11111 11111", "cartão de crédito [CARTAO]"),
        ("meu visa é 411111 111111 1111", "meu visa é [CARTAO]"),
        ("card 4111-111-111-111-111", "card [CARTAO]"),
        ("cartão 4111.1111.1111.111", "cartão [CARTAO]"),
        ("número do cartão: 4111 1111 1111 111", "número do cartão: [CARTAO]"),
    ],
)
def test_a2_card_unusual_grouping_after_card_keyword_is_masked(text, expected):
    assert mask_sensitive(text) == expected
    assert contains_card_number(text)


@pytest.mark.parametrize(
    "text",
    [
        "vendas no cartão de 2026-11-11 2026-11-13",
        "cartão parcelado em 12 vezes de R$ 100",
        "cartão final 1234",
        "crédito de R$ 1.234.567,89",
        "débito em 10 20 30 40 50 60 70 reais",
        "cartão com 12 3456 7890 123 dígitos",
        # sem palavra de cartão, agrupamento incomum não é detectado (limitação aceita)
        "4111 1111 1111 111",
    ],
)
def test_a2_card_negatives_stay_intact(text):
    assert mask_sensitive(text) == text
    assert not contains_card_number(text)


@pytest.mark.parametrize(
    "text",
    [
        "Meu cartão é 4111 1111 1111 111",
        "cartão de crédito 41111 11111 11111",
        "meu visa é 411111 111111 1111",
        "card 4111-111-111-111-111",
        "cartão 4111.1111.1111.111",
        # formatos estruturais continuam escalonados
        "Meu cartão é 4111 1111 1111 1111",
        "4111111111111111",
    ],
)
def test_a2_router_escalates_card_numbers(text):
    assert RouterAgent().route(text).agent == "human_escalation"


@pytest.mark.parametrize(
    "text",
    [
        "vendas no cartão de 2026-11-11 2026-11-13",
        "Qual o status da transação txn1003?",
    ],
)
def test_a2_router_does_not_escalate_card_negatives(text):
    assert RouterAgent().route(text).agent != "human_escalation"


# --- A.2: "número" só é contexto de telefone em frases específicas ---------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("meu número é 11 98765-4321", "meu número é [TELEFONE]"),
        ("número de telefone 3456-7890", "número de telefone [TELEFONE]"),
        ("número do celular: 98765-4321", "número do celular: [TELEFONE]"),
        ("número do WhatsApp 11987654321", "número do WhatsApp [TELEFONE]"),
    ],
)
def test_a2_phone_number_phrases_are_context(text, expected):
    assert mask_sensitive(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "número 1234567890",
        "número do pedido 1234567890",
        "número da transação txn1003",
    ],
)
def test_a2_bare_numero_is_not_phone_context(text):
    assert mask_sensitive(text) == text
