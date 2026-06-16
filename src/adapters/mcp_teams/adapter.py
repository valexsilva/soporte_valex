"""Adapter unificado de Teams (doc sección 14.3).

Despacha la respuesta del orquestador hacia Teams según el proveedor
configurado (simulated | webhook) sin alterar el bucle ReAct. Cuando el
estado es SUSPENDED, envía una Adaptive Card de aprobación.
"""

from __future__ import annotations

from typing import Any

from src.adapters.mcp_teams.cards import build_approval_card, build_text_card
from src.adapters.mcp_teams.webhook_client import TeamsWebhookClient
from src.core.config import IntegrationMode, Settings, get_settings
from src.core.models import AgentResponse, SessionStatus


class TeamsAdapter:
    """Punto de salida hacia Teams con selección de proveedor."""

    def __init__(
        self,
        settings: Settings | None = None,
        webhook_client: TeamsWebhookClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._webhook_client = webhook_client or TeamsWebhookClient(
            self._settings.teams_webhook
        )

    async def dispatch(self, response: AgentResponse) -> dict[str, Any]:
        """Despacha la respuesta del agente al canal Teams configurado."""

        if self._settings.teams_mode == IntegrationMode.WEBHOOK:
            return await self._dispatch_webhook(response)

        # Modo simulado por defecto.
        return self._dispatch_simulated(response)

    async def _dispatch_webhook(self, response: AgentResponse) -> dict[str, Any]:
        """SALIDA hacia Teams vía Incoming Webhook con Adaptive Cards."""

        if response.status == SessionStatus.SUSPENDED and response.requires_approval:
            approval = response.integration_metadata.get("approval", {})
            card = build_approval_card(approval)
            result = await self._webhook_client.send_card(card)
            return {"provider": "webhook", "kind": "adaptive_card", "result": result}

        card = build_text_card(response.message)
        result = await self._webhook_client.send_card(card)
        return {"provider": "webhook", "kind": "message", "result": result}

    def _dispatch_simulated(self, response: AgentResponse) -> dict[str, Any]:
        if response.status == SessionStatus.SUSPENDED:
            approval = response.integration_metadata.get("approval", {})
            return {
                "provider": "simulated",
                "kind": "adaptive_card",
                "card": build_approval_card(approval),
            }
        return {
            "provider": "simulated",
            "kind": "message",
            "card": build_text_card(response.message),
        }
