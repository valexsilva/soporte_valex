"""Tool: execute_pipeline_action (doc sección 7.2).

Conector serverless idempotente hacia Jenkins / GitHub Actions. Incluye
el "PRO Shield": cualquier mutación sobre entorno productivo se bloquea
por diseño (doc sección 3.2).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.core.exceptions import ProductionMutationBlocked
from src.tools.base import Tool


class PipelineActionInput(BaseModel):
    """Esquema de entrada de la tool de ejecución de pipeline."""

    component_name: str
    environment: Literal["dev", "pre", "pro"]
    action: Literal["deploy", "rollback", "restart"]
    branch: str = "main"
    provider: Literal["jenkins", "github_actions"] = "github_actions"
    idempotency_key: str = Field(..., min_length=4)


class PipelineActionTool(Tool):
    """Ejecuta acciones de CI/CD en entornos controlados."""

    name = "execute_pipeline_action"
    description = (
        "Dispara acciones idempotentes de CI/CD (deploy, rollback, restart) "
        "en Jenkins o GitHub Actions. Bloqueado en producción (read-only)."
    )
    input_model = PipelineActionInput

    async def run(self, payload: BaseModel) -> dict[str, Any]:
        assert isinstance(payload, PipelineActionInput)

        # PRO Shield: bloqueo de mutaciones en producción.
        if payload.environment == "pro":
            raise ProductionMutationBlocked(
                "Mutaciones bloqueadas en PRO. El agente opera en modo read-only "
                "para entornos productivos."
            )

        return {
            "component_name": payload.component_name,
            "environment": payload.environment,
            "action": payload.action,
            "branch": payload.branch,
            "provider": payload.provider,
            "idempotency_key": payload.idempotency_key,
            "status": "triggered",
            "simulated": True,
        }
