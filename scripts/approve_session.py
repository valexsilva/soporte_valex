"""Aprobación manual de sesiones Human-in-the-loop (HITL) en local.

En modo webhook, la Adaptive Card de aprobación se publica en el canal pero el
Incoming Webhook NO devuelve el clic de Aprobar/Rechazar al backend. Este script
permite cerrar el ciclo HITL desde la terminal: lista las sesiones suspendidas y
reanuda una (aprobando o rechazando), publicando el resultado en el canal por el
Incoming Webhook (vía el TeamsAdapter).

Uso:
    py -3 scripts/approve_session.py --list
    py -3 scripts/approve_session.py --approve <session_id>
    py -3 scripts/approve_session.py --reject  <session_id>
"""

from __future__ import annotations

import argparse
import asyncio

from src.adapters.mcp_teams.adapter import TeamsAdapter
from src.agents.orchestrator.react_loop import AgentOrchestrator
from src.core.config import get_settings
from src.core.exceptions import SessionNotFound
from src.core.models import SessionStatus
from src.workflows.state_manager import build_session_store


def _inject_truststore() -> None:
    try:
        import truststore  # noqa: PLC0415

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001
        pass


async def _list_suspended() -> int:
    store = build_session_store(get_settings())
    sessions = await store.list_sessions()
    suspended = [s for s in sessions if s.status == SessionStatus.SUSPENDED]
    if not suspended:
        print("No hay sesiones suspendidas (pendientes de aprobación).")
        return 0
    print(f"{len(suspended)} sesión(es) pendiente(s) de aprobación:")
    for s in suspended:
        pending = s.pending_action or {}
        tool_input = pending.get("tool_input", {})
        print(
            f"- {s.session_id} | tool={pending.get('tool_name')} | "
            f"componente={tool_input.get('component_name')} | "
            f"entorno={tool_input.get('environment')} | "
            f"acción={tool_input.get('action')} | rama={tool_input.get('branch')}"
        )
    return 0


async def _resume(session_id: str, *, approved: bool) -> int:
    _inject_truststore()
    orchestrator = AgentOrchestrator()
    adapter = TeamsAdapter()
    user_choice = "Aprobado" if approved else "Rechazado"
    try:
        response = await orchestrator.resume(
            session_id, approved=approved, user_choice=user_choice
        )
    except SessionNotFound as exc:
        print(f"Error: {exc}")
        return 1

    dispatch = await adapter.dispatch(response)
    print(f"Sesión {session_id} -> {user_choice}.")
    print(f"  Estado final: {response.status.value}")
    print(f"  Mensaje publicado: {response.message}")
    print(f"  Dispatch: {dispatch.get('provider')}/{dispatch.get('kind')}")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="Aprobación manual HITL.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="Listar suspendidas.")
    group.add_argument("--approve", metavar="SESSION_ID", help="Aprobar la sesión.")
    group.add_argument("--reject", metavar="SESSION_ID", help="Rechazar la sesión.")
    args = parser.parse_args()

    if args.list:
        return await _list_suspended()
    if args.approve:
        return await _resume(args.approve, approved=True)
    return await _resume(args.reject, approved=False)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
