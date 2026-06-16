"""Pruebas del orquestador ReAct: flujo completo, HITL y escalamiento."""

from __future__ import annotations

import json

import pytest

from src.agents.orchestrator.react_loop import AgentOrchestrator
from src.core.config import (
    AuditBackend,
    LLMProvider,
    ServiceNowSettings,
    Settings,
    StateBackend,
)
from src.core.models import AgentRequest, Environment, SessionStatus
from src.integrations.base import LLMResult
from src.tools.registry import build_default_registry
from src.workflows.audit import AuditLogger, InMemoryAuditSink
from src.workflows.state_manager import InMemorySessionStore
from tests.conftest import StubLLMRouter


class FakeDevinProvider:
    """Doble de DevinProvider para validar el flujo asíncrono (Opción A)."""

    name = "devin"

    def __init__(self, poll_sequence: list[str | None]) -> None:
        # Cada elemento: None = aún en ejecución; str = texto terminal del agente.
        self._poll_sequence = poll_sequence
        self._poll_idx = 0
        self.started: list[tuple[str, str | None]] = []

    async def start(self, prompt: str, *, session_id: str | None = None) -> dict:
        self.started.append((prompt, session_id))
        return {"session_id": session_id or "devin-sess-1", "url": "http://devin/x"}

    async def poll_result(self, session_id: str) -> LLMResult | None:
        val = self._poll_sequence[min(self._poll_idx, len(self._poll_sequence) - 1)]
        self._poll_idx += 1
        if val is None:
            return None
        return LLMResult(
            text=val, provider="devin", confidence=1.0,
            raw={"session_id": session_id},
        )


def _devin_settings() -> Settings:
    return Settings(
        _env_file=None,
        state_backend=StateBackend.MEMORY,
        audit_backend=AuditBackend.MEMORY,
        llm_primary=LLMProvider.DEVIN,
        llm_fallback=LLMProvider.LOCAL,
        devin_async=True,
        react_max_cycles=3,
    )


def _build_async_devin_orchestrator(fake: FakeDevinProvider) -> AgentOrchestrator:
    return AgentOrchestrator(
        settings=_devin_settings(),
        router=StubLLMRouter(["{}"]),
        tools=build_default_registry(),
        store=InMemorySessionStore(),
        audit=AuditLogger(InMemoryAuditSink()),
        devin=fake,
    )


def _build_orchestrator(scripted: list[str], settings) -> AgentOrchestrator:
    return AgentOrchestrator(
        settings=settings,
        router=StubLLMRouter(scripted),
        tools=build_default_registry(),
        store=InMemorySessionStore(),
        audit=AuditLogger(InMemoryAuditSink()),
    )


@pytest.mark.asyncio
async def test_final_answer_flow(test_settings) -> None:
    scripted = [
        json.dumps(
            {"thought": "respondo directo", "action": "final",
             "final_answer": "Diagnóstico listo", "confidence": 0.95}
        )
    ]
    orch = _build_orchestrator(scripted, test_settings)
    resp = await orch.handle(
        AgentRequest(text="estado del bus", user_id="u1", environment=Environment.PRE)
    )
    assert resp.status == SessionStatus.COMPLETED
    assert "Diagnóstico" in resp.message


@pytest.mark.asyncio
async def test_hitl_suspend_and_resume(test_settings) -> None:
    scripted = [
        json.dumps(
            {
                "thought": "requiere rollback",
                "action": "tool",
                "tool_name": "execute_pipeline_action",
                "tool_input": {
                    "component_name": "bus-pagos",
                    "environment": "pre",
                    "action": "rollback",
                    "idempotency_key": "key-123",
                },
                "confidence": 0.95,
            }
        )
    ]
    orch = _build_orchestrator(scripted, test_settings)
    resp = await orch.handle(
        AgentRequest(text="falla", user_id="u1", environment=Environment.PRE)
    )
    assert resp.status == SessionStatus.SUSPENDED
    assert resp.requires_approval is True

    resumed = await orch.resume(resp.session_id, approved=True, user_choice="Aprobado")
    assert resumed.status == SessionStatus.COMPLETED


@pytest.mark.asyncio
async def test_tool_input_list_executes_each_then_final(test_settings) -> None:
    # Ciclo 1: telemetría de 2 componentes en paralelo (lista). Ciclo 2: final.
    scripted = [
        json.dumps(
            {
                "thought": "reviso ambos",
                "action": "tool",
                "tool_name": "get_component_telemetry_and_logs",
                "tool_input": [
                    {
                        "component_name": "linea-pf-service",
                        "environment": "pre",
                        "fetch_type": "raw_logs",
                    },
                    {
                        "component_name": "linea-pm-service",
                        "environment": "pre",
                        "fetch_type": "raw_logs",
                    },
                ],
                "confidence": 0.95,
            }
        ),
        json.dumps(
            {"thought": "listo", "action": "final",
             "final_answer": "Ambos servicios con timeouts a Oracle", "confidence": 0.95}
        ),
    ]
    orch = _build_orchestrator(scripted, test_settings)
    resp = await orch.handle(
        AgentRequest(text="revisar linea-*", user_id="u1", environment=Environment.PRE)
    )
    assert resp.status == SessionStatus.COMPLETED
    # Dos ACTION (una por componente) en los pasos registrados.
    actions = [s for s in resp.steps if s.tool_name == "get_component_telemetry_and_logs"
               and s.type.value == "action"]
    assert len(actions) == 2


@pytest.mark.asyncio
async def test_escalation_on_cycle_limit(test_settings) -> None:
    # Siempre pide una tool desconocida -> nunca finaliza -> escala.
    scripted = [
        json.dumps(
            {"thought": "loop", "action": "tool", "tool_name": "inexistente",
             "tool_input": {}, "confidence": 0.95}
        )
    ]
    orch = _build_orchestrator(scripted, test_settings)
    resp = await orch.handle(
        AgentRequest(text="x", user_id="u1", environment=Environment.PRE)
    )
    assert resp.status == SessionStatus.ESCALATED


@pytest.mark.asyncio
async def test_low_confidence_escalates(test_settings) -> None:
    scripted = [
        json.dumps(
            {"thought": "no estoy seguro", "action": "final",
             "final_answer": "quizas", "confidence": 0.4}
        )
    ]
    orch = _build_orchestrator(scripted, test_settings)
    resp = await orch.handle(
        AgentRequest(text="x", user_id="u1", environment=Environment.PRE)
    )
    assert resp.status == SessionStatus.ESCALATED


@pytest.mark.asyncio
async def test_escalate_includes_agent_clarification(test_settings) -> None:
    scripted = [
        json.dumps(
            {
                "thought": "falta el componente",
                "action": "escalate",
                "final_answer": "¿Qué componente deseas revisar?",
                "confidence": 0.45,
            }
        )
    ]
    orch = _build_orchestrator(scripted, test_settings)
    resp = await orch.handle(
        AgentRequest(text="x", user_id="u1", environment=Environment.PRE)
    )
    assert resp.status == SessionStatus.ESCALATED
    assert "¿Qué componente deseas revisar?" in resp.message
    assert "ServiceNow" in resp.message


@pytest.mark.asyncio
async def test_escalation_creates_servicenow_folio(test_settings) -> None:
    scripted = [
        json.dumps(
            {"thought": "no estoy seguro", "action": "escalate",
             "final_answer": "Posible problema de infraestructura", "confidence": 0.3}
        )
    ]
    orch = _build_orchestrator(scripted, test_settings)
    resp = await orch.handle(
        AgentRequest(text="x", user_id="u1", environment=Environment.PRE)
    )
    assert resp.status == SessionStatus.ESCALATED
    folio = resp.integration_metadata.get("folio", {})
    assert folio.get("folio", "").startswith("INC")
    assert folio["folio"] in resp.message


@pytest.mark.asyncio
async def test_escalation_guidance_mode_returns_steps(test_settings) -> None:
    # ServiceNow en modo 'guidance': no crea folio, devuelve los pasos.
    test_settings.servicenow = ServiceNowSettings(
        _env_file=None, folio_method="guidance"
    )
    scripted = [
        json.dumps(
            {"thought": "kafka caido", "action": "escalate",
             "final_answer": "Problema con Confluent Kafka", "confidence": 0.3}
        )
    ]
    orch = _build_orchestrator(scripted, test_settings)
    resp = await orch.handle(
        AgentRequest(
            text="kafka", user_id="u1", environment=Environment.PRE,
            component_name="bus-pagos",
        )
    )
    assert resp.status == SessionStatus.ESCALATED
    folio = resp.integration_metadata.get("folio", {})
    assert folio.get("status") == "manual_guidance"
    assert folio.get("guide") == "Middleware Services"
    assert "Order Now" in resp.message
    assert "Middleware Services" in resp.message


@pytest.mark.asyncio
async def test_devin_async_dispatch_then_resume_final() -> None:
    final = json.dumps(
        {"thought": "listo", "action": "final",
         "final_answer": "Diagnóstico Devin", "confidence": 0.95}
    )
    # 1er poll: aún en ejecución (None); 2do poll: resultado terminal.
    fake = FakeDevinProvider([None, final])
    orch = _build_async_devin_orchestrator(fake)

    resp = await orch.handle(
        AgentRequest(text="diagnostico", user_id="u1", environment=Environment.PRE)
    )
    # Se despacha a Devin y la sesión queda en espera (no bloquea).
    assert resp.status == SessionStatus.WAITING_DEVIN
    assert resp.integration_metadata["devin"]["session_id"] == "devin-sess-1"
    assert len(fake.started) == 1

    # Primer callback: Devin sigue trabajando.
    r1 = await orch.resume_devin(resp.session_id)
    assert r1.status == SessionStatus.WAITING_DEVIN

    # Segundo callback: Devin terminó -> se integra el resultado.
    r2 = await orch.resume_devin(resp.session_id)
    assert r2.status == SessionStatus.COMPLETED
    assert "Diagnóstico Devin" in r2.message


@pytest.mark.asyncio
async def test_devin_async_resume_unknown_state_is_safe() -> None:
    fake = FakeDevinProvider([None])
    orch = _build_async_devin_orchestrator(fake)
    resp = await orch.handle(
        AgentRequest(text="x", user_id="u1", environment=Environment.PRE)
    )
    # Completar primero para que ya no esté en WAITING_DEVIN.
    fake._poll_sequence = [
        json.dumps({"thought": "t", "action": "final",
                    "final_answer": "ok", "confidence": 0.95})
    ]
    fake._poll_idx = 0
    done = await orch.resume_devin(resp.session_id)
    assert done.status == SessionStatus.COMPLETED

    # Un segundo callback ya no debe reanudar nada (estado no en espera).
    again = await orch.resume_devin(resp.session_id)
    assert again.status == SessionStatus.COMPLETED
