"""Tests del poller de reanudación de Devin y de la sanitización anti-bucle."""

from __future__ import annotations

from src.adapters.mcp_teams.devin_poller import DevinResumePoller
from src.adapters.mcp_teams.webhook_client import (
    neutralize_keyword,
    sanitize_payload,
)
from src.core.models import (
    AgentRequest,
    AgentResponse,
    AgentSession,
    SessionStatus,
)
from src.workflows.state_manager import InMemorySessionStore

_ZWSP = "\u200b"


# ---- Anti-bucle: neutralización del keyword --------------------------------


def test_neutralize_keyword_breaks_literal_match() -> None:
    out = neutralize_keyword("Resumen de SoporteGD listo", "SoporteGD")
    assert "SoporteGD" not in out
    assert out.replace(_ZWSP, "") == "Resumen de SoporteGD listo"


def test_neutralize_keyword_case_insensitive() -> None:
    out = neutralize_keyword("ticket soportegd", "SoporteGD")
    assert "soportegd" not in out.lower().replace(_ZWSP, "") or _ZWSP in out
    assert _ZWSP in out


def test_neutralize_keyword_noop_when_absent() -> None:
    assert neutralize_keyword("sin keyword", "SoporteGD") == "sin keyword"


def test_sanitize_payload_recurses_dicts_and_lists() -> None:
    payload = {
        "type": "message",
        "attachments": [
            {"content": {"body": [{"text": "alerta SoporteGD"}]}},
        ],
    }
    out = sanitize_payload(payload, "SoporteGD")
    text = out["attachments"][0]["content"]["body"][0]["text"]
    assert "SoporteGD" not in text
    assert text.replace(_ZWSP, "") == "alerta SoporteGD"


# ---- list_sessions ---------------------------------------------------------


async def test_inmemory_list_sessions() -> None:
    store = InMemorySessionStore()
    s1 = AgentSession(request=AgentRequest(text="a", user_id="u1"))
    s2 = AgentSession(request=AgentRequest(text="b", user_id="u2"))
    s2.status = SessionStatus.WAITING_DEVIN
    await store.save(s1)
    await store.save(s2)

    sessions = await store.list_sessions()
    statuses = {s.session_id: s.status for s in sessions}
    assert statuses[s1.session_id] == SessionStatus.CREATED
    assert statuses[s2.session_id] == SessionStatus.WAITING_DEVIN


# ---- Poller ----------------------------------------------------------------


class _FakeOrchestrator:
    """Devuelve resultados predefinidos por session_id (FIFO por sesión)."""

    def __init__(self, results: dict[str, list[AgentResponse]]) -> None:
        self._results = results
        self.calls: list[str] = []

    async def resume_devin(self, session_id: str) -> AgentResponse:
        self.calls.append(session_id)
        queue = self._results[session_id]
        return queue.pop(0) if len(queue) > 1 else queue[0]


class _FakeAdapter:
    def __init__(self) -> None:
        self.dispatched: list[AgentResponse] = []

    async def dispatch(self, response: AgentResponse) -> dict[str, str]:
        self.dispatched.append(response)
        return {"status": "ok"}


def _resp(session_id: str, status: SessionStatus, msg: str) -> AgentResponse:
    return AgentResponse(session_id=session_id, status=status, message=msg)


async def test_poll_once_dispatches_only_completed() -> None:
    store = InMemorySessionStore()
    waiting = AgentSession(request=AgentRequest(text="x", user_id="u"))
    waiting.status = SessionStatus.WAITING_DEVIN
    still = AgentSession(request=AgentRequest(text="y", user_id="u"))
    still.status = SessionStatus.WAITING_DEVIN
    done_already = AgentSession(request=AgentRequest(text="z", user_id="u"))
    done_already.status = SessionStatus.COMPLETED
    await store.save(waiting)
    await store.save(still)
    await store.save(done_already)

    orch = _FakeOrchestrator(
        {
            waiting.session_id: [
                _resp(waiting.session_id, SessionStatus.COMPLETED, "listo")
            ],
            still.session_id: [
                _resp(still.session_id, SessionStatus.WAITING_DEVIN, "en curso")
            ],
        }
    )
    adapter = _FakeAdapter()
    poller = DevinResumePoller(orch, adapter=adapter, store=store)

    completed = await poller.poll_once()

    # Solo se reanudan las WAITING_DEVIN (no la ya COMPLETED).
    assert set(orch.calls) == {waiting.session_id, still.session_id}
    # Solo se publica la que terminó.
    assert completed == 1
    assert len(adapter.dispatched) == 1
    assert adapter.dispatched[0].session_id == waiting.session_id


async def test_poll_once_no_waiting_sessions() -> None:
    store = InMemorySessionStore()
    s = AgentSession(request=AgentRequest(text="x", user_id="u"))
    s.status = SessionStatus.COMPLETED
    await store.save(s)

    orch = _FakeOrchestrator({})
    adapter = _FakeAdapter()
    poller = DevinResumePoller(orch, adapter=adapter, store=store)

    completed = await poller.poll_once()
    assert completed == 0
    assert orch.calls == []
    assert adapter.dispatched == []
