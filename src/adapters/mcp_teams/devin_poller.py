"""Poller de reanudación de sesiones Devin (entrega de respuesta final).

Devin es asíncrono: el orquestador despacha el trabajo y suspende la sesión con
estado ``WAITING_DEVIN``. Como no hay endpoint público para recibir el callback
de Devin, este poller consulta periódicamente las sesiones en espera, las
reanuda vía ``orchestrator.resume_devin`` y, cuando Devin termina, publica la
respuesta final en el canal por el Incoming Webhook (a través del adapter).

Comparte el mismo ``SessionStore`` (Redis) que el listener de entrada, por lo
que puede ejecutarse como un proceso independiente.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from src.adapters.mcp_teams.adapter import TeamsAdapter
from src.core.config import Settings, get_settings
from src.core.models import AgentResponse, SessionStatus
from src.workflows.state_manager import SessionStore, build_session_store


class _OrchestratorLike(Protocol):
    async def resume_devin(self, session_id: str) -> AgentResponse: ...


class DevinResumePoller:
    """Reanuda sesiones ``WAITING_DEVIN`` y entrega la respuesta al canal."""

    def __init__(
        self,
        orchestrator: _OrchestratorLike,
        adapter: TeamsAdapter | None = None,
        store: SessionStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._settings = settings or get_settings()
        self._adapter = adapter or TeamsAdapter(self._settings)
        self._store = store or build_session_store(self._settings)

    async def _waiting_ids(self) -> list[str]:
        """IDs de sesiones que esperan el resultado de Devin."""

        sessions = await self._store.list_sessions()
        return [
            s.session_id
            for s in sessions
            if s.status == SessionStatus.WAITING_DEVIN
        ]

    async def poll_once(self) -> int:
        """Reanuda cada sesión en espera; despacha las que ya terminaron.

        Devuelve cuántas sesiones se completaron (y se publicaron) en esta
        pasada. Las que siguen en curso quedan para la siguiente iteración.
        """

        completed = 0
        for session_id in await self._waiting_ids():
            response = await self._orchestrator.resume_devin(session_id)
            # Sigue esperando a Devin: no publicar todavía.
            if response.status == SessionStatus.WAITING_DEVIN:
                continue
            await self._adapter.dispatch(response)
            completed += 1
        return completed

    async def run_forever(self) -> None:
        """Bucle de polling continuo (para ejecutar como tarea de fondo)."""

        interval = self._settings.teams_webhook.poller_interval_seconds
        while True:
            try:
                completed = await self.poll_once()
                if completed:
                    print(
                        f"[devin-poller] {completed} sesión(es) completada(s) "
                        "y publicada(s) en el canal."
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[devin-poller] error en poll: {exc}")
            await asyncio.sleep(interval)
