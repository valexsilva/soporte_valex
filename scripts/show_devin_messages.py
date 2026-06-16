"""Diagnóstico: muestra los mensajes de una sesión Devin.

Uso:
    py -3 scripts/show_devin_messages.py <devin_session_id>
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
    messages = await client.get_messages(session_id)
    items = (
        messages.get("items")
        or messages.get("messages")
        or messages.get("data")
        or []
    )
    print(f"{len(items)} mensaje(s):")
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source", "?")
        text = item.get("message") or item.get("content") or item.get("text") or ""
        print(f"\n--- [{source}] ---\n{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
