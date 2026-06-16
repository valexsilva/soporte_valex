"""Cuenta correos NO leídos que matchean el filtro (sin marcarlos como leídos).

Read-only: no ejecuta el agente ni cambia el estado de lectura.
"""

from __future__ import annotations

from src.adapters.mcp_teams.outlook_listener import _MAX_SCAN, _matches
from src.core.config import get_settings


def main() -> int:
    import win32com.client  # noqa: PLC0415

    settings = get_settings().teams_email
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    items = ns.GetDefaultFolder(6).Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:  # noqa: BLE001
        pass

    matches: list[str] = []
    for index, item in enumerate(items):
        if index >= _MAX_SCAN:
            break
        if not bool(getattr(item, "UnRead", False)):
            continue
        subject = str(getattr(item, "Subject", "") or "")
        se = str(getattr(item, "SenderEmailAddress", "") or "")
        sn = str(getattr(item, "SenderName", "") or "")
        if _matches(se, sn, subject, settings):
            matches.append(subject)

    print(f"Filtro asunto: '{settings.subject_filter}'")
    print(f"No leídos que matchean: {len(matches)}")
    for subj in matches[:20]:
        print(f"  - {subj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
