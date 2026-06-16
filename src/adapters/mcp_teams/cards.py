"""Constructores de Adaptive Cards para Teams (doc sección 1.3 / 14.5)."""

from __future__ import annotations

from typing import Any


def build_approval_card(approval: dict[str, Any]) -> dict[str, Any]:
    """Crea una Adaptive Card de aprobación Human-in-the-loop.

    Incluye acciones Aprobar/Rechazar que disparan Action.Submit hacia el
    callback MCP (`/api/teams/mcp/action`).
    """

    return {
        "type": "AdaptiveCard",
        "version": "1.5",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "body": [
            {
                "type": "TextBlock",
                "text": "Firma de Release de Mitigación",
                "weight": "Bolder",
                "size": "Large",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Componente", "value": approval.get("component_name", "")},
                    {"title": "Entorno", "value": approval.get("environment", "")},
                    {"title": "Acción", "value": approval.get("action", "")},
                    {"title": "Rama", "value": approval.get("branch", "")},
                    {"title": "Análisis", "value": approval.get("summary", "")},
                ],
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Aprobar",
                "data": {
                    "session_id": approval.get("session_id"),
                    "approve": True,
                    "user_choice": "Aprobado",
                },
            },
            {
                "type": "Action.Submit",
                "title": "Rechazar",
                "data": {
                    "session_id": approval.get("session_id"),
                    "approve": False,
                    "user_choice": "Rechazado",
                },
            },
        ],
    }


def build_text_card(text: str) -> dict[str, Any]:
    """Crea una Adaptive Card simple de solo texto."""

    return {
        "type": "AdaptiveCard",
        "version": "1.5",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "body": [{"type": "TextBlock", "text": text, "wrap": True}],
    }
