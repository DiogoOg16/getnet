from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


class ToolNotFoundError(KeyError):
    """Raised when a tool name is not present in the registry."""


class ToolValidationError(ValueError):
    """Raised when public tool arguments do not satisfy the registered schema."""


class ToolContextError(ValueError):
    """Raised when trusted backend context is missing or invalid."""


def normalize_tool_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("Tool name must be a string.")
    return name.strip().lower()


@dataclass(frozen=True)
class Tool:
    """Provider-independent representation of an application tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    trusted_context: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        normalized_name = normalize_tool_name(self.name)
        object.__setattr__(self, "name", normalized_name)

        if not normalized_name:
            raise ValueError("Tool name must be a non-empty string.")
        if not isinstance(self.description, str):
            raise TypeError("Tool description must be a string.")
        if not isinstance(self.parameters, dict):
            raise TypeError("Tool parameters must be a JSON-serializable dictionary.")
        if not callable(self.handler):
            raise TypeError("Tool handler must be callable.")

        normalized_context = tuple(normalize_tool_name(item) for item in self.trusted_context)
        object.__setattr__(self, "trusted_context", normalized_context)

        parameters = copy.deepcopy(self.parameters)
        if not isinstance(parameters.get("type"), str):
            parameters["type"] = "object"
        if "properties" not in parameters:
            parameters["properties"] = {}
        if not isinstance(parameters["properties"], dict):
            raise TypeError("Tool properties must be a dictionary.")
        if "required" not in parameters:
            parameters["required"] = []
        if not isinstance(parameters["required"], list):
            parameters["required"] = list(parameters["required"])

        try:
            Draft202012Validator.check_schema(parameters)
        except SchemaError as exc:
            raise ValueError(f"Invalid JSON Schema for tool '{normalized_name}': {exc.message}") from exc

        object.__setattr__(self, "parameters", parameters)

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": copy.deepcopy(self.parameters),
            "trusted_context": list(self.trusted_context),
        }

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": copy.deepcopy(self.parameters),
        }

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        return self.handler(*args, **kwargs)


class ToolRegistry:
    """Registry of locally available tools.

    This layer intentionally has no Ollama or provider dependencies. It is only a
    central place to describe and resolve Python handlers used by the application.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    @staticmethod
    def normalize_name(name: str) -> str:
        return normalize_tool_name(name)

    def register(self, tool: Tool) -> Tool:
        normalized_name = self.normalize_name(tool.name)
        if normalized_name in self._tools:
            raise ValueError(f"Tool '{normalized_name}' is already registered.")

        self._tools[normalized_name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        if not isinstance(name, str):
            return None
        return self._tools.get(self.normalize_name(name))

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def metadata_list(self) -> list[dict[str, Any]]:
        return [tool.metadata() for tool in self.list()]

    def to_json(self) -> str:
        return json.dumps(self.metadata_list(), ensure_ascii=False)

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None


class ToolExecutor:
    """Controlled execution boundary for trusted application context injection.

    This is intentionally not the LLM-provider integration layer. It prepares the
    contract that the future provider adapter will use to validate arguments and
    inject application-owned context before a Python handler runs.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("ToolExecutor requires a ToolRegistry instance.")
        self.registry = registry

    def _validate_arguments(self, tool: Tool, arguments: Any) -> None:
        if not isinstance(arguments, dict):
            raise ToolValidationError("Tool arguments must be a dictionary.")

        reserved = set(tool.trusted_context)
        supplied_reserved = reserved.intersection(arguments)
        if supplied_reserved:
            names = ", ".join(sorted(supplied_reserved))
            raise ToolValidationError(
                f"Arguments {names} are reserved for trusted backend context and cannot be provided by the model."
            )

        properties = tool.parameters.get("properties", {})
        extra = set(arguments) - set(properties)
        if extra:
            names = ", ".join(sorted(extra))
            raise ToolValidationError(f"Undeclared arguments for '{tool.name}': {names}.")

        validator = Draft202012Validator(tool.parameters)
        errors = sorted(validator.iter_errors(arguments), key=lambda error: list(error.absolute_path))
        if errors:
            error = errors[0]
            path = ".".join(str(part) for part in error.absolute_path)
            location = f" at '{path}'" if path else ""
            raise ToolValidationError(
                f"Invalid arguments for tool '{tool.name}'{location}: {error.message}"
            )

    def _validate_context(self, tool: Tool, context: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(context, dict):
            raise ToolContextError("Tool context must be a dictionary provided by the backend.")

        trusted_context: dict[str, Any] = {}
        for field_name in tool.trusted_context:
            if field_name not in context:
                raise ToolContextError(f"Missing trusted context '{field_name}' for tool '{tool.name}'.")
            value = context[field_name]
            if value is None:
                raise ToolContextError(f"Trusted context '{field_name}' cannot be None for tool '{tool.name}'.")
            if isinstance(value, str) and value.strip() == "":
                raise ToolContextError(f"Trusted context '{field_name}' cannot be empty for tool '{tool.name}'.")
            trusted_context[field_name] = value

        return trusted_context

    def execute(self, tool_name: str, arguments: dict[str, Any], *, context: dict[str, Any] | None = None) -> Any:
        tool = self.registry.get(tool_name)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{tool_name}' is not registered.")

        if arguments is None:
            raise ToolValidationError("Tool arguments must be a dictionary.")

        self._validate_arguments(tool, copy.deepcopy(arguments))
        trusted_context = self._validate_context(tool, context)

        payload = dict(copy.deepcopy(arguments))
        payload.update(trusted_context)
        return tool.handler(**payload)


tool_registry = ToolRegistry()
