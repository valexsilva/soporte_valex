"""Verificador de SALIDA: postea una Adaptive Card de prueba al canal.

Usa el Incoming Webhook configurado (TEAMS_WEBHOOK_INCOMING_URL) para
confirmar que el agente puede publicar tarjetas en Teams. No requiere
endpoint público ni Azure/Entra.

Uso:
    # opción 1: por variable de entorno / .env
    py -3 scripts/send_test_card.py

    # opción 2: pasando la URL como argumento
    py -3 scripts/send_test_card.py "https://...webhook-url..."
"""

from __future__ import annotations

import asyncio
import sys

from src.adapters.mcp_teams.cards import build_approval_card, build_text_card
from src.adapters.mcp_teams.webhook_client import TeamsWebhookClient
from src.core.config import TeamsWebhookSettings, get_settings


def _inject_truststore() -> None:
    """Confía en la CA raíz del SO (inspección TLS corporativa)."""

    try:
        import truststore  # noqa: PLC0415

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001
        pass


async def main() -> int:
    _inject_truststore()
    url = sys.argv[1] if len(sys.argv) > 1 else get_settings().teams_webhook.incoming_url
    if not url:
        print(
            "ERROR: falta la URL del Incoming Webhook.\n"
            "Configura TEAMS_WEBHOOK_INCOMING_URL en .env o pásala como argumento."
        )
        return 1

    client = TeamsWebhookClient(TeamsWebhookSettings(incoming_url=url))

    print("Enviando tarjeta de texto...")
    r1 = await client.send_card(
        build_text_card("✅ Prueba de conexión del Agente Valex: tarjeta de texto.")
    )
    print("  ->", r1)

    print("Enviando tarjeta de aprobación (HITL)...")
    r2 = await client.send_card(
        build_approval_card(
            {
                "session_id": "demo-001",
                "component_name": "bus-pagos",
                "environment": "pre",
                "action": "rollback",
                "branch": "fix/mitigacion-123",
                "summary": "Despliegue de mitigación tras incidencia.",
            }
        )
    )
    print("  ->", r2)

    ok = r1.get("status") == "ok" and r2.get("status") == "ok"
    print("\n" + ("OK: ambas tarjetas enviadas." if ok else "FALLO: revisa la URL/red."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
