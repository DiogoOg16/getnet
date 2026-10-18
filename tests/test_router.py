from app.agents.router import RouterAgent


def test_routes_product_question_to_knowledge():
    router = RouterAgent()

    result = router.route(
        "Qual a diferença entre as maquininhas da Getnet?"
    )

    assert result.agent == "knowledge"


def test_routes_customer_issue_to_support():
    router = RouterAgent()

    result = router.route(
        "Minha máquina não conecta à internet"
    )

    assert result.agent == "customer_support"


def test_unknown_message_uses_fallback():
    router = RouterAgent()

    result = router.route(
        "Quero conversar sobre outro assunto"
    )

    assert result.agent == "fallback"
