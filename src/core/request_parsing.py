"""Inferencia de campos del AgentRequest a partir del texto de entrada.

Los canales de entrada (Outlook, IMAP, Outgoing Webhook) reciben texto libre.
Aquí se infiere el entorno objetivo mencionado en el mensaje para no depender
del valor por defecto.
"""

from __future__ import annotations

import re

from src.core.models import Environment

# Patrones por entorno (con límites de palabra y sinónimos en es/en). El orden
# importa solo como desempate; se elige la mención que aparece ANTES en el texto.
_ENV_PATTERNS: list[tuple[Environment, re.Pattern[str]]] = [
    (
        Environment.PRE,
        re.compile(
            r"(?i)\b(pre|preprod|preproducci[oó]n|preproduction|staging|stage)\b"
        ),
    ),
    (
        Environment.PRO,
        re.compile(r"(?i)\b(pro|prod|producci[oó]n|productivo|production)\b"),
    ),
    (
        Environment.DEV,
        re.compile(r"(?i)\b(dev|desarrollo|development)\b"),
    ),
]


def infer_environment(
    text: str, default: Environment = Environment.PRE
) -> Environment:
    """Infiere el entorno mencionado en el texto; si no hay, devuelve `default`.

    Cuando el mensaje menciona varios entornos, se prioriza el que aparece
    primero en el texto.
    """

    best_env: Environment | None = None
    best_pos: int | None = None
    for env, pattern in _ENV_PATTERNS:
        match = pattern.search(text or "")
        if match and (best_pos is None or match.start() < best_pos):
            best_pos = match.start()
            best_env = env
    return best_env or default
