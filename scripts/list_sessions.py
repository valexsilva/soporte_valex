"""Diagnóstico: lista las sesiones del store con su estado y sesión Devin."""

from __future__ import annotations

import asyncio

from src.core.config import get_settings
from src.workflows.state_manager import build_session_store


async def main() -> int:
    store = build_session_store(get_settings())
    sessions = await store.list_sessions()
    if not sessions:
        print("No hay sesiones en el store.")
        return 0
    print(f"{len(sessions)} sesión(es):")
    for s in sessions:
        print(
            f"- {s.session_id} | status={s.status.value} | "
            f"devin={s.devin_session_id} | user={s.request.user_id} | "
            f"updated={s.updated_at.isoformat()}"
        )
        print(f"    text: {s.request.text[:80]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
