"""Pruebas del proveedor Devin (extracción de mensajes y polling)."""

from __future__ import annotations

from src.integrations.devin.polling import TERMINAL_STATES
from src.integrations.devin.sessions import DevinProvider


def test_extract_text_prefers_last_agent_message() -> None:
    # La Devin API v3 entrega los mensajes bajo la clave 'items'.
    payload = {
        "items": [
            {"source": "user", "message": "hola"},
            {"source": "devin", "message": "respuesta intermedia"},
            {"source": "user", "message": "otra pregunta"},
            {"source": "devin", "message": "respuesta final del agente"},
            {"source": "user", "message": "ultimo mensaje del usuario"},
        ]
    }
    assert DevinProvider._extract_text(payload) == "respuesta final del agente"


def test_extract_text_empty_when_no_items() -> None:
    assert DevinProvider._extract_text({}) == ""
    assert DevinProvider._extract_text({"items": []}) == ""


def test_extract_text_fallback_to_last_item() -> None:
    # Sin fuente de agente identificable, cae al último item.
    payload = {"items": [{"source": "system", "message": "solo este"}]}
    assert DevinProvider._extract_text(payload) == "solo este"


def test_suspended_is_terminal_state() -> None:
    # Devin marca 'suspended' cuando termina su turno y espera al usuario.
    assert "suspended" in TERMINAL_STATES
