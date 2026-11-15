"""Latência por chamada dentro de cada etapa do orquestrador.

O orquestrador abre um coletor por etapa (`collect_calls`). As chamadas ao LLM,
às ferramentas, à recuperação e aos serviços externos se registram com
`record_call`, e o resultado entra no `trace` da resposta:

    {"kind": "llm", "name": "qwen2.5:7b", "duration_ms": 12345, "status": "ok"}

O coletor usa `contextvars`: cada requisição (e cada thread do servidor) tem o
seu, e o código chamado não precisa receber nada por parâmetro. Fora de um
coletor (testes de unidade, scripts), `record_call` não registra nada.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_current_calls: ContextVar[list[dict] | None] = ContextVar("getnet_step_calls", default=None)


@contextmanager
def collect_calls() -> Iterator[list[dict]]:
    """Coleta as chamadas feitas dentro do bloco, na ordem em que terminam."""
    calls: list[dict] = []
    token = _current_calls.set(calls)
    try:
        yield calls
    finally:
        _current_calls.reset(token)


@contextmanager
def record_call(kind: str, name: str) -> Iterator[None]:
    """Mede uma chamada; `status` é "error" se ela lançar exceção."""
    calls = _current_calls.get()
    started = time.perf_counter()
    status = "ok"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        if calls is not None:
            calls.append({
                "kind": kind,
                "name": name,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "status": status,
            })
