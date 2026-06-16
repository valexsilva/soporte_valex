"""Endpoint de ServiceNow: entrada de incidentes y escalamiento al Área X."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from src.agents.orchestrator.react_loop import AgentOrchestrator
from src.api.deps import get_orchestrator
from src.core.models import AgentRequest

router = APIRouter(prefix="/api/servicenow", tags=["servicenow"])


@router.post("/webhook")
async def servicenow_webhook(
    request: AgentRequest,
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    """Recibe un incidente desde ServiceNow y dispara el flujo del agente."""

    request.channel = "servicenow"
    response = await orchestrator.handle(request)
    return {"response": response.model_dump()}
