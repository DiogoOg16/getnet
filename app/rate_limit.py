"""Limite simples de requisições por usuário autenticado (janela deslizante em memória).

Adequado ao protótipo com um único worker, como o `Dockerfile`: o estado fica no
processo, não é compartilhado entre workers e some quando o processo reinicia.
"""

import math
import os
import threading
import time
from collections import defaultdict, deque

DEFAULT_REQUESTS_PER_MINUTE = 30
WINDOW_SECONDS = 60.0


def requests_per_minute() -> int:
    """Limite configurado em GETNET_RATE_LIMIT_PER_MINUTE; 0 desliga o limite."""
    raw = os.getenv("GETNET_RATE_LIMIT_PER_MINUTE", "").strip()
    if not raw:
        return DEFAULT_REQUESTS_PER_MINUTE
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError("GETNET_RATE_LIMIT_PER_MINUTE deve ser um inteiro >= 0.") from None
    if value < 0:
        raise RuntimeError("GETNET_RATE_LIMIT_PER_MINUTE deve ser um inteiro >= 0.")
    return value


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> float | None:
        """Registra a requisição e devolve None, ou os segundos até liberar se o limite foi atingido.

        Requisição recusada não conta na janela.
        """
        if limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return max(WINDOW_SECONDS - (now - hits[0]), 0.0)
            hits.append(now)
            return None

    @staticmethod
    def retry_after_header(seconds: float) -> str:
        return str(max(1, math.ceil(seconds)))

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
