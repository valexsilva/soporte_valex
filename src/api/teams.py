"""Endpoints de Teams: webhook de entrada y callback HITL (doc 14.6)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from src.adapters.mcp_teams.adapter import TeamsAdapter
from src.adapters.mcp_teams.cards import build_text_card
from src.adapters.mcp_teams.webhook_inbound import (
    build_card_response,
    extract_author,
    extract_text,
    verify_hmac,
)
from src.agents.orchestrator.react_loop import AgentOrchestrator
from src.api.deps import get_orchestrator, get_teams_adapter
from src.core.config import get_settings
from src.core.exceptions import SessionNotFound
from src.core.models import AgentRequest
from src.core.request_parsing import infer_environment

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.post("/outgoing")
async def teams_outgoing_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    adapter: TeamsAdapter = Depends(get_teams_adapter),
) -> dict[str, Any]:
    """ENTRADA: Outgoing Webhook de Teams (@mención en canal).

    Valida la firma HMAC sobre el cuerpo crudo, ejecuta el agente y
    responde con una Adaptive Card en formato Activity (la respuesta debe
    devolverse en ~5s; el dispatch de salida queda a cargo del flujo).
    """

    raw = await request.body()
    token = get_settings().teams_webhook.security_token
    if not verify_hmac(raw, authorization, token):
        raise HTTPException(status_code=401, detail="Firma HMAC inválida")

    try:
        activity = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Payload inválido") from exc

    text = extract_text(activity)
    if not text:
        return build_card_response(build_text_card("No recibí ningún mensaje."))

    response = await orchestrator.handle(
        AgentRequest(
            text=text,
            user_id=extract_author(activity),
            channel="teams",
            environment=infer_environment(text),
            metadata={"source": "outgoing_webhook"},
        )
    )
    return build_card_response(build_text_card(response.message))


@router.post("/webhook")
async def teams_webhook(
    request: AgentRequest,
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    adapter: TeamsAdapter = Depends(get_teams_adapter),
) -> dict[str, Any]:
    """Recibe una mención desde Teams y ejecuta el flujo del agente."""

    response = await orchestrator.handle(request)
    dispatch = await adapter.dispatch(response)
    return {"response": response.model_dump(), "dispatch": dispatch}


@router.post("/hitl/action")
async def teams_hitl_action(
    payload: dict[str, Any],
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    adapter: TeamsAdapter = Depends(get_teams_adapter),
) -> dict[str, Any]:
    """Recibe la decisión de la Adaptive Card y reanuda la sesión (HITL).

    Acepta el payload directo o anidado en `data` (modo Action.Submit).
    """

    data = payload.get("data", payload)
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id requerido")

    try:
        response = await orchestrator.resume(
            session_id,
            approved=bool(data.get("approve", False)),
            user_choice=str(data.get("user_choice", "")),
        )
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    dispatch = await adapter.dispatch(response)
    return {"response": response.model_dump(), "dispatch": dispatch}
