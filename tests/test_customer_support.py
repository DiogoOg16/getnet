import socket

from app.agents.customer_support import CustomerSupportAgent
from app.llm.ollama_client import OllamaClient
from app.llm.ollama_function_calling import OllamaFunctionCallingLoop
from app.llm.ollama_client import OllamaTimeoutError
from app.tools.customer_tools import (
    lookup_customer,
    lookup_settlement,
    lookup_transaction,
    register_customer_tools,
)
from app.tools.registry import ToolExecutor, tool_registry

register_customer_tools(tool_registry)


def test_lookup_existing_customer():
    result = lookup_customer("cliente1988")

    assert result["found"] is True
    assert result["customer"]["account_status"] == "active"


def test_lookup_unknown_customer():
    result = lookup_customer("cliente_inexistente")

    assert result["found"] is False


def test_lookup_transaction_owned_by_customer():
    result = lookup_transaction("txn1001", "cliente1988")

    assert result["found"] is True
    assert result["transaction"]["status"] == "approved"


def test_customer_cannot_lookup_another_customers_transaction():
    result = lookup_transaction("txn2001", "cliente1988")

    assert result["found"] is False


def test_agent_does_not_reveal_other_customers_transaction_details():
    result = CustomerSupportAgent().answer(
        "Por que a transação txn2001 foi recusada e como resolver?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["issue_resolved"] is False
    normalized = result["response"].lower()
    assert "não encontrei" in normalized or "não posso confirmar" in normalized
    assert "R$ 250.00" not in result["response"]


def test_agent_answers_transaction_question():
    result = CustomerSupportAgent().answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["tool_used"] == "lookup_transaction"
    assert "aprovada" in result["response"]


def test_agent_answers_customer_account_question():
    result = CustomerSupportAgent().answer(
        "Quero consultar minha conta",
        "cliente1988",
    )

    assert result["tool_used"] == "lookup_customer"
    assert "Cliente de Teste" in result["response"]


def test_agent_handles_settlement_timing_question_without_transaction_id():
    result = CustomerSupportAgent().answer(
        "Quando o dinheiro das vendas de ontem será depositado?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert "prazo" in result["response"].lower()
    assert "Registro 1" in result["response"]
    assert "Registro 2" in result["response"]
    assert "2026-11-05" in result["response"]
    assert "2026-11-12" in result["response"]
    assert "transação" in result["response"].lower() or "txn" in result["response"].lower()


def test_agent_lists_each_settlement_record_with_available_fields():
    result = CustomerSupportAgent().answer(
        "Quando o dinheiro das vendas será depositado?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert "Registro 1" in result["response"]
    assert "status scheduled" in result["response"].lower()
    assert "R$ 149.90" in result["response"]
    assert "BRL" in result["response"]
    assert "2026-11-05" in result["response"]
    assert "Registro 2" in result["response"]
    assert "status processing" in result["response"].lower()
    assert "R$ 89.50" in result["response"]
    assert "2026-11-12" in result["response"]


def test_agent_reports_missing_settlement_date_when_not_available(monkeypatch):
    from app.tools import customer_tools

    monkeypatch.setitem(
        customer_tools.SETTLEMENTS,
        "cliente1988",
        [{
            "settlement_id": "settlement_003",
            "customer_id": "cliente1988",
            "transaction_id": "txn1003",
            "status": "failed",
            "amount": 75.00,
            "currency": "BRL",
        }],
    )

    result = CustomerSupportAgent().answer(
        "Quando o dinheiro será depositado?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert "data prevista: não disponível" in result["response"].lower()
    assert "R$ 75.00" in result["response"]
    assert "status failed" in result["response"].lower()


def test_lookup_settlement_empty_records_for_known_customer_without_settlements():
    result = lookup_settlement("cliente2001")

    assert result["found"] is True
    assert result["simulated"] is True
    assert result["customer_id"] == "cliente2001"
    assert result["records"] == []
    assert "não há registros" in result["message"].lower()


def test_lookup_settlement_rejects_unknown_customer():
    result = lookup_settlement("cliente_inexistente")

    assert result["found"] is False
    assert result["simulated"] is True
    assert result["customer_id"] == "cliente_inexistente"


def test_agent_gives_guidance_for_declined_transaction_without_id():
    result = CustomerSupportAgent().answer(
        "My card machine is showing a transaction decline error.",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["tool_used"] is None
    assert (
        "recus" in result["response"].lower()
        or "declin" in result["response"].lower()
    )
    assert "txn" in result["response"].lower()

def test_lookup_settlement_returns_simulated_data():
    result = lookup_settlement("cliente1988")

    assert result["found"] is True
    assert result["simulated"] is True
    assert result["customer_id"] == "cliente1988"
    assert result["records"]
    assert "message" in result


def test_lookup_settlement_returns_empty_records_for_known_customer_without_settlements():
    result = lookup_settlement("cliente2001")

    assert result["found"] is True
    assert result["simulated"] is True
    assert result["customer_id"] == "cliente2001"
    assert result["records"] == []
    assert "não há registros" in result["message"].lower()


def test_lookup_settlement_rejects_unknown_customer():
    result = lookup_settlement("cliente_inexistente")

    assert result["found"] is False
    assert result["simulated"] is True
    assert result["customer_id"] == "cliente_inexistente"


def test_agent_uses_decline_reason_when_available():
    result = CustomerSupportAgent().answer(
        "Qual o status da transação txn2001?",
        "cliente2001",
    )

    assert result["agent"] == "customer_support"
    assert "recusada" in result["response"].lower()
    assert "Cartão bloqueado pelo emissor" in result["response"]
    assert all(fact["name"] != "decline_reason" for fact in result["verified_facts"])


def test_agent_reports_missing_decline_detail_when_reason_is_not_registered():
    result = CustomerSupportAgent().answer(
        "Qual o status da transação txn1003?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert "recusada" in result["response"].lower()
    assert "não há detalhes disponíveis" in result["response"].lower()
    assert all(fact["name"] != "decline_reason" for fact in result["verified_facts"])


def test_agent_detects_terminal_connectivity_issue_and_requests_missing_context():
    result = CustomerSupportAgent().answer(
        "Minha maquininha não conecta na internet.",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["awaiting_user_input"] is True
    assert result["handoff_required"] is False
    assert "wi-fi" in result["response"].lower() or "rede" in result["response"].lower()
    assert "mensagem" in result["response"].lower() or "sinal" in result["response"].lower()


def test_agent_detects_terminal_connectivity_issue_in_english():
    result = CustomerSupportAgent().answer(
        "My card machine won't connect to the internet, what should I do?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["awaiting_user_input"] is True
    assert result["handoff_required"] is False
    normalized = result["response"].lower()
    assert "wi-fi" in normalized or "rede" in normalized or "sinal" in normalized


def test_agent_does_not_treat_non_connectivity_device_question_as_troubleshooting():
    result = CustomerSupportAgent().answer(
        "My card machine supports contactless payments?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["tool_used"] is None
    assert "diagnóstico de conectividade" not in result["response"].lower()


def test_agent_extracts_explicit_terminal_context_from_message():
    context = CustomerSupportAgent()._extract_terminal_context(
        "Minha maquininha não conecta na internet, Wi‑Fi indisponível e mostra erro de rede.",
    )

    assert context["issue_type"] == "connectivity"
    assert context["has_internet_issue"] is True
    assert context["has_wifi_signal"] is False
    assert "erro de rede" in context["error_hint"] or context["error_hint"]


def test_agent_uses_knowledge_when_connectivity_context_is_sufficient(monkeypatch):
    fake_response = {
        "agent": "knowledge",
        "response": "Siga os passos de diagnóstico da rede Wi‑Fi e confirme se a maquininha está recebendo sinal.",
        "sources": ["faq_conectividade.md"],
        "source_sections": {"Conectividade": ["faq_conectividade.md"]},
        "tool_used": "knowledge",
        "flow_completed": True,
        "response_delivered": True,
        "issue_resolved": False,
        "resolved": False,
        "awaiting_user_input": False,
        "step_status": "success",
    }

    def fake_knowledge_answer(self, message):
        assert message == "Minha maquininha não conecta na internet e a rede Wi‑Fi está indisponível."
        return fake_response

    monkeypatch.setattr("app.agents.knowledge.KnowledgeAgent.answer", fake_knowledge_answer)

    result = CustomerSupportAgent().answer(
        "Minha maquininha não conecta na internet e a rede Wi‑Fi está indisponível.",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["handoff_required"] is False
    assert result["step_status"] == "success"
    assert result["tool_used"] == "knowledge"
    assert result["sources"] == fake_response["sources"]
    assert result["source_sections"] == fake_response["source_sections"]
    assert "Com base na documentação disponível da Getnet" in result["response"]
    normalized = result["response"].replace("‑", "-").replace("–", "-").replace("—", "-")
    assert "Siga os passos de diagnóstico da rede Wi-Fi e confirme se a maquininha está recebendo sinal." in normalized


def test_agent_handoff_when_documented_guidance_is_insufficient():
    result = CustomerSupportAgent().answer(
        "Minha maquininha não conecta na internet e não há orientação segura na base.",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["handoff_required"] is True
    assert result["step_status"] == "handoff"
    assert "atendimento humano" in result["response"].lower()


def test_agent_response_does_not_claim_nonexistent_terminal_telemetry():
    result = CustomerSupportAgent().answer(
        "Minha maquininha não conecta na internet e não funciona.",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert "telemetria" not in result["response"].lower()
    assert "offline" not in result["response"].lower() or "offline" in result["response"].lower()
    assert "wifi" in result["response"].lower() or "rede" in result["response"].lower() or "sinal" in result["response"].lower()


class FakeFunctionCallingLoop:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def run(self, messages, *, context=None, tools=None):
        self.calls.append({"messages": messages, "context": context, "tools": tools})
        if self.error is not None:
            raise self.error
        return self.result


class SequencedFunctionCallingLoop:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(self, messages, *, context=None, tools=None):
        self.calls.append({"messages": messages, "context": context, "tools": tools})
        if not self.results:
            return {"status": "completed", "tool_results": []}
        return self.results.pop(0)


def test_agent_tracks_successful_function_calling_result():
    loop = FakeFunctionCallingLoop(
        {
            "status": "completed",
            "tool_results": [
                {
                    "tool_name": "lookup_transaction",
                    "arguments": {"transaction_id": "txn1001"},
                    "result": {
                        "ok": True,
                        "result": {
                            "found": True,
                            "transaction": {
                                "transaction_id": "txn1001",
                                "status": "approved",
                                "amount": 49.90,
                                "currency": "BRL",
                            },
                        },
                    },
                }
            ],
        }
    )

    result = CustomerSupportAgent(loop=loop).answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["function_call_status"] == "tool_call_success"
    assert result["tool_used"] == "lookup_transaction"
    assert result["issue_resolved"] is True
    assert "aprovada" in result["response"].lower()


def test_agent_tracks_no_tool_calls_explicitly():
    loop = FakeFunctionCallingLoop({"status": "completed", "tool_results": []})

    result = CustomerSupportAgent(loop=loop).answer(
        "Quero consultar minha conta",
        "cliente1988",
    )

    assert result["function_call_status"] == "no_tool_calls"
    assert result["tool_used"] == "lookup_customer"
    assert "Cliente de Teste" in result["response"]


def test_agent_passes_only_authorized_tools_to_function_calling_loop():
    loop = FakeFunctionCallingLoop({"status": "completed", "tool_results": []})

    CustomerSupportAgent(loop=loop).answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    tool_names = {tool["function"]["name"] for tool in loop.calls[0]["tools"]}
    assert tool_names == {"lookup_transaction"}
    assert "lookup_settlement" not in tool_names
    assert "lookup_customer" not in tool_names


def test_agent_includes_explicit_tool_calling_instruction():
    loop = FakeFunctionCallingLoop({"status": "completed", "tool_results": []})

    CustomerSupportAgent(loop=loop).answer(
        "Quero consultar minha conta",
        "cliente1988",
    )

    call_messages = loop.calls[0]["messages"]
    assert len(call_messages) == 2
    assert call_messages[0]["role"] == "system"
    instruction = call_messages[0]["content"].lower()
    assert "ferramentas autorizadas" in instruction
    assert "lookup_customer" in instruction
    assert "deve chamar a ferramenta autorizada" in instruction
    assert "não peça user_id" in instruction
    assert call_messages[1] == {"role": "user", "content": "Quero consultar minha conta"}


def test_agent_retries_once_when_model_returns_no_tool_calls():
    loop = SequencedFunctionCallingLoop(
        [
            {"status": "completed", "tool_results": []},
            {
                "status": "completed",
                "tool_results": [
                    {
                        "tool_name": "lookup_customer",
                        "arguments": {},
                        "result": {
                            "ok": True,
                            "result": {
                                "found": True,
                                "customer": {
                                    "name": "Cliente de Teste",
                                    "account_status": "active",
                                },
                            },
                        },
                    }
                ],
            },
        ]
    )

    result = CustomerSupportAgent(loop=loop).answer(
        "Quero consultar minha conta",
        "cliente1988",
    )

    assert len(loop.calls) == 2
    assert result["function_call_status"] == "tool_call_success"
    retry_instruction = loop.calls[1]["messages"][0]["content"].lower()
    assert "tentativa obrigatória de correção" in retry_instruction
    assert "gere tool_calls agora" in retry_instruction


def test_agent_uses_backend_fallback_on_ollama_connection_error_for_transaction():
    loop = FakeFunctionCallingLoop(error=ConnectionError("ollama unavailable"))

    result = CustomerSupportAgent(loop=loop).answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["function_call_status"] == "no_tool_calls"
    assert result["tool_used"] == "lookup_transaction"
    assert result["issue_resolved"] is True
    assert result["step_status"] == "success"
    assert "txn1001" in result["response"]


def test_agent_uses_backend_fallback_on_ollama_connection_error_for_customer_lookup():
    loop = FakeFunctionCallingLoop(error=ConnectionError("ollama unavailable"))

    result = CustomerSupportAgent(loop=loop).answer(
        "Quero consultar minha conta",
        "cliente1988",
    )

    assert result["function_call_status"] == "no_tool_calls"
    assert result["tool_used"] == "lookup_customer"
    assert result["issue_resolved"] is True
    assert result["step_status"] == "success"
    assert "Cliente de Teste" in result["response"]


def test_agent_uses_backend_fallback_on_ollama_connection_error_for_settlement_lookup():
    loop = FakeFunctionCallingLoop(error=ConnectionError("ollama unavailable"))

    result = CustomerSupportAgent(loop=loop).answer(
        "Quando o dinheiro das vendas de ontem será depositado?",
        "cliente1988",
    )

    assert result["function_call_status"] == "no_tool_calls"
    assert result["tool_used"] == "lookup_settlement"
    assert result["issue_resolved"] is True
    assert result["step_status"] == "success"
    assert "Prazo de recebimento" in result["response"]


def test_agent_uses_backend_fallback_on_ollama_timeout_error():
    loop = FakeFunctionCallingLoop(error=OllamaTimeoutError("timed out"))

    result = CustomerSupportAgent(loop=loop).answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["function_call_status"] == "no_tool_calls"
    assert result["tool_used"] == "lookup_transaction"
    assert result["issue_resolved"] is True


def test_integration_connection_refused_triggers_deterministic_transaction_fallback():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        refused_port = sock.getsockname()[1]

    client = OllamaClient(base_url=f"http://127.0.0.1:{refused_port}", timeout=1)
    executor = ToolExecutor(tool_registry)
    loop = OllamaFunctionCallingLoop(
        client=client,
        registry=tool_registry,
        executor=executor,
        max_iterations=3,
    )
    agent = CustomerSupportAgent(
        client=client,
        registry=tool_registry,
        executor=executor,
        loop=loop,
    )

    transaction_id = "txn1001"
    result = agent.answer(
        f"Qual o status da transação {transaction_id}?",
        "cliente1988",
    )

    assert result["function_call_status"] == "no_tool_calls"
    assert result["tool_used"] == "lookup_transaction"
    assert result["issue_resolved"] is True
    assert transaction_id in result["response"]

    facts = result["verified_facts"]
    assert facts
    assert all(fact["entity"] == transaction_id for fact in facts)
    assert {fact["name"] for fact in facts} == {"status", "amount", "currency"}


def test_agent_does_not_fallback_for_non_infrastructure_tool_call_error():
    loop = FakeFunctionCallingLoop(error=RuntimeError("unexpected llm orchestration bug"))

    result = CustomerSupportAgent(loop=loop).answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["function_call_status"] == "tool_call_error"
    assert result["tool_used"] is None
    assert result["issue_resolved"] is False
    assert result["step_status"] == "tool_call_error"


def test_agent_tracks_max_iterations_exceeded_without_fallback():
    loop = FakeFunctionCallingLoop({"status": "max_iterations_exceeded", "tool_results": []})

    result = CustomerSupportAgent(loop=loop).answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["function_call_status"] == "max_iterations_exceeded"
    assert result["tool_used"] is None
    assert result["issue_resolved"] is False
    assert len(loop.calls) == 1


def test_agent_preserves_second_attempt_max_iterations_state():
    loop = SequencedFunctionCallingLoop(
        [
            {"status": "completed", "tool_results": []},
            {"status": "max_iterations_exceeded", "tool_results": []},
        ]
    )

    result = CustomerSupportAgent(loop=loop).answer(
        "Quero consultar minha conta",
        "cliente1988",
    )

    assert len(loop.calls) == 2
    assert result["function_call_status"] == "max_iterations_exceeded"
    assert result["tool_used"] is None
    assert result["issue_resolved"] is False


def test_run_function_calling_preserves_retry_error_and_metadata():
    retry_result = {
        "status": "max_iterations_exceeded",
        "error": "Function-calling loop exceeded the iteration limit.",
        "tool_results": [],
        "iterations": 5,
        "last_response": {"message": {"role": "assistant", "content": ""}},
        "malformed_tool_calls": ["x"],
    }
    loop = SequencedFunctionCallingLoop(
        [
            {"status": "completed", "tool_results": []},
            retry_result,
        ]
    )

    payload = CustomerSupportAgent(loop=loop)._run_function_calling(
        "Quero consultar minha conta",
        "cliente1988",
        allowed_tools=["lookup_customer"],
    )

    assert payload["status"] == "max_iterations_exceeded"
    assert payload["error"] == "Function-calling loop exceeded the iteration limit."
    assert payload["iterations"] == 5
    assert payload["malformed_tool_calls"] == ["x"]
    assert isinstance(payload["tool_results"], list)


def test_run_function_calling_validates_retry_tool_results_as_list():
    loop = SequencedFunctionCallingLoop(
        [
            {"status": "completed", "tool_results": []},
            {"status": "tool_call_error", "error": "network", "tool_results": {"invalid": True}},
        ]
    )

    payload = CustomerSupportAgent(loop=loop)._run_function_calling(
        "Quero consultar minha conta",
        "cliente1988",
        allowed_tools=["lookup_customer"],
    )

    assert payload["status"] == "invalid_result"
    assert "tool_results" in payload["error"].lower()


class FailOnSecondRunLoop:
    def __init__(self):
        self.calls = []

    def run(self, messages, *, context=None, tools=None):
        self.calls.append({"messages": messages, "context": context, "tools": tools})
        if len(self.calls) == 1:
            return {"status": "completed", "tool_results": []}
        raise ConnectionError("ollama unavailable on retry")


def test_agent_preserves_second_attempt_connection_error_state():
    loop = FailOnSecondRunLoop()

    result = CustomerSupportAgent(loop=loop).answer(
        "Quero consultar minha conta",
        "cliente1988",
    )

    assert len(loop.calls) == 2
    assert result["function_call_status"] == "no_tool_calls"
    assert result["tool_used"] == "lookup_customer"
    assert result["issue_resolved"] is True


def test_agent_tracks_malformed_function_calling_result():
    loop = FakeFunctionCallingLoop(
        {
            "status": "completed",
            "tool_results": [
                {
                    "tool_name": "lookup_transaction",
                    "arguments": {"transaction_id": "txn1001"},
                    "result": {"ok": True, "result": {"status": "approved"}},
                }
            ],
        }
    )

    result = CustomerSupportAgent(loop=loop).answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["function_call_status"] == "invalid_result"
    assert result["tool_used"] is None
    assert result["issue_resolved"] is False


def test_agent_does_not_fallback_for_invalid_tool_result_payload():
    loop = FakeFunctionCallingLoop(
        {
            "status": "completed",
            "tool_results": [
                {
                    "tool_name": "lookup_customer",
                    "arguments": {},
                    "result": {"ok": False, "error": "Invalid tool arguments."},
                }
            ],
        }
    )

    result = CustomerSupportAgent(loop=loop).answer(
        "Quero consultar minha conta",
        "cliente1988",
    )

    assert result["function_call_status"] == "invalid_result"
    assert result["tool_used"] == "lookup_customer"
    assert result["issue_resolved"] is False


def test_agent_does_not_execute_old_handler_twice_when_function_call_succeeds():
    loop = FakeFunctionCallingLoop(
        {
            "status": "completed",
            "tool_results": [
                {
                    "tool_name": "lookup_transaction",
                    "arguments": {"transaction_id": "txn1001"},
                    "result": {
                        "ok": True,
                        "result": {
                            "found": True,
                            "transaction": {
                                "transaction_id": "txn1001",
                                "status": "approved",
                                "amount": 49.90,
                                "currency": "BRL",
                            },
                        },
                    },
                }
            ],
        }
    )
    agent = CustomerSupportAgent(loop=loop)
    calls = []

    def fake_execute(tool_name, arguments, *, context=None):
        calls.append((tool_name, arguments, context))
        return {
            "found": True,
            "transaction": {
                "transaction_id": arguments["transaction_id"],
                "status": "approved",
                "amount": 49.90,
                "currency": "BRL",
            },
        }

    agent.executor.execute = fake_execute

    result = agent.answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["function_call_status"] == "tool_call_success"
    assert calls == []


def test_agent_does_not_mark_resolution_when_function_calling_failed():
    loop = FakeFunctionCallingLoop(
        {
            "status": "completed",
            "tool_results": [
                {
                    "tool_name": "lookup_transaction",
                    "arguments": {"transaction_id": "txn1001"},
                    "result": {"ok": False, "error": "Tool execution failed."},
                }
            ],
        }
    )

    result = CustomerSupportAgent(loop=loop).answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["function_call_status"] == "invalid_result"
    assert result["issue_resolved"] is False
    assert "não posso confirmar" in result["response"].lower()


def test_agent_keeps_transaction_id_request_when_missing():
    loop = FakeFunctionCallingLoop({"status": "completed", "tool_results": []})
    result = CustomerSupportAgent(loop=loop).answer(
        "Minha transação foi recusada.",
        "cliente1988",
    )

    assert result["tool_used"] is None
    assert "txn" in result["response"].lower()
    assert result["awaiting_user_input"] is True


def test_fallback_transaction_query_keeps_cross_customer_ownership_blocked():
    loop = FakeFunctionCallingLoop(error=ConnectionError("ollama unavailable"))

    result = CustomerSupportAgent(loop=loop).answer(
        "Qual o status da transação txn2001?",
        "cliente1988",
    )

    assert result["function_call_status"] == "no_tool_calls"
    assert result["issue_resolved"] is False
    assert "não encontrei" in result["response"].lower()


def test_fallback_does_not_share_verified_facts_between_users():
    loop = FakeFunctionCallingLoop(error=ConnectionError("ollama unavailable"))
    agent = CustomerSupportAgent(loop=loop)

    first = agent.answer("Qual o status da transação txn1001?", "cliente1988")
    second = agent.answer("Qual o status da transação txn2001?", "cliente2001")

    assert first["function_call_status"] == "no_tool_calls"
    assert second["function_call_status"] == "no_tool_calls"
    assert first["verified_facts"]
    assert second["verified_facts"]
    assert all(fact["entity"] == "txn1001" for fact in first["verified_facts"])
    assert all(fact["entity"] == "txn2001" for fact in second["verified_facts"])
