"""ENTRADA vía Outlook COM/MAPI (sin credenciales ni IMAP).

Se apoya en el Outlook de escritorio YA autenticado en la máquina (Windows)
para leer las notificaciones de Teams que llegan al buzón, ejecuta el agente
y publica la respuesta por el Incoming Webhook.

Ventajas frente a IMAP: no requiere basic-auth (bloqueado en M365 corporativo)
ni app registration en Entra. Limitación: solo funciona en Windows con Outlook
instalado y abierto, y depende de que Teams esté configurado para enviar
notificaciones por correo.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from typing import Any, Callable, Protocol

from src.adapters.mcp_teams.cards import build_text_card
from src.adapters.mcp_teams.webhook_client import TeamsWebhookClient
from src.core.config import TeamsEmailSettings, get_settings
from src.core.models import AgentRequest
from src.core.request_parsing import infer_environment

# Cuántos mensajes recientes inspeccionar por pasada (evita recorrer todo).
_MAX_SCAN = 200
# Extensiones de adjuntos cuyo contenido se extrae como texto de contexto.
_TEXT_EXTENSIONS = {
    ".txt", ".log", ".json", ".csv", ".md", ".yaml", ".yml",
    ".xml", ".ini", ".conf", ".cfg", ".properties", ".sql",
}
# Topes para no inflar el contexto del agente.
_MAX_ATTACH_CHARS = 20000
_MAX_TOTAL_ATTACH_CHARS = 60000
# Constante de Outlook: olFolderInbox.
_OL_FOLDER_INBOX = 6


class _OrchestratorLike(Protocol):
    async def handle(self, request: AgentRequest) -> Any: ...


def _looks_like_teams(sender_email: str, sender_name: str, sender_filter: str) -> bool:
    se = (sender_email or "").lower()
    sn = (sender_name or "").lower()
    return sender_filter.lower() in se or "teams" in sn


def _matches(
    sender_email: str, sender_name: str, subject: str, settings: TeamsEmailSettings
) -> bool:
    """Coincide por remitente de Teams o por filtro de asunto (Power Automate)."""

    if settings.subject_filter:
        return settings.subject_filter.lower() in (subject or "").lower()
    return _looks_like_teams(sender_email, sender_name, settings.sender_filter)


# Etiquetas reconocidas en el cuerpo -> campo destino.
_LABELS = {
    "ASUNTO": "subject",
    "DE": "author",
    "FROM": "author",
    "DE USUARIO": "author",
    "MENSAJE": "text",
    "TEXTO": "text",
    "TEXT": "text",
    "CUERPO": "text",
    "TIPO": "type",
    "TYPE": "type",
}
# Detecta una etiqueta conocida seguida de ':' en cualquier posición del texto
# (sirve para cuerpos de una sola línea o multilínea). El lookbehind evita
# que la etiqueta sea parte de una palabra más larga.
_LABEL_TOKEN = re.compile(
    r"(?i)(?<![A-Za-zÁÉÍÓÚáéíóúÑñ])"
    r"(ASUNTO|DE\s+USUARIO|DE|FROM|MENSAJE|TEXTO|TEXT|CUERPO|TIPO|TYPE)\s*:"
)


def strip_trigger_prefix(text: str, prefix: str) -> str | None:
    """Devuelve el texto sin el prefijo de disparo, o None si no lo lleva.

    El emparejamiento ignora mayúsculas y espacios/':' iniciales. Si ``prefix``
    está vacío, no hay filtro y se devuelve el texto tal cual.
    """

    if not prefix:
        return text
    stripped = (text or "").lstrip()
    if stripped[: len(prefix)].lower() != prefix.lower():
        return None
    rest = stripped[len(prefix):]
    return rest.lstrip(" \t:,-–—\r\n")


def extract_message(body: str) -> dict[str, str]:
    """Obtiene {text, author} del cuerpo del correo.

    Soporta tres formatos, en orden de prioridad:
    1. JSON: ``{"text": ..., "from": ...}``.
    2. Etiquetas: ``DE: ...`` / ``MENSAJE: ...`` / ``TIPO: ...`` en cualquier
       orden y posición (una o varias líneas); el valor de cada etiqueta es
       todo lo que sigue hasta la siguiente etiqueta conocida. Recomendado
       para flujos de Power Automate.
    3. Texto plano: se usa el cuerpo completo como mensaje.
    """

    raw = (body or "").strip()
    if not raw:
        return {"text": "", "author": ""}

    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            text = str(data.get("text") or data.get("message") or "").strip()
            author = str(
                data.get("from") or data.get("author") or data.get("user") or ""
            ).strip()
            return {"text": text or raw, "author": author}

    matches = list(_LABEL_TOKEN.finditer(raw))
    if matches:
        fields: dict[str, str] = {}
        for i, match in enumerate(matches):
            label = " ".join(match.group(1).upper().split())
            key = _LABELS.get(label)
            if key is None:
                continue
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            value = raw[start:end].strip()
            if not fields.get(key):
                fields[key] = value
        return {
            "text": fields.get("text", "").strip(),
            "author": fields.get("author", "").strip(),
        }

    return {"text": raw, "author": ""}


def _read_attachments(item: Any) -> list[dict[str, str]]:
    """Extrae los adjuntos del correo: {filename, content}.

    Para archivos de texto guarda y lee el contenido (con topes); para el
    resto solo registra el nombre. Usa SaveAsFile vía COM en un dir temporal.
    """

    attachments = getattr(item, "Attachments", None)
    if not attachments:
        return []

    results: list[dict[str, str]] = []
    total = 0
    with tempfile.TemporaryDirectory(prefix="valex_attach_") as tmp:
        for att in attachments:
            name = str(getattr(att, "FileName", "") or "").strip()
            if not name:
                continue
            ext = os.path.splitext(name)[1].lower()
            content = ""
            if ext in _TEXT_EXTENSIONS and total < _MAX_TOTAL_ATTACH_CHARS:
                path = os.path.join(tmp, os.path.basename(name))
                try:
                    att.SaveAsFile(path)
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        content = fh.read(_MAX_ATTACH_CHARS)
                    total += len(content)
                except Exception:  # noqa: BLE001
                    content = ""
            results.append({"filename": name, "content": content})
    return results


def compose_request_text(message: str, attachments: list[dict[str, str]]) -> str:
    """Une el mensaje con el contenido de los adjuntos como contexto."""

    parts = [message]
    named = [a for a in attachments if a.get("filename")]
    if named:
        parts.append("\n--- Archivos adjuntos (contexto) ---")
        for att in named:
            content = (att.get("content") or "").strip()
            if content:
                parts.append(f"\n[{att['filename']}]\n{content}")
            else:
                parts.append(f"\n[{att['filename']}] (adjunto no textual)")
    return "\n".join(parts)


class OutlookComListener:
    """Sondea la Bandeja de entrada de Outlook por notificaciones de Teams."""

    def __init__(
        self,
        orchestrator: _OrchestratorLike,
        webhook_client: TeamsWebhookClient | None = None,
        settings: TeamsEmailSettings | None = None,
        folder_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._settings = settings or get_settings().teams_email
        self._webhook = webhook_client or TeamsWebhookClient()
        self._folder_factory = folder_factory or self._default_folder

    def _default_folder(self) -> Any:
        import win32com.client  # noqa: PLC0415

        namespace = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        return namespace.GetDefaultFolder(_OL_FOLDER_INBOX)

    def _fetch_unread(self) -> list[dict[str, Any]]:
        """Operación COM bloqueante: devuelve los correos de Teams no leídos."""

        folder = self._folder_factory()
        items = folder.Items
        try:
            items.Sort("[ReceivedTime]", True)
        except Exception:  # noqa: BLE001
            pass

        out: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if index >= _MAX_SCAN:
                break
            if not bool(getattr(item, "UnRead", False)):
                continue
            sender_email = str(getattr(item, "SenderEmailAddress", "") or "")
            sender_name = str(getattr(item, "SenderName", "") or "")
            subject = str(getattr(item, "Subject", "") or "")
            if not _matches(sender_email, sender_name, subject, self._settings):
                continue
            parsed = extract_message(str(getattr(item, "Body", "") or ""))
            out.append(
                {
                    "author": parsed["author"] or sender_name or sender_email or "teams",
                    "subject": subject,
                    "text": parsed["text"],
                    "attachments": _read_attachments(item),
                }
            )
            try:
                item.UnRead = False
                item.Save()
            except Exception:  # noqa: BLE001
                pass
        return out

    async def poll_once(self) -> int:
        """Procesa los correos de Teams no leídos. Devuelve cuántos se atendieron."""

        messages = await asyncio.to_thread(self._fetch_unread)
        handled = 0
        for parsed in messages:
            text = parsed.get("text", "").strip()
            attachments = parsed.get("attachments", [])
            if not text and not attachments:
                continue
            # Solo se atienden mensajes con el prefijo de disparo (p. ej.
            # "SoporteGD ..."), evitando ecos del propio bot y chatter.
            triggered = strip_trigger_prefix(text, self._settings.trigger_prefix)
            if triggered is None:
                continue
            text = triggered
            if not text and not attachments:
                continue
            full_text = compose_request_text(text, attachments)
            response = await self._orchestrator.handle(
                AgentRequest(
                    text=full_text,
                    user_id=parsed.get("author") or "outlook-user",
                    channel="teams",
                    environment=infer_environment(full_text),
                    metadata={
                        "source": "outlook_com",
                        "subject": parsed.get("subject", ""),
                        "attachments": [a.get("filename") for a in attachments],
                    },
                )
            )
            await self._webhook.send_card(build_text_card(response.message))
            handled += 1
        return handled

    async def run_forever(self) -> None:
        """Bucle de polling continuo (para ejecutar como tarea de fondo)."""

        interval = self._settings.poll_interval_seconds
        while True:
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(interval)
