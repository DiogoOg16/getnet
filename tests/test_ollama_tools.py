import copy

from app.llm.ollama_tools import registry_to_ollama_tools, tool_to_ollama_tool
from app.tools.customer_tools import (
    lookup_customer,
    lookup_settlement,
    lookup_transaction,
)
from app.tools.registry import Tool, ToolRegistry, tool_registry


def _tool_payload(payload, name):
    return next(item for item in payload if item.get("function", {}).get("name") == name)


def test_converter_handles_lookup_customer():
    payload = registry_to_ollama_tools()
    converted = _tool_payload(payload, "lookup_customer")

    assert converted["type"] == "function"
    assert converted["function"]["name"] == "lookup_customer"
    assert converted["function"]["description"] == (
        "Recupera um cliente pelo ID do usuário autenticado."
    )
    assert converted["function"]["parameters"] == {
        "type": "object",
        "properties": {},
        "required": [],
    }


def test_converter_handles_lookup_transaction():
    payload = registry_to_ollama_tools()
    converted = _tool_payload(payload, "lookup_transaction")
    tool = tool_registry.get("lookup_transaction")

    assert converted["type"] == "function"
    assert converted["function"]["name"] == tool.name
    assert converted["function"]["description"] == tool.description
    assert converted["function"]["parameters"] == tool.parameters


def test_converter_handles_lookup_settlement():
    payload = registry_to_ollama_tools()
    converted = _tool_payload(payload, "lookup_settlement")
    tool = tool_registry.get("lookup_settlement")

    assert converted["function"]["name"] == tool.name
    assert converted["function"]["description"] == tool.description
    assert converted["function"]["parameters"] == tool.parameters


def test_converter_preserves_json_schema_and_excludes_backend_fields():
    payload = registry_to_ollama_tools()
    converted_transaction = _tool_payload(payload, "lookup_transaction")

    assert converted_transaction["function"]["parameters"] == {
        "type": "object",
        "properties": {
            "transaction_id": {
                "type": "string",
                "description": "Identificador da transação.",
            }
        },
        "required": ["transaction_id"],
    }
    assert "user_id" not in converted_transaction["function"]["parameters"].get("properties", {})
    assert "user_id" not in converted_transaction["function"]["parameters"].get("required", [])

    converted_customer = _tool_payload(payload, "lookup_customer")
    assert "user_id" not in converted_customer["function"]["parameters"].get("properties", {})
    assert "user_id" not in converted_customer["function"]["parameters"].get("required", [])


def test_tool_to_ollama_tool_uses_trusted_context_directly():
    called = {"value": False}

    def fake_handler(**kwargs):
        called["value"] = True
        return {"ok": True}

    tool = Tool(
        name="lookup_customer_profile",
        description="Recupera o perfil do cliente autenticado.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "tenant_id": {"type": "string"},
            },
            "required": ["customer_id", "tenant_id"],
            "additionalProperties": False,
        },
        trusted_context=("tenant_id", "region"),
        handler=fake_handler,
    )

    converted = tool_to_ollama_tool(tool)

    assert converted["type"] == "function"
    assert converted["function"]["name"] == "lookup_customer_profile"
    assert "tenant_id" not in converted["function"]["parameters"]["properties"]
    assert "region" not in converted["function"]["parameters"]["properties"]
    assert converted["function"]["parameters"]["required"] == ["customer_id"]
    assert converted["function"]["parameters"]["additionalProperties"] is False
    assert called["value"] is False


def test_converter_removes_reserved_fields_from_nested_schemas():
    registry = ToolRegistry()

    def fake_handler(**kwargs):
        return {"ok": True}

    registry.register(
        Tool(
            name="nested_lookup",
            description="Lookup aninhado com contexto e payload complexo.",
            parameters={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "details": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "string"},
                            "customer_id": {"type": "string"},
                            "meta": {
                                "type": "object",
                                "properties": {
                                    "user_id": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                                "required": ["user_id", "status"],
                            },
                        },
                        "required": ["user_id", "customer_id"],
                    },
                },
                "required": ["account_id", "details"],
                "additionalProperties": True,
            },
            trusted_context=("user_id", "tenant_id"),
            handler=fake_handler,
        )
    )

    converted = registry_to_ollama_tools(registry)[0]
    details = converted["function"]["parameters"]["properties"]["details"]

    assert "user_id" not in converted["function"]["parameters"]["properties"]
    assert "user_id" not in details["properties"]
    assert "tenant_id" not in converted["function"]["parameters"]["properties"]
    assert "status" in details["properties"]["meta"]["properties"]
    assert "user_id" not in details["properties"]["meta"]["required"]
    assert converted["function"]["parameters"]["additionalProperties"] is True


def test_converter_preserves_non_reserved_schema_elements():
    tool = Tool(
        name="advanced_tool",
        description="Tool complexa com schema avançado.",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "account_id": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de itens.",
                },
            },
            "required": ["user_id", "account_id"],
            "title": "AdvancedTool",
            "additionalProperties": False,
            "description": "Schema avançado",
        },
        trusted_context=("user_id",),
        handler=lambda **kwargs: {"ok": True},
    )

    converted = tool_to_ollama_tool(tool)
    parameters = converted["function"]["parameters"]

    assert parameters["title"] == "AdvancedTool"
    assert parameters["description"] == "Schema avançado"
    assert parameters["additionalProperties"] is False
    assert parameters["properties"]["account_id"] == {"type": "string"}
    assert parameters["properties"]["items"]["items"] == {"type": "string"}
    assert parameters["required"] == ["account_id"]


def test_converter_does_not_mutate_registry():
    before = [copy.deepcopy(tool.public_schema()) for tool in tool_registry.list()]

    _ = registry_to_ollama_tools()

    after = [copy.deepcopy(tool.public_schema()) for tool in tool_registry.list()]
    assert after == before
    assert tool_registry.get("lookup_customer").handler is lookup_customer
    assert tool_registry.get("lookup_transaction").handler is lookup_transaction
    assert tool_registry.get("lookup_settlement").handler is lookup_settlement


def test_converter_returns_empty_list_for_empty_registry():
    registry = ToolRegistry()

    assert registry_to_ollama_tools(registry) == []


def test_converter_does_not_execute_handlers():
    called = {"value": False}

    def fake_handler(**kwargs):
        called["value"] = True
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="test_without_execution",
            description="Tool que não deve ser executada na conversão.",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            trusted_context=("user_id",),
            handler=fake_handler,
        )
    )

    converted = registry_to_ollama_tools(registry)

    assert len(converted) == 1
    assert converted[0]["function"]["name"] == "test_without_execution"
    assert called["value"] is False
