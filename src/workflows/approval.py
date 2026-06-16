"""Lógica de aprobaciones Human-in-the-loop (doc sección 1.3 / 8.2).

Determina cuándo un plan de acción requiere firma humana y construye el
contexto de auditoría para la tarjeta de aprobación.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from src.core.models import AgentSession, Environment

# Acciones que siempre requieren aprobación de un Administrador.
SENSITIVE_ACTIONS = {"deploy", "rollback", "restart"}


class ApprovalRequest(BaseModel):
    """Contexto de auditoría para una solicitud de aprobación."""

    session_id: str
    component_name: str
    environment: str
    action: str
    branch: str
    summary: str


def requires_approval(action: str, environment: Environment) -> bool:
    """Indica si una acción exige aprobación humana.

    Las acciones sensibles en entornos no productivos (DEV/PRE) requieren
    firma. En PRO el PRO Shield bloquea antes de llegar aquí.
    """

    return action in SENSITIVE_ACTIONS and environment != Environment.PRO


def build_approval_request(
    session: AgentSession, action_payload: dict[str, Any]
) -> ApprovalRequest:
    """Construye la solicitud de aprobación a partir del plan de acción."""

    return ApprovalRequest(
        session_id=session.session_id,
        component_name=action_payload.get("component_name", "desconocido"),
        environment=action_payload.get("environment", "pre"),
        action=action_payload.get("action", "desconocida"),
        branch=action_payload.get("branch", "main"),
        summary=action_payload.get("summary", "Acción de mitigación propuesta."),
    )
