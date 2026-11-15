"""Registro de exceções com stack trace e sem dados pessoais (REL-02).

Exceções capturadas para devolver uma resposta segura ao usuário não podem
sumir dos logs: o operador precisa do tipo e do stack trace para diagnosticar.
A mensagem de uma exceção pode carregar texto do usuário, então o texto
formatado passa por `mask_sensitive` antes de ser registrado.
"""

from __future__ import annotations

import logging
import traceback

from app.privacy import mask_sensitive


def log_exception(
    logger: logging.Logger,
    event: str,
    exc: BaseException,
    *,
    level: int = logging.ERROR,
    **fields: object,
) -> None:
    """Registra `event` com os campos, o tipo da exceção e o stack trace mascarado."""
    context = " ".join(f"{key}={value}" for key, value in fields.items())
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
    logger.log(
        level,
        "%s %s error_type=%s\n%s",
        event,
        context,
        type(exc).__name__,
        mask_sensitive(formatted),
    )
