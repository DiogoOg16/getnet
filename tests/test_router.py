from app.agents.router import RouterAgent


def test_routes_product_question_to_knowledge():
    router = RouterAgent()

    result = router.route(
        "Qual a diferença entre as maquininhas da Getnet?"
    )

    assert result.agent == "knowledge"


def test_routes_device_problem_to_knowledge():
    router = RouterAgent()

    result = router.route(
        "Minha máquina não conecta à internet"
    )

    assert result.agent == "knowledge"


def test_routes_payment_problem_to_support():
    router = RouterAgent()

    result = router.route(
        "Não recebi meu pagamento"
    )

    assert result.agent == "customer_support"


def test_unknown_message_uses_fallback():
    router = RouterAgent()

    result = router.route(
        "Quero conversar sobre outro assunto"
    )

    assert result.agent == "fallback"


def test_routes_current_weather_to_web_search():
    result = RouterAgent().route("Como está o tempo em Porto Alegre?")
    assert result.agent == "web_search"


def test_routes_currency_question_to_web_search():
    result = RouterAgent().route("Qual é a cotação do euro hoje?")
    assert result.agent == "web_search"


def test_routes_election_question_to_web_search():
    result = RouterAgent().route(
        "Quem ganhou a última eleição presidencial francesa?"
    )
    assert result.agent == "web_search"


def test_support_has_priority_over_web_keywords():
    result = RouterAgent().route(
        "Não recebi meu pagamento hoje"
    )
    assert result.agent == "customer_support"
