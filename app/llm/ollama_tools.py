from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.tools.registry import Tool, ToolRegistry, tool_registry

_RESERVED_BACKEND_FIELDS = {"user_id"}


def _sanitize_parameters(parameters: dict[str, Any], reserved_fields: set[str]) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        return deepcopy(parameters)

    reserved = set(reserved_fields)
    sanitized: dict[str, Any] = {}

    for key, value in parameters.items():
        if key == "properties" and isinstance(value, dict):
            sanitized[key] = {
                name: _sanitize_parameters(prop_schema, reserved)
                for name, prop_schema in value.items()
                if name not in reserved
            }
            continue

        if key == "required" and isinstance(value, list):
            sanitized[key] = [item for item in value if item not in reserved]
            continue

        if key in {"allOf", "anyOf", "oneOf"} and isinstance(value, list):
            sanitized[key] = [_sanitize_parameters(item, reserved) for item in value]
            continue

        if key in {"items", "contains", "not", "additionalProperties", "propertyNames", "if", "then", "else"}:
            sanitized[key] = _sanitize_parameters(value, reserved)
            continue

        if key in {"definitions", "$defs", "patternProperties"} and isinstance(value, dict):
            sanitized[key] = {
                name: _sanitize_parameters(sub_schema, reserved)
                for name, sub_schema in value.items()
            }
            continue

        if key == "dependencies" and isinstance(value, dict):
            sanitized[key] = {
                dependency_name: _sanitize_parameters(dependency_value, reserved)
                for dependency_name, dependency_value in value.items()
                if dependency_name not in reserved
            }
            continue

        if isinstance(value, dict):
            sanitized[key] = _sanitize_parameters(value, reserved)
            continue

        if isinstance(value, list):
            sanitized[key] = [_sanitize_parameters(item, reserved) for item in value]
            continue

        sanitized[key] = deepcopy(value)

    return sanitized


def tool_to_ollama_tool(tool: Tool, *, reserved_fields: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(tool, Tool):
        raise TypeError("tool must be an instance of Tool.")

    reserved = set(_RESERVED_BACKEND_FIELDS)
    reserved.update(getattr(tool, "trusted_context", ()))
    if reserved_fields:
        reserved.update(reserved_fields)

    public_schema = deepcopy(tool.public_schema())
    parameters = _sanitize_parameters(public_schema["parameters"], reserved)

    return {
        "type": "function",
        "function": {
            "name": public_schema["name"],
            "description": public_schema["description"],
            "parameters": parameters,
        },
    }


def registry_to_ollama_tools(registry: ToolRegistry | None = None) -> list[dict[str, Any]]:
    registry_instance = registry if registry is not None else tool_registry
    if not isinstance(registry_instance, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry instance or None.")

    reserved_fields = set(_RESERVED_BACKEND_FIELDS)
    for tool in registry_instance.list():
        reserved_fields.update(getattr(tool, "trusted_context", ()))

    return [
        tool_to_ollama_tool(tool, reserved_fields=reserved_fields)
        for tool in registry_instance.list()
    ]


__all__ = [
    "tool_to_ollama_tool",
    "registry_to_ollama_tools",
]
