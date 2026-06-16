"""Pruebas del listener de Outlook COM (con dobles, sin Outlook real)."""

from __future__ import annotations

from typing import Any

from src.adapters.mcp_teams.outlook_listener import (
    OutlookComListener,
    _looks_like_teams,
    _matches,
    compose_request_text,
    extract_message,
)
from src.core.config import TeamsEmailSettings
from src.core.models import AgentResponse, SessionStatus


class FakeAttachment:
    def __init__(self, filename: str, content: str = "") -> None:
        self.FileName = filename
        self._content = content

    def SaveAsFile(self, path: str) -> None:  # noqa: N802
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._content)


class FakeItem:
    def __init__(self, sender_email: str, sender_name: str, subject: str,
                 body: str, unread: bool = True,
                 attachments: list[FakeAttachment] | None = None) -> None:
        self.SenderEmailAddress = sender_email
        self.SenderName = sender_name
        self.Subject = subject
        self.Body = body
        self.UnRead = unread
        self.Attachments = attachments or []
        self.saved = False

    def Save(self) -> None:
        self.saved = True


class FakeItems:
    def __init__(self, items: list[FakeItem]) -> None:
        self._items = items

    def Sort(self, field: str, descending: bool) -> None:  # noqa: N802
        pass

    def __iter__(self):
        return iter(self._items)


class FakeFolder:
    Name = "Bandeja de entrada"

    def __init__(self, items: list[FakeItem]) -> None:
        self.Items = FakeItems(items)


class FakeWebhook:
    def __init__(self) -> None:
        self.cards: list[dict[str, Any]] = []

    async def send_card(self, card: dict[str, Any]) -> dict[str, Any]:
        self.cards.append(card)
        return {"status": "ok"}


class FakeOrchestrator:
    def __init__(self) -> None:
        self.handled: list[str] = []

    async def handle(self, request: Any) -> AgentResponse:
        self.handled.append(request.text)
        return AgentResponse(
            session_id="s1", status=SessionStatus.COMPLETED, message="respuesta del agente"
        )


def test_looks_like_teams() -> None:
    assert _looks_like_teams("noreply@email.teams.microsoft.com", "Microsoft Teams",
                             "teams.microsoft.com")
    assert _looks_like_teams("x@y.com", "Microsoft Teams", "teams.microsoft.com")
    assert not _looks_like_teams("jefe@empresa.com", "Beto", "teams.microsoft.com")


async def test_poll_once_processes_unread_teams() -> None:
    items = [
        FakeItem("noreply@email.teams.microsoft.com", "Microsoft Teams",
                 "Ana te mencionó", "Ana: ayuda con el pipeline", unread=True),
        FakeItem("jefe@empresa.com", "Beto", "otro", "no es teams", unread=True),
        FakeItem("noreply@email.teams.microsoft.com", "Microsoft Teams",
                 "ya leído", "viejo", unread=False),
    ]
    folder = FakeFolder(items)
    orch = FakeOrchestrator()
    webhook = FakeWebhook()
    listener = OutlookComListener(
        orch, webhook_client=webhook,  # type: ignore[arg-type]
        settings=TeamsEmailSettings(subject_filter="", trigger_prefix=""),
        folder_factory=lambda: folder,
    )

    handled = await listener.poll_once()
    assert handled == 1
    assert orch.handled == ["Ana: ayuda con el pipeline"]
    assert webhook.cards[0]["body"][0]["text"] == "respuesta del agente"
    assert items[0].UnRead is False and items[0].saved is True
    assert items[1].UnRead is True  # no era de Teams, intacto


def test_matches_by_subject_filter() -> None:
    s = TeamsEmailSettings(subject_filter="Soporte GD")
    # Aunque el remitente sea uno mismo (no Teams), coincide por asunto.
    assert _matches("yo@empresa.com", "Alejandro", "Soporte GD | 123 | SoporteGD", s)
    assert not _matches("yo@empresa.com", "Alejandro", "Reporte mensual", s)


def test_matches_by_sender_when_no_subject_filter() -> None:
    s = TeamsEmailSettings(subject_filter="")  # fuerza match por remitente
    assert _matches("noreply@email.teams.microsoft.com", "Microsoft Teams", "x", s)
    assert not _matches("jefe@empresa.com", "Beto", "x", s)


def test_extract_message_json() -> None:
    parsed = extract_message('{"text": "rollback bus-pagos", "from": "Ana"}')
    assert parsed["text"] == "rollback bus-pagos"
    assert parsed["author"] == "Ana"


def test_extract_message_plain() -> None:
    parsed = extract_message("  necesito ayuda con el pipeline  ")
    assert parsed["text"] == "necesito ayuda con el pipeline"
    assert parsed["author"] == ""


def test_extract_message_labeled() -> None:
    body = (
        "DE: 5e840d65-718b-42f8-a664-5ac801ef12a8\n"
        "TIPO: channel\n"
        "MENSAJE: falla en bus-pagos\nhacer rollback a pre"
    )
    parsed = extract_message(body)
    assert parsed["author"] == "5e840d65-718b-42f8-a664-5ac801ef12a8"
    assert parsed["text"] == "falla en bus-pagos\nhacer rollback a pre"


def test_extract_message_labeled_de_usuario() -> None:
    body = "De Usuario: Ana\nMENSAJE: revisa el deploy"
    parsed = extract_message(body)
    assert parsed["author"] == "Ana"
    assert parsed["text"] == "revisa el deploy"


def test_extract_message_labeled_tipo_after_mensaje() -> None:
    # Estructura real del flujo: MENSAJE no es el último (le sigue TIPO).
    body = (
        "ASUNTO: Soporte GD\n"
        "DE: Ana\n"
        "MENSAJE: falla en bus-pagos\nrevisar logs\n"
        "TIPO: channel"
    )
    parsed = extract_message(body)
    assert parsed["author"] == "Ana"
    assert parsed["text"] == "falla en bus-pagos\nrevisar logs"
    assert "channel" not in parsed["text"]


def test_extract_message_single_line() -> None:
    # Caso real del flujo: todas las etiquetas en una sola línea.
    body = (
        "ASUNTO: SoporteGD DE: 5e840d65-718b-42f8-a664-5ac801ef12a8 "
        "MENSAJE: Necesito revisar los servicios en dev TIPO:channel"
    )
    parsed = extract_message(body)
    assert parsed["author"] == "5e840d65-718b-42f8-a664-5ac801ef12a8"
    assert parsed["text"] == "Necesito revisar los servicios en dev"


def test_compose_request_text_with_attachments() -> None:
    text = compose_request_text(
        "revisa el error",
        [
            {"filename": "error.log", "content": "NullPointer at line 42"},
            {"filename": "captura.png", "content": ""},
        ],
    )
    assert "revisa el error" in text
    assert "[error.log]" in text and "NullPointer at line 42" in text
    assert "[captura.png] (adjunto no textual)" in text


async def test_poll_once_includes_attachment_context() -> None:
    items = [
        FakeItem(
            "yo@empresa.com", "Alejandro", "Soporte GD | 1 | SoporteGD",
            "DE: Ana\nMENSAJE: analiza el log\nTIPO: channel",
            unread=True,
            attachments=[FakeAttachment("trace.log", "ERROR: timeout en pago")],
        ),
    ]
    orch = FakeOrchestrator()
    listener = OutlookComListener(
        orch, webhook_client=FakeWebhook(),  # type: ignore[arg-type]
        settings=TeamsEmailSettings(subject_filter="Soporte GD", trigger_prefix=""),
        folder_factory=lambda: FakeFolder(items),
    )
    handled = await listener.poll_once()
    assert handled == 1
    sent = orch.handled[0]
    assert "analiza el log" in sent
    assert "[trace.log]" in sent and "ERROR: timeout en pago" in sent


async def test_poll_once_subject_filter_flow() -> None:
    items = [
        FakeItem("yo@empresa.com", "Alejandro", "Soporte GD | 123 | SoporteGD",
                 '{"text": "falla en bus-pagos", "from": "Alejandro"}', unread=True),
    ]
    orch = FakeOrchestrator()
    webhook = FakeWebhook()
    listener = OutlookComListener(
        orch, webhook_client=webhook,  # type: ignore[arg-type]
        settings=TeamsEmailSettings(subject_filter="Soporte GD", trigger_prefix=""),
        folder_factory=lambda: FakeFolder(items),
    )
    handled = await listener.poll_once()
    assert handled == 1
    assert orch.handled == ["falla en bus-pagos"]


async def test_poll_once_no_unread() -> None:
    items = [FakeItem("noreply@email.teams.microsoft.com", "Microsoft Teams",
                      "s", "cuerpo", unread=False)]
    orch = FakeOrchestrator()
    listener = OutlookComListener(
        orch, webhook_client=FakeWebhook(),  # type: ignore[arg-type]
        settings=TeamsEmailSettings(),
        folder_factory=lambda: FakeFolder(items),
    )
    assert await listener.poll_once() == 0
    assert orch.handled == []


async def test_trigger_prefix_gate() -> None:
    # Con prefijo por defecto 'SoporteGD': solo se procesa el que lo lleva,
    # y el prefijo se elimina antes de pasarlo al agente.
    items = [
        FakeItem("noreply@email.teams.microsoft.com", "Microsoft Teams",
                 "m1", "SoporteGD: revisa el bus de pagos", unread=True),
        FakeItem("noreply@email.teams.microsoft.com", "Microsoft Teams",
                 "m2", "mensaje sin prefijo (eco del bot)", unread=True),
    ]
    orch = FakeOrchestrator()
    listener = OutlookComListener(
        orch, webhook_client=FakeWebhook(),  # type: ignore[arg-type]
        settings=TeamsEmailSettings(subject_filter=""),
        folder_factory=lambda: FakeFolder(items),
    )
    handled = await listener.poll_once()
    assert handled == 1
    assert orch.handled == ["revisa el bus de pagos"]
