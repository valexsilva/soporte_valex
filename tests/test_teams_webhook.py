"""Pruebas de los webhooks de Teams (entrada/salida) con Adaptive Cards."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from src.adapters.mcp_teams.adapter import TeamsAdapter
from src.adapters.mcp_teams.webhook_client import TeamsWebhookClient, wrap_adaptive_card
from src.adapters.mcp_teams.webhook_inbound import (
    build_card_response,
    extract_author,
    extract_text,
    verify_hmac,
)
from src.core.config import IntegrationMode, Settings, TeamsWebhookSettings
from src.core.models import AgentResponse, SessionStatus


# ---- Salida (Incoming Webhook) ----------------------------------------


class FakeWebhookClient:
    def __init__(self) -> None:
        self.cards: list[dict[str, Any]] = []

    async def send_card(self, card: dict[str, Any]) -> dict[str, Any]:
        self.cards.append(card)
        return {"status": "ok", "http_status": 200}


def test_wrap_adaptive_card_format() -> None:
    card = {"type": "AdaptiveCard"}
    wrapped = wrap_adaptive_card(card)
    assert wrapped["type"] == "message"
    att = wrapped["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert att["content"] is card


async def test_dispatch_webhook_sends_card() -> None:
    settings = Settings(teams_mode=IntegrationMode.WEBHOOK)
    fake = FakeWebhookClient()
    adapter = TeamsAdapter(settings=settings, webhook_client=fake)  # type: ignore[arg-type]

    resp = AgentResponse(
        session_id="s1", status=SessionStatus.COMPLETED, message="hola equipo"
    )
    result = await adapter.dispatch(resp)
    assert result["provider"] == "webhook"
    assert fake.cards, "no se envió tarjeta"
    body = fake.cards[0]["body"][0]
    assert body["text"] == "hola equipo"


async def test_send_card_without_url_returns_error() -> None:
    client = TeamsWebhookClient(TeamsWebhookSettings(incoming_url=""))
    result = await client.send_card({"type": "AdaptiveCard"})
    assert result["status"] == "error"
    assert result["reason"] == "incoming_url_not_configured"


# ---- Entrada (Outgoing Webhook) ---------------------------------------


def _sign(body: bytes, token_b64: str) -> str:
    key = base64.b64decode(token_b64)
    digest = hmac.new(key, body, hashlib.sha256).digest()
    return "HMAC " + base64.b64encode(digest).decode("utf-8")


def test_verify_hmac_valid_and_invalid() -> None:
    token = base64.b64encode(b"super-secret-key").decode("utf-8")
    body = json.dumps({"text": "hola"}).encode("utf-8")
    good = _sign(body, token)
    assert verify_hmac(body, good, token) is True
    assert verify_hmac(body, "HMAC deadbeef", token) is False
    assert verify_hmac(body, None, token) is False


def test_verify_hmac_skipped_without_token() -> None:
    assert verify_hmac(b"x", None, "") is True


def test_extract_text_strips_mentions() -> None:
    activity = {"text": "<at>AgenteValex</at> necesito ayuda"}
    assert extract_text(activity) == "necesito ayuda"


def test_extract_author() -> None:
    assert extract_author({"from": {"name": "Ana"}}) == "Ana"
    assert extract_author({}) == "teams-user"


def test_build_card_response_format() -> None:
    resp = build_card_response({"type": "AdaptiveCard"})
    assert resp["type"] == "message"
    assert resp["attachments"][0]["contentType"].endswith("card.adaptive")
