import pytest

from app.agents.router import RouterAgent

# Perguntas normais que NÃO devem escalar para humano.
NOT_ESCALATED = [
    ("Qual a diferença entre as maquininhas de cartão da Getnet?", "knowledge"),
    ("Como cadastrar uma chave Pix na Getnet?", "knowledge"),
    ("Quais dados sensíveis a Getnet guarda?", "knowledge"),
    ("Esqueci minha senha do portal da Getnet", "knowledge"),
]

# Pedidos que DEVEM escalar para humano.
ESCALATED = [
    "Quero falar com um atendente",
    "Preciso de atendimento humano",
    "I want to talk to a human",
    "Não consigo continuar, preciso de ajuda urgente",
    "Preciso de ajuda com dados pessoais sensíveis",
    "Meu CPF é 123.456.789-09, pode confirmar?",
    "O número do meu cartão é 4111 1111 1111 1111",
]


@pytest.mark.parametrize("message,expected", NOT_ESCALATED)
def test_normal_questions_are_not_escalated(message, expected):
    assert RouterAgent().route(message).agent == expected


@pytest.mark.parametrize("message", ESCALATED)
def test_sensitive_or_human_requests_are_escalated(message):
    assert RouterAgent().route(message).agent == "human_escalation"
