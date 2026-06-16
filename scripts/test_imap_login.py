"""Diagnóstico aislado de IMAP: valida login y cuenta correos de Teams.

No construye el orquestador ni toca Redis. Sirve para saber si tu tenant
M365 permite IMAP (basic auth) antes de activar el flujo completo.

Uso:
    py -3 scripts/test_imap_login.py
"""

from __future__ import annotations

import imaplib

from src.core.config import get_settings


def _inject_truststore() -> None:
    try:
        import truststore  # noqa: PLC0415

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    _inject_truststore()
    s = get_settings().teams_email
    print(f"Host: {s.imap_host}:{s.imap_port}  Usuario: {s.username}")
    if not s.username or not s.password:
        print("ERROR: faltan TEAMS_EMAIL_USERNAME / TEAMS_EMAIL_PASSWORD en .env")
        return 1

    try:
        imap = imaplib.IMAP4_SSL(s.imap_host, s.imap_port)
    except Exception as exc:  # noqa: BLE001
        print(f"FALLO de conexión TLS/red: {type(exc).__name__}: {exc}")
        return 1

    try:
        imap.login(s.username, s.password)
    except imaplib.IMAP4.error as exc:
        print(f"FALLO de login (¿basic auth deshabilitado o credenciales?): {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FALLO inesperado en login: {type(exc).__name__}: {exc}")
        return 1

    print("LOGIN OK ✅")
    try:
        imap.select(s.mailbox)
        typ, data = imap.search(None, "FROM", s.sender_filter)
        ids = data[0].split() if data and data[0] else []
        typ2, unseen = imap.search(None, "UNSEEN", "FROM", s.sender_filter)
        uids = unseen[0].split() if unseen and unseen[0] else []
        print(f"Correos de Teams en {s.mailbox}: {len(ids)} (no leídos: {len(uids)})")
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
