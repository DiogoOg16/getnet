import copy
import json

import pytest

from app.tools.customer_tools import (
    lookup_customer,
    lookup_settlement,
    lookup_transaction,
    register_customer_tools,
)
from app.tools.registry import (
    Tool,
    ToolContextError,
    ToolExecutor,
    ToolNotFoundError,
    ToolRegistry,
    ToolValidationError,
    tool_registry,
)

register_customer_tools(tool_registry)


def test_fresh_registry_is_empty_before_explicit_initialization():
    registry = ToolRegistry()

    assert registry.list() == []


def test_registry_registers_customer_tools():
    names = {tool.name for tool in tool_registry.list()}

    assert names == {"lookup_customer", "lookup_transaction", "lookup_settlement"}


def test_register_customer_tools_is_idempotent():
    registry = ToolRegistry()

    register_customer_tools(registry)
    register_customer_tools(registry)

    names = {tool.name for tool in registry.list()}
    assert names == {"lookup_customer", "lookup_transaction", "lookup_settlement"}
    assert len(registry.list()) == 3


def test_registry_gets_tool_by_name():
    tool = tool_registry.get("lookup_transaction")

    assert tool is not None
    assert tool.name == "lookup_transaction"
    assert tool.handler is lookup_transaction
    assert tool.parameters["properties"] == {"transaction_id": {"type": "string", "description": "Identificador da transação."}}
    assert tool.parameters["required"] == ["transaction_id"]
    assert tool.trusted_context == ("user_id",)


def test_registry_lists_registered_tools():
    tools = tool_registry.list()

    assert len(tools) >= 3
    assert {tool.name for tool in tools} >= {"lookup_customer", "lookup_transaction", "lookup_settlement"}


def test_registry_rejects_duplicate_names_case_insensitive():
    registry = ToolRegistry()
    registry.register(Tool("lookup_customer", "first", {"type": "object", "properties": {}}, lookup_customer))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(Tool("LOOKUP_CUSTOMER", "duplicate", {"type": "object", "properties": {}}, lookup_customer))


def test_registry_returns_none_for_missing_tool():
    assert tool_registry.get("nonexistent_tool") is None


def test_tool_metadata_is_json_serializable_and_isolated_from_registry():
    tool = tool_registry.get("lookup_customer")
    assert tool is not None

    payload = tool.metadata()
    json.dumps(payload)

    payload["description"] = "mutated"
    payload["parameters"]["properties"]["user_id"] = {"type": "string"}

    assert tool.metadata()["description"] != "mutated"
    assert "user_id" not in tool.metadata()["parameters"]["properties"]


def test_tool_executor_injects_trusted_context_before_invocation():
    executor = ToolExecutor(tool_registry)

    result = executor.execute("lookup_customer", {}, context={"user_id": "cliente1988"})

    assert result["found"] is True
    assert result["customer"]["customer_id"] == "cliente1988"


def test_tool_executor_rejects_unknown_tool():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(KeyError, match="not registered"):
        executor.execute("missing_tool", {})


def test_tool_registry_to_json_has_defined_behavior():
    payload = json.loads(tool_registry.to_json())

    assert isinstance(payload, list)
    assert {item["name"] for item in payload} >= {"lookup_customer", "lookup_transaction", "lookup_settlement"}
    assert all("trusted_context" in item for item in payload)


def test_registry_name_normalization_is_consistent():
    assert tool_registry.get("LOOKUP_CUSTOMER") is tool_registry.get("lookup_customer")
    assert tool_registry.get(" LOOKUP_TRANSACTION ") is tool_registry.get("lookup_transaction")


def test_tool_executor_requires_context_for_user_id():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolContextError, match="user_id"):
        executor.execute("lookup_customer", {}, context={})


def test_tool_executor_rejects_missing_user_id_context():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolContextError, match="user_id"):
        executor.execute("lookup_customer", {}, context={"customer_id": "cliente1988"})


def test_tool_executor_rejects_none_user_id_context():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolContextError, match="user_id"):
        executor.execute("lookup_customer", {}, context={"user_id": None})


def test_tool_executor_rejects_empty_user_id_context():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolContextError, match="user_id"):
        executor.execute("lookup_customer", {}, context={"user_id": "   "})


def test_tool_executor_rejects_public_user_id_argument():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolValidationError, match="reserved|trusted backend context"):
        executor.execute("lookup_customer", {"user_id": "cliente1988"}, context={"user_id": "cliente1988"})


def test_tool_executor_requires_transaction_id_argument():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolValidationError, match="transaction_id"):
        executor.execute("lookup_transaction", {}, context={"user_id": "cliente1988"})


def test_tool_executor_rejects_undeclared_argument():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolValidationError, match="Undeclared|undeclared|additional|not declared"):
        executor.execute("lookup_transaction", {"transaction_id": "txn1001", "extra": "value"}, context={"user_id": "cliente1988"})


def test_tool_executor_rejects_wrong_transaction_id_type():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolValidationError, match="transaction_id|type"):
        executor.execute("lookup_transaction", {"transaction_id": 123}, context={"user_id": "cliente1988"})


def test_tool_executor_requires_dict_arguments():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolValidationError, match="dictionary|dict"):
        executor.execute("lookup_customer", ["not", "dict"], context={"user_id": "cliente1988"})


def test_tool_executor_does_not_call_handler_on_validation_error():
    called = {"value": False}

    def fake_handler(**kwargs):
        called["value"] = True
        return {"ok": True}

    tool = Tool(
        name="lookup_transaction",
        description="stub",
        parameters={
            "type": "object",
            "properties": {"transaction_id": {"type": "string"}},
            "required": ["transaction_id"],
        },
        trusted_context=("user_id",),
        handler=fake_handler,
    )
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolValidationError):
        executor.execute("lookup_transaction", {"transaction_id": 123}, context={"user_id": "cliente1988"})

    assert called["value"] is False


def test_tool_executor_does_not_call_handler_on_invalid_context():
    called = {"value": False}

    def fake_handler(**kwargs):
        called["value"] = True
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="test_tool",
            description="Test tool",
            parameters={"type": "object", "properties": {}, "required": []},
            trusted_context=("user_id",),
            handler=fake_handler,
        )
    )
    executor = ToolExecutor(registry)

    with pytest.raises(ToolContextError):
        executor.execute("test_tool", {}, context={})

    assert called["value"] is False


def test_tool_executor_executes_valid_tools():
    executor = ToolExecutor(tool_registry)

    customer = executor.execute("lookup_customer", {}, context={"user_id": "cliente1988"})
    transaction = executor.execute("lookup_transaction", {"transaction_id": "txn1001"}, context={"user_id": "cliente1988"})
    settlement = executor.execute("lookup_settlement", {}, context={"user_id": "cliente1988"})

    assert customer["found"] is True
    assert transaction["found"] is True
    assert settlement["found"] is True


def test_tool_executor_rejects_unknown_tool():
    executor = ToolExecutor(tool_registry)

    with pytest.raises(ToolNotFoundError, match="not registered"):
        executor.execute("missing_tool", {})
