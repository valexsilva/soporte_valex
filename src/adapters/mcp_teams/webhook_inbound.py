"""Helpers de ENTRADA: Outgoing Webhook de Teams (@mención en canal).

Cuando un usuario @menciona al webhook en un canal, Teams hace POST de una
Activity a nuestro endpoint con cabecera ``Authorization: HMAC <base64>``.
Aquí validamos la firma HMAC-SHA256, extraemos el texto (sin la mención) y
construimos la respuesta en formato Activity con una Adaptive Card.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from typing import Any

# Quita las menciones HTML <at>...</at> que Teams incluye en el texto.
_AT_TAG = re.compile(r"<at>.*?</at>", flags=re.IGNORECASE | re.DOTALL)


def verify_hmac(body: bytes, auth_header: str | None, security_token: str) -> bool:
    """Valida la firma HMAC del Outgoing Webhook de Teams.

    Teams firma el cuerpo crudo con el token (base64) y envía
    ``Authorization: HMAC <firma_base64>``. Si no hay token configurado, se
    omite la validación (modo desarrollo).
    """

    if not security_token:
        return True
    if not auth_header:
        return False

    provided = auth_header.split("HMAC ", 1)[-1].strip()
    try:
        key = base64.b64decode(security_token)
    except (ValueError, TypeError):
        return False
    digest = hmac.new(key, body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, provided)


def extract_text(activity: dict[str, Any]) -> str:
    """Devuelve el texto del mensaje sin las menciones <at>."""

    text = str(activity.get("text", ""))
    return _AT_TAG.sub("", text).strip()


def extract_author(activity: dict[str, Any]) -> str:
    """Nombre/ID del autor del mensaje entrante."""

    sender = activity.get("from", {})
    if isinstance(sender, dict):
        return str(sender.get("name") or sender.get("id") or "teams-user")
    return "teams-user"


def build_card_response(card: dict[str, Any]) -> dict[str, Any]:
    """Respuesta Activity con una Adaptive Card (la renderiza Teams)."""

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }
        ],
    }


def build_text_response(text: str) -> dict[str, Any]:
    """Respuesta Activity de texto simple."""

    return {"type": "message", "text": text}
