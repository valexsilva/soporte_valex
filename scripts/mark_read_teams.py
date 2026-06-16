"""Marca como LEÍDOS los correos no leídos que matchean el filtro.

No ejecuta el agente ni crea sesiones: solo limpia la cola para una prueba
fresca. Útil antes de un run --once.
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

    cleared = 0
    for index, item in enumerate(items):
        if index >= _MAX_SCAN:
            break
        if not bool(getattr(item, "UnRead", False)):
            continue
        subject = str(getattr(item, "Subject", "") or "")
        se = str(getattr(item, "SenderEmailAddress", "") or "")
        sn = str(getattr(item, "SenderName", "") or "")
        if not _matches(se, sn, subject, settings):
            continue
        try:
            item.UnRead = False
            item.Save()
            cleared += 1
            print(f"  marcado leído: {subject}")
        except Exception as exc:  # noqa: BLE001
            print(f"  no se pudo marcar: {subject} ({exc})")

    print(f"\nTotal marcados como leídos: {cleared}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
