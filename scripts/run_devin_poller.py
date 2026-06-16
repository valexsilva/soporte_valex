"""Ejecuta el poller que entrega la respuesta final de Devin al canal.

Devin es asíncrono: el listener de entrada despacha el trabajo y la sesión
queda en WAITING_DEVIN. Este poller consulta esas sesiones, las reanuda y
cuando Devin termina publica la respuesta por el Incoming Webhook.

Comparte el store de sesiones (Redis) con el listener, así que se ejecuta como
un proceso independiente, en paralelo a ``run_outlook_listener.py``.

Uso:
    py -3 scripts/run_devin_poller.py            # bucle continuo
    py -3 scripts/run_devin_poller.py --once     # una sola pasada
"""

from __future__ import annotations

import asyncio
import os
import sys

# Permite ejecutar el script directamente (python scripts/run_X.py) añadiendo
# la raíz del repo a sys.path, para que 'import src...' funcione sin PYTHONPATH.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.mcp_teams.devin_poller import DevinResumePoller  # noqa: E402
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
    poller = DevinResumePoller(AgentOrchestrator())

    if "--once" in sys.argv:
        n = await poller.poll_once()
        print(f"Sesiones Devin completadas y publicadas: {n}.")
        return 0

    interval = get_settings().teams_webhook.poller_interval_seconds
    print(f"Poller de Devin activo (cada {interval}s). Ctrl+C para salir.")
    await poller.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
