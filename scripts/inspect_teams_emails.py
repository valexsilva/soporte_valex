"""Inspecciona correos recientes de Outlook para afinar el filtro de Teams.

Read-only: NO ejecuta el agente ni publica en el canal. Muestra remitente,
asunto, estado de lectura y un fragmento del cuerpo de los mensajes más
recientes (y resalta los que coinciden con el filtro de Teams).

Uso:
    py -3 scripts/inspect_teams_emails.py
    py -3 scripts/inspect_teams_emails.py "Soporte GD"   # filtra por asunto
"""

from __future__ import annotations

import sys

from src.adapters.mcp_teams.outlook_listener import _looks_like_teams
from src.core.config import get_settings


def main() -> int:
    import win32com.client  # noqa: PLC0415

    needle = sys.argv[1].lower() if len(sys.argv) > 1 else None
    sender_filter = get_settings().teams_email.sender_filter

    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)
    items = inbox.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:  # noqa: BLE001
        pass

    shown = 0
    for index, item in enumerate(items):
        if index >= 60:
            break
        subject = str(getattr(item, "Subject", "") or "")
        sender_email = str(getattr(item, "SenderEmailAddress", "") or "")
        sender_name = str(getattr(item, "SenderName", "") or "")
        unread = bool(getattr(item, "UnRead", False))

        if needle and needle not in subject.lower():
            continue

        is_teams = _looks_like_teams(sender_email, sender_name, sender_filter)
        body = str(getattr(item, "Body", "") or "").strip().replace("\r", " ")
        preview = " ".join(body.split())[:200]

        print("-" * 70)
        print(f"Asunto : {subject}")
        print(f"De     : {sender_name}  <{sender_email}>")
        print(f"NoLeido: {unread}   ¿match filtro Teams?: {is_teams}")
        print(f"Cuerpo : {preview}")
        shown += 1
        if not needle and shown >= 15:
            break

    if shown == 0:
        print("No se encontraron mensajes con ese criterio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
