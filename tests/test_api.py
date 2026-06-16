"""Pruebas de integración HTTP de la API (doc sección 11: Plan de Validación).

Usa TestClient con backends en memoria y un LLM stub, sobreescribiendo las
dependencias para no requerir Redis/Kafka/Devin reales.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from src.adapters.mcp_teams.adapter import TeamsAdapter
from src.agents.orchestrator.react_loop import AgentOrchestrator
from src.api.deps import get_orchestrator, get_teams_adapter
from src.api.main import app
from src.core.config import (
    AuditBackend,
    IntegrationMode,
    LLMProvider,
    Settings,
    StateBackend,
)
from src.tools.registry import build_default_registry
from src.workflows.audit import AuditLogger, InMemoryAuditSink
from src.workflows.state_manager import InMemorySessionStore
from tests.conftest import StubLLMRouter


def _memory_settings() -> Settings:
    return Settings(
        state_backend=StateBackend.MEMORY,
        audit_backend=AuditBackend.MEMORY,
        llm_primary=LLMProvider.LOCAL,
        llm_fallback=LLMProvider.LOCAL,
        teams_mode=IntegrationMode.SIMULATED,
        react_max_cycles=3,
    )


def _make_orchestrator(scripted: list[str]) -> AgentOrchestrator:
    settings = _memory_settings()
    return AgentOrchestrator(
        settings=settings,
        router=StubLLMRouter(scripted),
        tools=build_default_registry(),
        store=InMemorySessionStore(),
        audit=AuditLogger(InMemoryAuditSink()),
    )


@pytest.fixture
def client_factory():
    """Crea un TestClient con dependencias sobreescritas según el guion LLM."""

    created: list[TestClient] = []

    def _factory(scripted: list[str]) -> TestClient:
        orchestrator = _make_orchestrator(scripted)
        adapter = TeamsAdapter(settings=_memory_settings())
        app.dependency_overrides[get_orchestrator] = lambda: orchestrator
        app.dependency_overrides[get_teams_adapter] = lambda: adapter
        c = TestClient(app)
        created.append(c)
        return c

    yield _factory
    app.dependency_overrides.clear()


def test_health() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_teams_webhook_final_answer(client_factory) -> None:
    scripted = [
        json.dumps(
            {"thought": "ok", "action": "final",
             "final_answer": "Diagnóstico completado", "confidence": 0.95}
        )
    ]
    client = client_factory(scripted)
    resp = client.post(
        "/api/teams/webhook",
        json={"text": "estado del bus", "user_id": "u1", "environment": "pre"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"]["status"] == "completed"
    assert body["dispatch"]["provider"] == "simulated"


def test_teams_webhook_hitl_then_action(client_factory) -> None:
    scripted = [
        json.dumps(
            {
                "thought": "rollback",
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
    client = client_factory(scripted)
    resp = client.post(
        "/api/teams/webhook",
        json={"text": "falla", "user_id": "u1", "environment": "pre"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"]["status"] == "suspended"
    session_id = body["response"]["session_id"]

    # Callback de la Adaptive Card aprobando la acción.
    action = client.post(
        "/api/teams/hitl/action",
        json={"data": {"session_id": session_id, "approve": True,
                       "user_choice": "Aprobado"}},
    )
    assert action.status_code == 200
    assert action.json()["response"]["status"] == "completed"


def _final_answer_script(text: str = "Diagnóstico completado") -> list[str]:
    return [
        json.dumps(
            {"thought": "ok", "action": "final", "final_answer": text, "confidence": 0.95}
        )
    ]


def _sign_hmac(body: bytes, token_b64: str) -> str:
    key = base64.b64decode(token_b64)
    digest = hmac.new(key, body, hashlib.sha256).digest()
    return "HMAC " + base64.b64encode(digest).decode("utf-8")


def test_teams_outgoing_valid_hmac_returns_card(client_factory, monkeypatch) -> None:
    token = base64.b64encode(b"clave-secreta-de-prueba").decode("utf-8")
    settings = _memory_settings()
    settings.teams_webhook.security_token = token
    monkeypatch.setattr("src.api.teams.get_settings", lambda: settings)

    client = client_factory(_final_answer_script())
    body = json.dumps(
        {"text": "<at>Agente</at> estado del bus", "from": {"name": "Ana"}}
    ).encode("utf-8")

    resp = client.post(
        "/api/teams/outgoing",
        content=body,
        headers={"Authorization": _sign_hmac(body, token),
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["type"] == "message"
    card = payload["attachments"][0]["content"]
    assert card["body"][0]["text"] == "Diagnóstico completado"


def test_teams_outgoing_invalid_hmac_rejected(client_factory, monkeypatch) -> None:
    token = base64.b64encode(b"clave-secreta-de-prueba").decode("utf-8")
    settings = _memory_settings()
    settings.teams_webhook.security_token = token
    monkeypatch.setattr("src.api.teams.get_settings", lambda: settings)

    client = client_factory(_final_answer_script())
    body = json.dumps({"text": "hola"}).encode("utf-8")

    resp = client.post(
        "/api/teams/outgoing",
        content=body,
        headers={"Authorization": "HMAC firma-falsa",
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_teams_outgoing_without_token_skips_hmac(client_factory, monkeypatch) -> None:
    settings = _memory_settings()
    settings.teams_webhook.security_token = ""  # sin token -> sin validación
    monkeypatch.setattr("src.api.teams.get_settings", lambda: settings)

    client = client_factory(_final_answer_script("Todo en orden"))
    resp = client.post(
        "/api/teams/outgoing",
        json={"text": "<at>Agente</at> reporte", "from": {"name": "Beto"}},
    )
    assert resp.status_code == 200
    card = resp.json()["attachments"][0]["content"]
    assert card["body"][0]["text"] == "Todo en orden"


def test_ingestion_upload_and_status() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/ingestion/upload",
        files={"file": ("manual.txt", b"linea 1\nlinea 2\nlinea 3", "text/plain")},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status = client.get(f"/api/ingestion/status/{job_id}")
    assert status.status_code == 200
    assert status.json()["job_id"] == job_id


def test_finops_metrics() -> None:
    client = TestClient(app)
    resp = client.get("/api/finops/metrics")
    assert resp.status_code == 200
    assert "task_success_rate" in resp.json()
