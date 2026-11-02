import json
import os

import pytest

from app.llm.ollama_client import OllamaClient
from app.llm.ollama_function_calling import OllamaFunctionCallingLoop
from app.tools.registry import Tool, ToolExecutor, ToolRegistry


@pytest.mark.network
def test_ollama_real_function_calling_loop_with_tool_executor():
    if os.getenv("RUN_OLLAMA_INTEGRATION") != "1":
        pytest.skip("Set RUN_OLLAMA_INTEGRATION=1 to execute the real Ollama integration test.")

    class RecordingOllamaClient(OllamaClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.chat_calls: list[list[dict]] = []

        def chat(self, messages, tools=None):
            self.chat_calls.append([dict(message) for message in messages])
            return super().chat(messages, tools=tools)

    def echo_number(value: int, user_id: str) -> dict:
        return {"ok": True, "echo": value, "user_id": user_id}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo_number",
            description="Echoes a validated integer back to the model.",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
            trusted_context=("user_id",),
            handler=echo_number,
        )
    )

    client = RecordingOllamaClient()
    loop = OllamaFunctionCallingLoop(
        client,
        registry,
        executor=ToolExecutor(registry),
        max_iterations=3,
    )

    prompt = (
        "Use the tool echo_number exactly once with value 7. "
        "Return the tool result in a brief final answer."
    )
    result = loop.run(
        [{"role": "user", "content": prompt}],
        context={"user_id": "user-42"},
    )

    assert result["status"] == "completed"
    assert result["iterations"] >= 2
    assert result["iterations"] <= 3
    assert len(result["tool_results"]) == 1

    tool_result = result["tool_results"][0]
    assert tool_result["tool_name"] == "echo_number"
    assert tool_result["arguments"] == {"value": 7}
    assert tool_result["result"]["ok"] is True
    assert tool_result["result"]["result"]["echo"] == 7
    assert tool_result["result"]["result"]["user_id"] == "user-42"

    history = result["messages"]
    assert history[-1]["role"] == "assistant"
    assert history[-2]["role"] == "tool"
    assert json.loads(history[-2]["content"])["result"]["echo"] == 7

    assert len(client.chat_calls) >= 2
    second_call_history = client.chat_calls[1]
    assert any(
        message.get("role") == "assistant" and "tool_calls" in message
        for message in second_call_history
    )
    assert any(
        message.get("role") == "tool"
        and message.get("tool_name") == "echo_number"
        and "echo" in json.loads(message.get("content", "{}"))["result"]
        for message in second_call_history
    )
    assert "tool_calls" in history[1]

    final_response = result["final_response"] or ""
    assert final_response.strip()
    assert "7" in final_response or "echo" in final_response.lower()
