"""Polling de estado de sesiones Devin hasta alcanzar un estado terminal."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.config import DevinSettings, get_settings
from src.core.exceptions import LLMProviderError
from src.integrations.devin.client import DevinClient

# Estados terminales reportados por Devin API. `suspended` indica que el
# agente terminó su turno y espera input del usuario (turno completo).
TERMINAL_STATES = {
    "finished",
    "completed",
    "blocked",
    "suspended",
    "stopped",
    "failed",
    "expired",
}


async def wait_for_completion(
    client: DevinClient,
    session_id: str,
    *,
    settings: DevinSettings | None = None,
) -> dict[str, Any]:
    """Hace polling del status de una sesión hasta que sea terminal.

    Args:
        client: cliente Devin ya configurado.
        session_id: identificador de la sesión a vigilar.
        settings: override opcional de configuración de polling.

    Returns:
        El último payload de status devuelto por la API.

    Raises:
        LLMProviderError: si se agotan los intentos sin estado terminal.
    """

    cfg = settings or get_settings().devin
    last_status: dict[str, Any] = {}

    for _ in range(cfg.poll_max_attempts):
        last_status = await client.get_session(session_id)
        status_value = str(
            last_status.get("status_enum") or last_status.get("status") or ""
        ).lower()
        if status_value in TERMINAL_STATES:
            return last_status
        await asyncio.sleep(cfg.poll_interval_seconds)

    raise LLMProviderError(
        f"Devin session {session_id} no alcanzó estado terminal tras "
        f"{cfg.poll_max_attempts} intentos."
    )
