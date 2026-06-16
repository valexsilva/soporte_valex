"""Cliente HTTP de bajo nivel para la Devin API.

Implementa los endpoints definidos en la colección Flashpost `devin-api`:

- POST   /v3/organizations/{org_id}/sessions                   -> crear sesión
- GET    /v3/organizations/{org_id}/sessions                   -> listar sesiones
- GET    /v3/organizations/{org_id}/sessions/{session_id}      -> status sesión
- GET    /v3/organizations/{org_id}/sessions/{session_id}/messages
- POST   /v3/organizations/{org_id}/sessions/{session_id}/messages

La autenticación se realiza vía Bearer token (DEVIN_API_KEY).
"""

from __future__ import annotations

from typing import Any

import httpx

from src.core.config import DevinSettings, get_settings
from src.core.exceptions import LLMProviderError


class DevinClient:
    """Cliente asíncrono para la Devin API v3."""

    def __init__(self, settings: DevinSettings | None = None) -> None:
        self._settings = settings or get_settings().devin

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @property
    def _org_base(self) -> str:
        return f"{self._settings.api_base}/organizations/{self._settings.org_id}"

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._settings.timeout_seconds) as client:
                response = await client.request(
                    method, url, headers=self._headers, json=json
                )
                response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"Devin API error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Devin API connection error: {exc}") from exc

    async def create_session(
        self, prompt: str, *, idempotent: bool = True, **extra: Any
    ) -> dict[str, Any]:
        """Crea una nueva sesión Devin (POST /v3/organizations/{org_id}/sessions)."""

        payload: dict[str, Any] = {"prompt": prompt, "idempotent": idempotent}
        payload.update(extra)
        return await self._request(
            "POST", f"{self._org_base}/sessions", json=payload
        )

    async def list_sessions(self) -> dict[str, Any]:
        """Lista sesiones de la organización."""

        return await self._request("GET", f"{self._org_base}/sessions")

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Obtiene el status de una sesión."""

        return await self._request("GET", f"{self._org_base}/sessions/{session_id}")

    async def get_messages(self, session_id: str) -> dict[str, Any]:
        """Obtiene los mensajes de una sesión."""

        return await self._request(
            "GET", f"{self._org_base}/sessions/{session_id}/messages"
        )

    async def send_message(self, session_id: str, message: str) -> dict[str, Any]:
        """Envía un mensaje a una sesión existente."""

        return await self._request(
            "POST",
            f"{self._org_base}/sessions/{session_id}/messages",
            json={"message": message},
        )
