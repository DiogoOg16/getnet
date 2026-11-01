from __future__ import annotations

import os
from typing import Any

import requests


class OllamaClientError(RuntimeError):
    """Base exception for Ollama client failures."""


class OllamaHTTPError(OllamaClientError):
    """Raised when the remote Ollama API responds with an error status."""


class OllamaTimeoutError(OllamaClientError):
    """Raised when the Ollama request exceeds the configured timeout."""


class OllamaConnectionError(OllamaClientError):
    """Raised when the Ollama server cannot be reached."""


class OllamaRequestError(OllamaClientError):
    """Raised when a transport-level request exception occurs outside the specific timeout/connection cases."""


class OllamaResponseFormatError(OllamaClientError, ValueError):
    """Raised when the Ollama response payload does not match the expected shape."""


class OllamaClient:
    """Thin HTTP client for the local Ollama chat API."""

    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: int = 60) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.timeout = timeout

    def _payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": messages,
        }
        if tools is not None:
            payload["tools"] = tools
        return payload

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not isinstance(messages, list):
            raise TypeError("messages must be a list of message dictionaries.")

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=self._payload(messages, tools),
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise OllamaTimeoutError(f"Ollama request timed out after {self.timeout} seconds.") from exc
        except requests.exceptions.SSLError as exc:
            raise OllamaRequestError(f"Ollama transport request failed: {exc}.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise OllamaConnectionError(f"Could not connect to Ollama at {self.base_url}.") from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaRequestError(f"Ollama transport request failed: {exc}.") from exc

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise OllamaHTTPError(f"Ollama HTTP error: {response.status_code} {response.reason}.") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaResponseFormatError("Ollama returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise OllamaResponseFormatError("Ollama returned an unexpected response payload.")

        return data

    @staticmethod
    def parse_message_content(response: dict[str, Any]) -> str:
        if not isinstance(response, dict):
            raise OllamaResponseFormatError("Ollama response payload must be a dictionary.")

        message = response.get("message")
        if message is None:
            raise OllamaResponseFormatError("Ollama response is missing 'message'.")
        if not isinstance(message, dict):
            raise OllamaResponseFormatError("Ollama response 'message' must be a dictionary.")

        content = message.get("content")
        if content is None:
            raise OllamaResponseFormatError("Ollama response is missing 'message.content'.")
        if not isinstance(content, str):
            raise OllamaResponseFormatError("Ollama response 'message.content' must be a string.")

        return content.strip()
