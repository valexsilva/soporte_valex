"""Proveedor LLM basado en sesiones Devin.

Encapsula el flujo completo: crear sesión, hacer polling de status y
recuperar el último mensaje del agente como resultado de inferencia.
"""

from __future__ import annotations

from typing import Any

from src.core.config import DevinSettings, get_settings
from src.integrations.base import LLMResult
from src.integrations.devin.client import DevinClient
from src.integrations.devin.polling import TERMINAL_STATES, wait_for_completion


class DevinProvider:
    """Proveedor de inferencia (prioritario) sobre la Devin API."""

    name = "devin"

    def __init__(
        self,
        client: DevinClient | None = None,
        settings: DevinSettings | None = None,
    ) -> None:
        self._settings = settings or get_settings().devin
        self._client = client or DevinClient(self._settings)

    # Fuentes que identifican un mensaje emitido por el agente (no el usuario).
    _AGENT_SOURCES = {"devin", "assistant", "agent", "ai"}

    @classmethod
    def _extract_text(cls, messages: dict[str, Any]) -> str:
        """Extrae el último mensaje del agente del payload de mensajes.

        La Devin API v3 devuelve los mensajes bajo la clave `items`, cada
        uno con `source` (user/devin) y `message`. Se prioriza el último
        mensaje cuya fuente sea el agente.
        """

        items = (
            messages.get("items")
            or messages.get("messages")
            or messages.get("data")
            or []
        )
        if not isinstance(items, list) or not items:
            return ""

        def _text(item: dict[str, Any]) -> str:
            return str(
                item.get("message")
                or item.get("content")
                or item.get("text")
                or ""
            )

        for item in reversed(items):
            if isinstance(item, dict) and str(
                item.get("source", "")
            ).lower() in cls._AGENT_SOURCES:
                return _text(item)

        last = items[-1]
        return _text(last) if isinstance(last, dict) else ""

    async def complete(self, prompt: str, **kwargs: Any) -> LLMResult:
        """Ejecuta una inferencia completa contra Devin.

        Si se pasa `session_id`, reutiliza la sesión enviando un mensaje;
        de lo contrario crea una nueva sesión con el prompt.
        """

        session_id = kwargs.get("session_id")

        if session_id:
            await self._client.send_message(session_id, prompt)
        else:
            created = await self._client.create_session(prompt)
            session_id = created.get("session_id") or created.get("id")

        if not session_id:
            return LLMResult(text="", provider=self.name, confidence=0.0)

        status = await wait_for_completion(
            self._client, session_id, settings=self._settings
        )
        messages = await self._client.get_messages(session_id)
        text = self._extract_text(messages)

        return LLMResult(
            text=text,
            provider=self.name,
            confidence=1.0 if text else 0.0,
            raw={"session_id": session_id, "status": status},
        )

    # ---- Modo asíncrono (no bloqueante) -------------------------------

    async def start(
        self, prompt: str, *, session_id: str | None = None
    ) -> dict[str, Any]:
        """Despacha el trabajo a Devin sin esperar (no hace polling).

        Crea una nueva sesión o envía un mensaje a una existente y devuelve
        el identificador de la sesión Devin para reanudar luego vía callback.
        """

        if session_id:
            await self._client.send_message(session_id, prompt)
            return {"session_id": session_id, "url": None}

        created = await self._client.create_session(prompt)
        return {
            "session_id": created.get("session_id") or created.get("id"),
            "url": created.get("url"),
        }

    async def poll_result(self, session_id: str) -> LLMResult | None:
        """Consulta el estado de una sesión Devin sin bloquear.

        Devuelve `None` si la sesión sigue en ejecución; si alcanzó un estado
        terminal, recupera el último mensaje del agente como resultado.
        """

        status = await self._client.get_session(session_id)
        status_value = str(
            status.get("status_enum") or status.get("status") or ""
        ).lower()
        if status_value not in TERMINAL_STATES:
            return None

        messages = await self._client.get_messages(session_id)
        text = self._extract_text(messages)
        return LLMResult(
            text=text,
            provider=self.name,
            confidence=1.0 if text else 0.0,
            raw={"session_id": session_id, "status": status_value},
        )
