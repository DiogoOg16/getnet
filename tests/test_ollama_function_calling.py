import copy
import json

from app.llm.ollama_function_calling import OllamaFunctionCallingLoop
from app.tools.registry import Tool, ToolRegistry


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({
            "messages": copy.deepcopy(messages),
            "tools": copy.deepcopy(tools),
        })
        if not self.responses:
            raise AssertionError("Fake client has no remaining responses.")
        return copy.deepcopy(self.responses.pop(0))


def _build_registry():
    registry = ToolRegistry()

    def lookup_customer(customer_id: str, user_id: str):
        return {"found": True, "customer_id": customer_id, "user_id": user_id}

    def lookup_transaction(transaction_id: str, user_id: str):
        return {"found": True, "transaction_id": transaction_id, "user_id": user_id}

    def lookup_settlement(user_id: str):
        return {"found": True, "customer_id": user_id, "records": ["r1"]}

    registry.register(
        Tool(
            name="lookup_customer",
            description="Consulta cliente autenticado.",
            parameters={
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
            trusted_context=("user_id",),
            handler=lookup_customer,
        )
    )
    registry.register(
        Tool(
            name="lookup_transaction",
            description="Consulta transação autenticada.",
            parameters={
                "type": "object",
                "properties": {"transaction_id": {"type": "string"}},
                "required": ["transaction_id"],
            },
            trusted_context=("user_id",),
            handler=lookup_transaction,
        )
    )
    registry.register(
        Tool(
            name="lookup_settlement",
            description="Consulta liquidação autenticada.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            trusted_context=("user_id",),
            handler=lookup_settlement,
        )
    )
    return registry


def test_loop_returns_final_response_without_tool_calls():
    client = FakeClient([
        {"message": {"role": "assistant", "content": "Resposta final"}},
    ])
    loop = OllamaFunctionCallingLoop(client, ToolRegistry(), max_iterations=3)

    result = loop.run([{"role": "user", "content": "Olá"}])

    assert result["status"] == "completed"
    assert result["final_response"] == "Resposta final"
    assert result["messages"][-1]["content"] == "Resposta final"


def test_loop_executes_single_tool_call():
    registry = _build_registry()
    client = FakeClient([
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "lookup_customer", "arguments": {"customer_id": "cliente-1"}},
                    }
                ],
            }
        },
        {"message": {"role": "assistant", "content": "Resposta após ferramenta"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Quem é meu cliente?"}], context={"user_id": "u-1"})

    assert result["status"] == "completed"
    assert result["final_response"] == "Resposta após ferramenta"
    assert result["tool_results"][0]["tool_name"] == "lookup_customer"
    assert result["tool_results"][0]["result"]["ok"] is True
    assert result["tool_results"][0]["result"]["result"]["customer_id"] == "cliente-1"
    assert result["messages"][-2]["role"] == "tool"
    assert result["messages"][-2]["tool_name"] == "lookup_customer"


def test_loop_executes_multiple_tool_calls_in_same_round():
    registry = _build_registry()
    client = FakeClient([
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_a", "function": {"name": "lookup_customer", "arguments": {"customer_id": "cliente-1"}}},
                    {"id": "call_b", "function": {"name": "lookup_transaction", "arguments": {"transaction_id": "txn-1"}}},
                ],
            }
        },
        {"message": {"role": "assistant", "content": "Resposta final"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Resumo"}], context={"user_id": "u-1"})

    assert result["status"] == "completed"
    assert len(result["tool_results"]) == 2
    assert {item["tool_name"] for item in result["tool_results"]} == {"lookup_customer", "lookup_transaction"}


def test_loop_handles_multiple_rounds_of_tool_calls():
    registry = _build_registry()
    client = FakeClient([
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "lookup_customer", "arguments": {"customer_id": "cliente-1"}}},
                ],
            }
        },
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_2", "function": {"name": "lookup_settlement", "arguments": {}}},
                ],
            }
        },
        {"message": {"role": "assistant", "content": "Concluído"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=5)

    result = loop.run([{"role": "user", "content": "Detalhes"}], context={"user_id": "u-1"})

    assert result["status"] == "completed"
    assert result["final_response"] == "Concluído"
    assert len(result["tool_results"]) == 2


def test_loop_handles_unknown_tool():
    registry = _build_registry()
    client = FakeClient([
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "missing_tool", "arguments": {}}},
                ],
            }
        },
        {"message": {"role": "assistant", "content": "Não consegui"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Diga algo"}], context={"user_id": "u-1"})

    assert result["status"] == "completed"
    assert result["tool_results"][0]["result"]["ok"] is False
    assert result["tool_results"][0]["result"]["error"] == "Tool not found."


def test_loop_handles_invalid_arguments():
    registry = _build_registry()
    client = FakeClient([
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "lookup_customer", "arguments": {}}},
                ],
            }
        },
        {"message": {"role": "assistant", "content": "Argumento inválido tratado"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Teste"}], context={"user_id": "u-1"})

    assert result["status"] == "completed"
    assert result["tool_results"][0]["result"]["ok"] is False
    assert result["tool_results"][0]["result"]["error"] == "Invalid tool arguments."


def test_loop_handles_execution_failure():
    registry = ToolRegistry()

    def failing_handler(**kwargs):
        raise RuntimeError("boom")

    registry.register(
        Tool(
            name="failing_tool",
            description="Ferramenta que falha.",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
            trusted_context=("user_id",),
            handler=failing_handler,
        )
    )
    client = FakeClient([
        {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "function": {"name": "failing_tool", "arguments": {"value": "ok"}}}]}} ,
        {"message": {"role": "assistant", "content": "Falha tratada"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Teste"}], context={"user_id": "u-1"})

    assert result["status"] == "completed"
    assert result["tool_results"][0]["result"]["ok"] is False
    assert result["tool_results"][0]["result"]["error"] == "Tool execution failed."


def test_loop_handles_malformed_arguments():
    registry = _build_registry()
    client = FakeClient([
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "lookup_customer", "arguments": '{"customer_id":'}},
                ],
            }
        },
        {"message": {"role": "assistant", "content": "Argumento malformado tratado"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Teste"}], context={"user_id": "u-1"})

    assert result["status"] == "completed"
    assert result["tool_results"][0]["result"]["ok"] is False
    assert result["tool_results"][0]["result"]["error"] == "Invalid tool arguments."


def test_loop_serializes_non_json_result():
    registry = ToolRegistry()

    class Unserializable:
        def __str__(self):
            return "custom-object"

    def handler(value: str, user_id: str):
        return {"payload": Unserializable(), "user_id": user_id}

    registry.register(
        Tool(
            name="returns_custom",
            description="Retorna valor não serializável nativo.",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
            trusted_context=("user_id",),
            handler=handler,
        )
    )
    client = FakeClient([
        {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "function": {"name": "returns_custom", "arguments": {"value": "x"}}}] }},
        {"message": {"role": "assistant", "content": "Final"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Teste"}], context={"user_id": "u-1"})

    assert result["status"] == "completed"
    payload_text = json.loads(result["messages"][-2]["content"])["result"]["payload"]
    assert "custom-object" in str(payload_text)


def test_loop_stops_after_max_iterations():
    registry = _build_registry()
    client = FakeClient([
        {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "function": {"name": "lookup_customer", "arguments": {"customer_id": "cliente-1"}}}] }},
        {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "call_2", "function": {"name": "lookup_customer", "arguments": {"customer_id": "cliente-2"}}}] }},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=2)

    result = loop.run([{"role": "user", "content": "Teste"}], context={"user_id": "u-1"})

    assert result["status"] == "max_iterations_exceeded"
    assert result["iterations"] == 2
    assert result["final_response"] is None


def test_loop_injects_backend_context_into_tool_execution():
    registry = _build_registry()
    recorded = {}

    def capture_customer(customer_id: str, user_id: str):
        recorded["user_id"] = user_id
        return {"ok": True, "customer_id": customer_id}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="lookup_customer",
            description="Consulta cliente autenticado.",
            parameters={"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]},
            trusted_context=("user_id",),
            handler=capture_customer,
        )
    )
    client = FakeClient([
        {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "function": {"name": "lookup_customer", "arguments": {"customer_id": "cliente-1"}}}] }},
        {"message": {"role": "assistant", "content": "Final"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Teste"}], context={"user_id": "backend-user"})

    assert result["status"] == "completed"
    assert recorded["user_id"] == "backend-user"


def test_loop_rejects_user_id_from_model_arguments():
    registry = _build_registry()
    client = FakeClient([
        {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "function": {"name": "lookup_customer", "arguments": {"customer_id": "cliente-1", "user_id": "evil-user"}}}] }},
        {"message": {"role": "assistant", "content": "Final"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Teste"}], context={"user_id": "safe-user"})

    assert result["status"] == "completed"
    assert result["tool_results"][0]["result"]["ok"] is False
    assert result["tool_results"][0]["result"]["error"] == "Invalid tool arguments."


def test_loop_preserves_assistant_and_tool_messages_in_history():
    registry = _build_registry()
    client = FakeClient([
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "lookup_customer", "arguments": {"customer_id": "cliente-1"}}},
                ],
            }
        },
        {"message": {"role": "assistant", "content": "Final"}},
    ])
    loop = OllamaFunctionCallingLoop(client, registry, max_iterations=3)

    result = loop.run([{"role": "user", "content": "Teste"}], context={"user_id": "u-1"})

    history = result["messages"]
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[1]["tool_calls"][0]["function"]["name"] == "lookup_customer"
    assert history[2]["role"] == "tool"
    assert history[2]["tool_name"] == "lookup_customer"
    assert history[3]["role"] == "assistant"
    assert history[3]["content"] == "Final"
