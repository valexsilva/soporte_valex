"""Cliente de SALIDA hacia Teams vía Incoming Webhook / Workflows.

Publica mensajes y Adaptive Cards en un canal de Teams haciendo POST a la
URL del Incoming Webhook (o del flujo de Power Automate / Workflows).

NOTA sobre interactividad: las tarjetas posteadas por un Incoming Webhook
soportan ``Action.OpenUrl`` pero NO devuelven ``Action.Submit`` a nuestro
backend. Para HITL con callback se usa la ENTRADA por @mención (outgoing
webhook) o un bot. Ver ``src/api/teams.py``.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from src.core.config import TeamsWebhookSettings, get_settings

# Carácter invisible (zero-width space) para romper la coincidencia literal de
# la palabra clave sin alterar el texto visible.
_ZWSP = "\u200b"


def neutralize_keyword(text: str, keyword: str) -> str:
    """Rompe la coincidencia literal de ``keyword`` en ``text`` (anti-bucle).

    Inserta un carácter invisible tras el primer carácter del keyword, de forma
    que el flujo de Power Automate (que se dispara por la palabra clave) NO se
    reactive con las respuestas del propio agente. El texto se ve idéntico.
    """

    if not keyword or not text:
        return text
    replacement = keyword[0] + _ZWSP + keyword[1:]
    return re.sub(re.escape(keyword), replacement, text, flags=re.IGNORECASE)


def sanitize_payload(obj: Any, keyword: str) -> Any:
    """Aplica ``neutralize_keyword`` recursivamente a todas las cadenas."""

    if isinstance(obj, str):
        return neutralize_keyword(obj, keyword)
    if isinstance(obj, dict):
        return {k: sanitize_payload(v, keyword) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_payload(v, keyword) for v in obj]
    return obj


def wrap_adaptive_card(card: dict[str, Any]) -> dict[str, Any]:
    """Envuelve una Adaptive Card en el formato que aceptan los webhooks.

    Formato soportado por Workflows/Incoming Webhooks modernos:
    ``{type: message, attachments: [{contentType: adaptive, content: card}]}``.
    """

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }
        ],
    }


class TeamsWebhookClient:
    """POST de tarjetas/mensajes al Incoming Webhook del canal."""

    def __init__(self, settings: TeamsWebhookSettings | None = None) -> None:
        self._settings = settings or get_settings().teams_webhook

    async def send_card(self, card: dict[str, Any]) -> dict[str, Any]:
        """Publica una Adaptive Card en el canal."""

        return await self._post(wrap_adaptive_card(card))

    async def send_text(self, text: str) -> dict[str, Any]:
        """Publica un mensaje de texto simple en el canal."""

        return await self._post({"text": text})

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        if not self._settings.incoming_url:
            return {"status": "error", "reason": "incoming_url_not_configured"}
        # Anti-bucle: neutraliza la palabra clave que dispara el flujo de
        # entrada para que las respuestas del agente no se reenvíen a sí mismas.
        body = sanitize_payload(body, self._settings.loop_guard_keyword)
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.timeout_seconds
            ) as client:
                resp = await client.post(self._settings.incoming_url, json=body)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            return {"status": "error", "reason": "transport_error", "detail": str(exc)}
        return {"status": "ok", "http_status": resp.status_code}
