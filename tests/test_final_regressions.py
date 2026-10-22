from app.agents.customer_support import CustomerSupportAgent
from app.rag.retriever import retrieve


def _contents(query):
    return " ".join(r["content"] for r in retrieve(query, limit=3))


def test_crediario_installments_retrieves_48x_chunk_in_portuguese():
    assert "48 vezes" in _contents("Quantas parcelas posso fazer no crediário?")


def test_crediario_installments_retrieves_48x_chunk_in_english():
    assert "48 vezes" in _contents(
        "How many installments can I split a sale into with the crediário?"
    )


def test_settlement_timing_question_in_english_is_answered():
    result = CustomerSupportAgent().answer(
        "When will the money from yesterday's sales be deposited?",
        "cliente1988",
    )

    assert result["tool_used"] == "settlement_timeline"
