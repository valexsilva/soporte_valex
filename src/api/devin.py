"""Endpoint de callback para reanudar sesiones Devin asíncronas (Opción A).

El orquestador despacha el trabajo a Devin y suspende la sesión con estado
WAITING_DEVIN. Este endpoint reanuda el flujo: puede invocarse desde un
webhook de Devin al finalizar la sesión, o desde un poller/scheduler que
consulte periódicamente las sesiones en espera.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.adapters.mcp_teams.adapter import TeamsAdapter
from src.agents.orchestrator.react_loop import AgentOrchestrator
from src.api.deps import get_orchestrator, get_teams_adapter
from src.core.exceptions import SessionNotFound

router = APIRouter(prefix="/api/devin", tags=["devin"])


@router.post("/callback")
async def devin_callback(
    payload: dict[str, Any],
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    adapter: TeamsAdapter = Depends(get_teams_adapter),
) -> dict[str, Any]:
    """Reanuda una sesión que esperaba el resultado de Devin.

    Acepta el `session_id` (del orquestador) directo o anidado en `data`.
    Si la sesión Devin sigue en curso, responde 'en progreso'; si terminó,
    integra el resultado y continúa el flujo, despachando a Teams.
    """

    data = payload.get("data", payload)
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id requerido")

    try:
        response = await orchestrator.resume_devin(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    dispatch = await adapter.dispatch(response)
    return {"response": response.model_dump(), "dispatch": dispatch}
