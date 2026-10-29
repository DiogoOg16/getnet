"""Demo authentication for the Getnet support API."""

import hmac
import json
import os

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials


def _load_auth_tokens() -> dict[str, str]:
    """Load token-to-user mappings from the environment."""
    raw_tokens = os.getenv("GETNET_DEMO_AUTH_TOKENS", "")

    if not raw_tokens:
        return {}

    try:
        tokens = json.loads(raw_tokens)
    except json.JSONDecodeError:
        raise RuntimeError(
            "GETNET_DEMO_AUTH_TOKENS must contain a valid JSON object."
        ) from None

    if not isinstance(tokens, dict) or not all(
        isinstance(token, str)
        and token
        and isinstance(user_id, str)
        and user_id
        for token, user_id in tokens.items()
    ):
        raise RuntimeError(
            "GETNET_DEMO_AUTH_TOKENS must map non-empty tokens to user IDs."
        )

    return tokens


def authenticate_user(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    """Validate a Bearer token and return its associated user ID."""
    try:
        tokens = _load_auth_tokens()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuração de autenticação indisponível.",
        ) from exc

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais ausentes ou inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    authenticated_user_id = None

    for token, user_id in tokens.items():
        if hmac.compare_digest(credentials.credentials, token):
            authenticated_user_id = user_id

    if authenticated_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais ausentes ou inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return authenticated_user_id
