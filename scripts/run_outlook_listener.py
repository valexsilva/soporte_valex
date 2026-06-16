"""Ejecuta el listener de entrada vía Outlook COM (sin credenciales/IMAP).

Lee notificaciones de Teams desde tu Outlook de escritorio ya autenticado,
ejecuta el agente y publica la respuesta por el Incoming Webhook.

Uso:
    py -3 scripts/run_outlook_listener.py            # bucle continuo
    py -3 scripts/run_outlook_listener.py --once     # una sola pasada
"""

from __future__ import annotations

import asyncio
import os
import sys

# Permite ejecutar el script directamente (python scripts/run_X.py) añadiendo
# la raíz del repo a sys.path, para que 'import src...' funcione sin PYTHONPATH.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.mcp_teams.outlook_listener import OutlookComListener  # noqa: E402
from src.agents.orchestrator.react_loop import AgentOrchestrator  # noqa: E402
from src.core.config import get_settings  # noqa: E402


def _inject_truststore() -> None:
    try:
        import truststore  # noqa: PLC0415

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001
        pass


async def main() -> int:
    _inject_truststore()
    settings = get_settings().teams_email
    listener = OutlookComListener(AgentOrchestrator())

    if "--once" in sys.argv:
        n = await listener.poll_once()
        print(f"Procesados {n} correos de Teams desde Outlook.")
        return 0

    print(f"Escuchando Outlook (cada {settings.poll_interval_seconds}s). "
          "Ctrl+C para salir.")
    await listener.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
