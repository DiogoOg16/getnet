from app.agents.router import RouterAgent


def test_routes_product_question_to_knowledge():
    router = RouterAgent()

    result = router.route(
        "Qual a diferença entre as maquininhas da Getnet?"
    )

    assert result.agent == "knowledge"


def test_routes_device_problem_to_support():
    router = RouterAgent()

    result = router.route(
        "Minha máquina não conecta à internet"
    )

    assert result.agent == "customer_support"


def test_routes_payment_problem_to_support():
    router = RouterAgent()

    result = router.route(
        "Não recebi meu pagamento"
    )

    assert result.agent == "customer_support"


def test_routes_settlement_timing_question_to_support():
    assert RouterAgent().route(
        "Quando o dinheiro das vendas de ontem será depositado?"
    ).agent == "customer_support"
    assert RouterAgent().route(
        "When will the money from yesterday's sales be deposited?"
    ).agent == "customer_support"


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


def test_routes_generic_pix_concept_to_web_search():
    result = RouterAgent().route("O que é o Pix?")
    assert result.agent == "web_search"


def test_routes_how_it_works_pix_question_to_knowledge():
    result = RouterAgent().route("Como funciona o Pix?")
    assert result.agent == "knowledge"


def test_routes_settlement_paraphrases_to_support():
    for message in [
        "O dinheiro das vendas de ontem não entrou",
        "cadê meu pagamento?",
        "Não entrou o dinheiro das vendas de ontem",
    ]:
        assert RouterAgent().route(message).agent == "customer_support"


def test_distinguishes_declined_sale_from_installment_context():
    assert RouterAgent().route("Minha venda foi recusada").agent == "customer_support"
    assert RouterAgent().route("quero saber como funciona uma venda parcelada").agent == "knowledge"
    assert RouterAgent().route("MINHA MAQUININHA NÃO CONECTA NA INTERNET!").agent == "customer_support"


def test_audit_examples_for_configuration_vs_operational_failures():
    cases = [
        ("Minha maquininha não conecta na internet e não funciona.", "customer_support"),
        ("Minha maquininha não conecta na internet.", "customer_support"),
        ("Como configurar o Wi-Fi na maquininha Getnet?", "knowledge"),
        ("Como trocar a rede Wi-Fi da maquininha?", "knowledge"),
        ("Minha maquininha conecta, mas cai toda hora.", "customer_support"),
        ("Como usar a maquininha Getnet?", "knowledge"),
        ("Minha venda foi recusada.", "customer_support"),
        ("Como funciona uma venda parcelada?", "knowledge"),
    ]

    router = RouterAgent()
    for message, expected_agent in cases:
        assert router.route(message).agent == expected_agent


def test_routes_unsupported_sensitive_request_to_human_escalation():
    result = RouterAgent().route(
        "Preciso de ajuda com dados pessoais sensíveis e não posso continuar aqui."
    )
    assert result.agent == "human_escalation"
