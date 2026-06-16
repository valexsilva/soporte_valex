"""Gestor de estado de sesiones (Punto 3/4: híbrido memoria/Redis).

Persiste el estado de las sesiones del orquestador. Soporta dos backends
conmutables por configuración: memoria (desarrollo/tests) y Redis
(estados HITL suspendidos con TTL).
"""

from __future__ import annotations

from typing import Protocol

from src.core.config import Settings, StateBackend, get_settings
from src.core.exceptions import SessionNotFound
from src.core.models import AgentSession


class SessionStore(Protocol):
    """Contrato de almacenamiento de sesiones."""

    async def save(self, session: AgentSession) -> None: ...

    async def load(self, session_id: str) -> AgentSession: ...

    async def delete(self, session_id: str) -> None: ...

    async def list_sessions(self) -> list[AgentSession]: ...


class InMemorySessionStore:
    """Almacenamiento en memoria para desarrollo y pruebas."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def save(self, session: AgentSession) -> None:
        session.touch()
        self._data[session.session_id] = session.model_dump_json()

    async def load(self, session_id: str) -> AgentSession:
        raw = self._data.get(session_id)
        if raw is None:
            raise SessionNotFound(f"Sesión no encontrada: {session_id}")
        return AgentSession.model_validate_json(raw)

    async def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)

    async def list_sessions(self) -> list[AgentSession]:
        return [AgentSession.model_validate_json(raw) for raw in self._data.values()]


class RedisSessionStore:
    """Almacenamiento en Redis para estados HITL con TTL."""

    def __init__(self, settings: Settings | None = None) -> None:
        # Import diferido para no exigir redis en entornos sin el backend.
        import redis.asyncio as redis  # noqa: PLC0415

        cfg = settings or get_settings()
        self._client = redis.from_url(
            cfg.redis.url,
            decode_responses=True,
            protocol=cfg.redis.protocol,
        )
        self._ttl = cfg.redis.state_ttl_seconds

    @staticmethod
    def _key(session_id: str) -> str:
        return f"session:{session_id}"

    async def save(self, session: AgentSession) -> None:
        session.touch()
        await self._client.set(
            self._key(session.session_id),
            session.model_dump_json(),
            ex=self._ttl,
        )

    async def load(self, session_id: str) -> AgentSession:
        raw = await self._client.get(self._key(session_id))
        if raw is None:
            raise SessionNotFound(f"Sesión no encontrada: {session_id}")
        return AgentSession.model_validate_json(raw)

    async def delete(self, session_id: str) -> None:
        await self._client.delete(self._key(session_id))

    async def list_sessions(self) -> list[AgentSession]:
        """Recorre las claves ``session:*`` y devuelve las sesiones vigentes."""

        sessions: list[AgentSession] = []
        async for key in self._client.scan_iter(match="session:*"):
            raw = await self._client.get(key)
            if raw is None:
                continue
            try:
                sessions.append(AgentSession.model_validate_json(raw))
            except ValueError:
                continue
        return sessions


def build_session_store(settings: Settings | None = None) -> SessionStore:
    """Crea el store de sesiones según el backend configurado."""

    cfg = settings or get_settings()
    if cfg.state_backend == StateBackend.REDIS:
        return RedisSessionStore(cfg)
    return InMemorySessionStore()
