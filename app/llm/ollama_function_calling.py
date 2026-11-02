from __future__ import annotations

import copy
import json
from typing import Any

from app.llm.ollama_client import OllamaClient
from app.llm.ollama_tools import registry_to_ollama_tools
from app.tools.registry import (
    ToolContextError,
    ToolExecutor,
    ToolNotFoundError,
    ToolRegistry,
    ToolValidationError,
    tool_registry,
)


class FunctionCallingLoopError(RuntimeError):
    """Raised when the function-calling loop fails at the orchestration level."""


class MalformedToolCallError(ValueError):
    """Raised when a tool call does not match the expected Ollama structure."""


def _json_default(value: Any) -> str:
    return str(value)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


class OllamaFunctionCallingLoop:
    """Execute an Ollama tool-calling loop while keeping the conversation history valid."""

    def __init__(
        self,
        client: OllamaClient,
        registry: ToolRegistry | None = None,
        *,
        executor: ToolExecutor | None = None,
        max_iterations: int = 5,
    ) -> None:
        if not hasattr(client, "chat") or not callable(client.chat):
            raise TypeError("client must provide a chat(messages, tools=None) method.")
        if registry is None:
            registry = tool_registry
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry instance or None.")
        self.client = client
        self.registry = registry
        self.executor = executor or ToolExecutor(registry)
        if not isinstance(max_iterations, int):
            raise TypeError("max_iterations must be an integer.")
        if max_iterations <= 0:
            raise ValueError("max_iterations must be greater than zero.")
        self.max_iterations = max_iterations

    @staticmethod
    def _safe_tool_error(error: Exception) -> str:
        if isinstance(error, ToolNotFoundError):
            return "Tool not found."
        if isinstance(error, ToolValidationError):
            return "Invalid tool arguments."
        if isinstance(error, ToolContextError):
            return "Missing trusted backend context."
        return "Tool execution failed."

    @staticmethod
    def _coerce_tool_arguments(raw_arguments: Any) -> Any:
        if raw_arguments is None:
            return {}
        if isinstance(raw_arguments, dict):
            return copy.deepcopy(raw_arguments)
        if isinstance(raw_arguments, str):
            try:
                parsed = json.loads(raw_arguments)
            except json.JSONDecodeError:
                return raw_arguments
            if isinstance(parsed, dict):
                return parsed
            return raw_arguments
        return raw_arguments

    @staticmethod
    def _normalize_tool_call(call: Any, *, index: int) -> dict[str, Any]:
        if not isinstance(call, dict):
            raise MalformedToolCallError(f"Tool call at index {index} must be a dictionary.")

        function = call.get("function")
        if function is None:
            if "name" in call and "arguments" in call:
                function = {"name": call["name"], "arguments": call["arguments"]}
            else:
                raise MalformedToolCallError(f"Tool call at index {index} is missing function metadata.")
        if not isinstance(function, dict):
            raise MalformedToolCallError(f"Tool call at index {index} has an invalid function payload.")

        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise MalformedToolCallError(f"Tool call at index {index} is missing a valid function name.")

        arguments = OllamaFunctionCallingLoop._coerce_tool_arguments(function.get("arguments", {}))
        return {
            "id": call.get("id", f"call_{index}"),
            "name": name,
            "arguments": arguments,
        }

    def _extract_tool_calls(self, response: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        if not isinstance(response, dict):
            return [], ["Response payload must be a dictionary."]

        message = response.get("message")
        if message is None:
            return [], []
        if not isinstance(message, dict):
            return [], ["Response message must be a dictionary."]

        raw_calls = message.get("tool_calls")
        if raw_calls is None:
            return [], []
        if not isinstance(raw_calls, list):
            return [], ["Message tool_calls must be a list."]

        valid_calls: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, call in enumerate(raw_calls):
            try:
                valid_calls.append(self._normalize_tool_call(call, index=index))
            except MalformedToolCallError as exc:
                errors.append(str(exc))

        return valid_calls, errors

    def run(self, messages: list[dict[str, Any]], *, context: dict[str, Any] | None = None, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not isinstance(messages, list):
            raise TypeError("messages must be a list of message dictionaries.")

        history = [copy.deepcopy(message) for message in messages]
        tool_payload = list(tools) if tools is not None else registry_to_ollama_tools(self.registry)
        allowed_tool_names = None
        if tools is not None:
            allowed_tool_names = {
                str(tool["function"]["name"])
                for tool in tool_payload
                if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
            }

        executed_tools: list[dict[str, Any]] = []
        executed_names: set[str] = set()
        malformed_tool_calls: list[str] = []

        for iteration in range(1, self.max_iterations + 1):
            response = self.client.chat(history, tools=tool_payload)
            message = response.get("message") if isinstance(response, dict) else None

            if not isinstance(message, dict):
                raise FunctionCallingLoopError("Ollama response is missing a valid message dictionary.")

            tool_calls, malformed = self._extract_tool_calls(response)
            malformed_tool_calls.extend(malformed)
            if not tool_calls:
                assistant_message = copy.deepcopy(message)
                if assistant_message not in history:
                    history.append(assistant_message)
                return {
                    "status": "completed",
                    "iterations": iteration,
                    "messages": history,
                    "final_response": assistant_message.get("content", ""),
                    "tool_results": executed_tools,
                    "malformed_tool_calls": malformed_tool_calls,
                    "last_response": response,
                }

            history.append(copy.deepcopy(message))

            round_results: list[dict[str, Any]] = []
            for call in tool_calls:
                tool_name = call["name"]
                arguments = copy.deepcopy(call["arguments"])
                tool_id = call.get("id")

                if allowed_tool_names is not None and tool_name not in allowed_tool_names:
                    serialized = {"ok": False, "error": "Tool not allowed for this intent."}
                elif tool_name in executed_names:
                    serialized = {"ok": False, "error": "Tool already executed in this turn."}
                else:
                    try:
                        result_payload = self.executor.execute(tool_name, arguments, context=context)
                        serialized = {"ok": True, "result": _json_safe(result_payload)}
                        executed_names.add(tool_name)
                    except Exception as exc:  # pragma: no cover - path validated below
                        serialized = {"ok": False, "error": self._safe_tool_error(exc)}
                        executed_names.add(tool_name)

                tool_message = {
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": json.dumps(serialized, ensure_ascii=False, default=_json_default),
                }
                if tool_id is not None:
                    tool_message["tool_call_id"] = tool_id
                history.append(tool_message)
                round_results.append(
                    {
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "result": serialized,
                    }
                )
            executed_tools.extend(round_results)

            if iteration >= self.max_iterations:
                return {
                    "status": "max_iterations_exceeded",
                    "iterations": iteration,
                    "messages": history,
                    "final_response": None,
                    "tool_results": executed_tools,
                    "malformed_tool_calls": malformed_tool_calls,
                    "last_response": response,
                }

        return {
            "status": "completed",
            "iterations": self.max_iterations,
            "messages": history,
            "final_response": None,
            "tool_results": executed_tools,
            "malformed_tool_calls": malformed_tool_calls,
            "last_response": response,
        }


__all__ = ["OllamaFunctionCallingLoop", "FunctionCallingLoopError", "MalformedToolCallError"]
