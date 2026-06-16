"""Diagnóstico: consulta el estado de una sesión Devin por su ID.

Uso:
    py -3 scripts/check_devin_session.py <devin_session_id>
"""

from __future__ import annotations

import asyncio
import sys

from src.core.config import get_settings
from src.integrations.devin.client import DevinClient


def _inject_truststore() -> None:
    try:
        import truststore  # noqa: PLC0415

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001
        pass


async def main() -> int:
    _inject_truststore()
    if len(sys.argv) < 2:
        print("Falta el devin_session_id.")
        return 1
    session_id = sys.argv[1]
    client = DevinClient(get_settings().devin)
    status = await client.get_session(session_id)
    value = status.get("status_enum") or status.get("status")
    print(f"Devin session {session_id}: status={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
