"""Pre-flight de dependencias para el run en vivo del listener.

Comprueba (sin efectos) que estén disponibles Redis (estado del orquestador)
y el endpoint del LLM local. Reporta OK / NO DISPONIBLE por cada uno.
"""

from __future__ import annotations

import socket
from urllib.parse import urlparse

from src.core.config import get_settings


def _check(host: str, port: int, timeout: float = 1.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def main() -> int:
    s = get_settings()

    redis_url = urlparse(s.redis.url)
    redis_host = redis_url.hostname or "127.0.0.1"
    redis_port = redis_url.port or 6379

    llm_url = urlparse(s.local_llm_endpoint)
    llm_host = llm_url.hostname or "127.0.0.1"
    llm_port = llm_url.port or (443 if llm_url.scheme == "https" else 80)

    checks = [
        (f"Redis ({redis_host}:{redis_port})", redis_host, redis_port),
        (f"LLM local ({llm_host}:{llm_port})", llm_host, llm_port),
    ]
    all_ok = True
    for name, host, port in checks:
        ok = _check(host, port)
        all_ok = all_ok and ok
        print(f"{'OK ' if ok else 'NO '} {name}")

    print(f"\nSTATE_BACKEND={s.state_backend}  LLM_PRIMARY={s.llm_primary}")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
