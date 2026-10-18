import pytest

from app.agents.router import RouterAgent

CASES = [
    # Cenários do desafio (inglês)
    ("What's the difference between the Get Clássica and the Get Smart?", "knowledge"),
    ("What's the weather forecast in Porto Alegre tomorrow?", "web_search"),
    ("When will the money from yesterday's sales be deposited?", "customer_support"),
    ("Do I need a bank account to receive my sales via Pix?", "knowledge"),
    ("My card machine won't connect to the internet, what should I do?", "knowledge"),
    ("How does receivables advance (antecipação) work with Getnet?", "knowledge"),
    ("What's the euro exchange rate today?", "web_search"),
    ("My card machine is showing a transaction decline error.", "knowledge"),
    ("How many installments can I split a sale into with the crediário?", "knowledge"),
    ("Can I sell through WhatsApp using the Payment Link?", "knowledge"),
    # Equivalentes em português
    ("Qual a diferença entre a Get Clássica e a Get Smart?", "knowledge"),
    ("Quando o dinheiro das vendas de ontem será depositado?", "customer_support"),
    ("Preciso de conta bancária para receber vendas por Pix?", "knowledge"),
    ("Minha maquininha não conecta na internet, o que fazer?", "knowledge"),
    ("Como funciona a antecipação de recebíveis?", "knowledge"),
    ("Qual é a cotação do euro hoje?", "web_search"),
    # Transação, fallback e falsos positivos
    ("Qual o status da transação txn1001?", "customer_support"),
    ("Como antecipar minhas vendas pelo app?", "knowledge"),
    ("Meu neurologista atende hoje?", "fallback"),
    ("Me conte uma curiosidade aleatória", "fallback"),
]


@pytest.mark.parametrize("message,expected", CASES)
def test_routing_decisions(message, expected):
    assert RouterAgent().route(message).agent == expected
