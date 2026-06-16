"""Diagnóstico: ¿podemos leer Outlook de escritorio vía COM/MAPI?

No usa credenciales ni IMAP: se conecta al Outlook ya autenticado en esta
máquina (Windows). Cuenta los correos de la Bandeja de entrada y los que
parecen notificaciones de Teams.

Uso:
    py -3 scripts/test_outlook_com.py
"""

from __future__ import annotations


def main() -> int:
    try:
        import win32com.client  # noqa: PLC0415
    except ImportError:
        print("ERROR: pywin32 no está instalado (pip install pywin32).")
        return 1

    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
    except Exception as exc:  # noqa: BLE001
        print(f"FALLO al conectar con Outlook COM: {type(exc).__name__}: {exc}")
        print("¿Está Outlook de escritorio instalado y abierto?")
        return 1

    try:
        # 6 = olFolderInbox
        inbox = namespace.GetDefaultFolder(6)
        items = inbox.Items
        total = items.Count
        teams = 0
        # Revisa los más recientes para no recorrer todo el buzón.
        items.Sort("[ReceivedTime]", True)
        for i, item in enumerate(items):
            if i >= 200:
                break
            sender = str(getattr(item, "SenderEmailAddress", "") or "")
            name = str(getattr(item, "SenderName", "") or "")
            if "teams" in sender.lower() or "teams" in name.lower():
                teams += 1
        print("CONEXIÓN OK ✅")
        print(f"Carpeta: {inbox.Name}  Total mensajes: {total}")
        print(f"Notificaciones de Teams (en últimos 200): {teams}")
    except Exception as exc:  # noqa: BLE001
        print(f"Conectado, pero falló al leer la bandeja: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
