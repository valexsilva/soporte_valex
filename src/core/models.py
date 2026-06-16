"""Modelos Pydantic compartidos del sistema multi-agente."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Environment(str, Enum):
    """Entornos de infraestructura objetivo."""

    DEV = "dev"
    PRE = "pre"
    PRO = "pro"


class SessionStatus(str, Enum):
    """Estados del ciclo de vida de una sesión del orquestador."""

    CREATED = "created"
    RUNNING = "running"
    SUSPENDED = "suspended"
    WAITING_DEVIN = "waiting_devin"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"


class StepType(str, Enum):
    """Tipo de paso dentro del bucle ReAct."""

    THOUGHT = "thought"
    ACTION = "action"
    OBSERVATION = "observation"


class ReActStep(BaseModel):
    """Un paso individual del razonamiento ReAct."""

    type: StepType
    content: str
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class AgentRequest(BaseModel):
    """Solicitud entrante hacia el orquestador."""

    text: str
    user_id: str
    user_role: str = "atencion"
    channel: str = "teams"
    component_name: str | None = None
    environment: Environment = Environment.PRE
    ai_provider: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    """Respuesta del orquestador hacia el canal de entrada."""

    session_id: str
    status: SessionStatus
    message: str
    steps: list[ReActStep] = Field(default_factory=list)
    requires_approval: bool = False
    integration_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSession(BaseModel):
    """Estado persistente de una sesión del agente."""

    session_id: str = Field(default_factory=lambda: _new_id("sess"))
    status: SessionStatus = SessionStatus.CREATED
    request: AgentRequest
    steps: list[ReActStep] = Field(default_factory=list)
    cycle_count: int = 0
    pending_action: dict[str, Any] | None = None
    devin_session_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def touch(self) -> None:
        """Actualiza la marca temporal de modificación."""

        self.updated_at = _utcnow()
