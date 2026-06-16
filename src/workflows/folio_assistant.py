"""Asistente conversacional para llenar folios de ServiceNow.

Mientras no haya credenciales de API para crear folios automáticamente, este
asistente guía al usuario en la MISMA conversación: le va preguntando los
datos necesarios (servicio, componente, entorno, descripción, contacto) y al
final arma el resumen con el Order Guide y los pasos para levantarlo.

El estado del formulario se persiste por usuario (memoria o Redis) para
soportar el flujo multi-turno entre mensajes del canal.
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, Field

from src.core.config import ServiceNowSettings, Settings, StateBackend, get_settings
from src.core.models import AgentRequest, AgentResponse, SessionStatus
from src.integrations.servicenow.catalog import (
    DEFAULT_INSTANCE_URL,
    ORDER_GUIDES,
    build_guide_url,
    resolve_service,
)

# Intención de "folio": pide ayuda para levantar/llenar/crear un folio.
_FOLIO_INTENT = re.compile(
    r"(?i)(ayuda|ay[uú]dame|quiero|necesito|crear|crea|levantar|levanta|"
    r"llenar|llena|abrir|abre|generar|genera|nuevo)[^.\n]*\bfolio\b"
    r"|^\s*folio\b"
)
_CANCEL = {"cancelar", "cancela", "cancel", "salir", "abortar"}

# Tokens de entorno aceptados.
_ENV_TOKENS = {
    "dev": "dev", "desarrollo": "dev", "development": "dev",
    "pre": "pre", "preprod": "pre", "preproduccion": "pre",
    "preproducción": "pre", "staging": "pre", "stage": "pre",
    "pro": "pro", "prod": "pro", "produccion": "pro",
    "producción": "pro", "productivo": "pro", "production": "pro",
}
# Regex para detectar el entorno mencionado en texto libre (palabra completa).
_ENV_REGEX = re.compile(
    r"(?i)\b(" + "|".join(sorted(_ENV_TOKENS, key=len, reverse=True)) + r")\b"
)


def _detect_environment(text: str) -> str | None:
    """Devuelve el entorno (dev/pre/pro) mencionado en el texto, o None."""

    match = _ENV_REGEX.search(text or "")
    return _ENV_TOKENS[match.group(1).lower()] if match else None


def is_folio_intent(text: str) -> bool:
    """True si el texto pide ayuda para levantar un folio."""

    return bool(_FOLIO_INTENT.search(text or ""))


class FolioForm(BaseModel):
    """Estado del formulario de folio en curso para un usuario."""

    user_id: str
    step: int = 0
    service: str = ""
    guide_key: str = ""
    component: str = ""
    environment: str = ""
    short_description: str = ""
    email: str = ""
    phone: str = ""


# Secuencia de campos a recolectar: (atributo, pregunta).
_FIELDS: list[tuple[str, str]] = [
    (
        "service",
        "¿Qué servicio presenta el problema? Opciones: Oracle, DB2, "
        "OpenShift, Kafka, S3.",
    ),
    ("component", "¿Cuál es el componente o aplicación afectada?"),
    ("environment", "¿En qué entorno ocurre? (dev, pre o pro)"),
    (
        "short_description",
        "Describe brevemente el problema (qué falla y desde cuándo).",
    ),
    ("email", "¿Correo de contacto para el folio?"),
    ("phone", "¿Teléfono de contacto?"),
]


class FolioFormStore(Protocol):
    """Contrato de almacenamiento del formulario por usuario."""

    async def get(self, user_id: str) -> FolioForm | None: ...

    async def put(self, form: FolioForm) -> None: ...

    async def clear(self, user_id: str) -> None: ...


class InMemoryFolioFormStore:
    """Almacén en memoria (proceso) del formulario por usuario."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, user_id: str) -> FolioForm | None:
        raw = self._data.get(user_id)
        return FolioForm.model_validate_json(raw) if raw else None

    async def put(self, form: FolioForm) -> None:
        self._data[form.user_id] = form.model_dump_json()

    async def clear(self, user_id: str) -> None:
        self._data.pop(user_id, None)


class RedisFolioFormStore:
    """Almacén en Redis del formulario por usuario (con TTL)."""

    def __init__(self, settings: Settings | None = None) -> None:
        import redis.asyncio as redis  # noqa: PLC0415

        cfg = settings or get_settings()
        self._client = redis.from_url(
            cfg.redis.url, decode_responses=True, protocol=cfg.redis.protocol
        )
        self._ttl = cfg.redis.state_ttl_seconds

    @staticmethod
    def _key(user_id: str) -> str:
        return f"folioform:{user_id}"

    async def get(self, user_id: str) -> FolioForm | None:
        raw = await self._client.get(self._key(user_id))
        return FolioForm.model_validate_json(raw) if raw else None

    async def put(self, form: FolioForm) -> None:
        await self._client.set(
            self._key(form.user_id), form.model_dump_json(), ex=self._ttl
        )

    async def clear(self, user_id: str) -> None:
        await self._client.delete(self._key(user_id))


def build_folio_form_store(settings: Settings | None = None) -> FolioFormStore:
    """Crea el store del formulario según el backend de estado configurado."""

    cfg = settings or get_settings()
    if cfg.state_backend == StateBackend.REDIS:
        return RedisFolioFormStore(cfg)
    return InMemoryFolioFormStore()


class FolioAssistant:
    """Entrevista al usuario para reunir los datos del folio (multi-turno)."""

    def __init__(
        self,
        store: FolioFormStore | None = None,
        servicenow: ServiceNowSettings | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._store = store or build_folio_form_store(cfg)
        self._sn = servicenow or cfg.servicenow

    async def handle(self, request: AgentRequest) -> AgentResponse | None:
        """Atiende el turno si hay un folio en curso o el usuario lo pide.

        Devuelve un AgentResponse cuando el asistente gestiona el mensaje, o
        None si el mensaje no corresponde al asistente (lo maneja el agente).
        """

        user_id = request.user_id
        text = (request.text or "").strip()
        form = await self._store.get(user_id)

        if form is None:
            if not is_folio_intent(text):
                return None
            form = FolioForm(user_id=user_id)
            # Pre-rellena lo que se pueda inferir del primer mensaje para
            # hacer menos preguntas (servicio y entorno).
            detected = self._prefill(form, text)
            return await self._advance(
                user_id,
                form,
                intro=self._intro(detected),
            )

        # Folio en curso: permitir cancelar.
        if text.lower() in _CANCEL:
            await self._store.clear(user_id)
            return self._reply(
                user_id,
                "He cancelado el folio. Cuando quieras retomarlo, escribe "
                '"folio".',
                status=SessionStatus.COMPLETED,
            )

        field, _ = _FIELDS[form.step]
        error = self._store_answer(form, field, text)
        if error:
            return self._ask(user_id, intro=error, question=_FIELDS[form.step][1])

        return await self._advance(user_id, form, intro="")

    # ---- Pre-rellenado y avance ---------------------------------------

    def _prefill(self, form: FolioForm, text: str) -> list[str]:
        """Infiere servicio/entorno del primer mensaje. Devuelve lo detectado."""

        detected: list[str] = []
        route = resolve_service(text)
        if route is not None:
            form.service = route.service
            form.guide_key = route.guide_key
            detected.append(f"servicio '{route.service}'")
        env = _detect_environment(text)
        if env is not None:
            form.environment = env
            detected.append(f"entorno '{env}'")
        return detected

    @staticmethod
    def _intro(detected: list[str]) -> str:
        base = (
            "Te ayudo a preparar el folio en ServiceNow. Te haré unas "
            "preguntas y al final te daré el enlace y los pasos."
        )
        if detected:
            base += f" Detecté {' y '.join(detected)}."
        return base

    @staticmethod
    def _first_unfilled(form: FolioForm) -> int:
        """Índice del primer campo aún sin completar (len si están todos)."""

        for i, (field, _) in enumerate(_FIELDS):
            if not getattr(form, field):
                return i
        return len(_FIELDS)

    async def _advance(
        self, user_id: str, form: FolioForm, *, intro: str
    ) -> AgentResponse:
        """Avanza al primer campo pendiente: pregunta, o cierra con el resumen."""

        form.step = self._first_unfilled(form)
        if form.step < len(_FIELDS):
            await self._store.put(form)
            return self._ask(user_id, intro=intro, question=_FIELDS[form.step][1])

        await self._store.clear(user_id)
        return self._reply(
            user_id, self._summary(form), status=SessionStatus.COMPLETED
        )

    # ---- Validación/almacenamiento de respuestas ----------------------

    def _store_answer(self, form: FolioForm, field: str, text: str) -> str:
        """Guarda la respuesta; devuelve un mensaje de error si es inválida."""

        if field == "service":
            route = resolve_service(text)
            if route is None:
                return (
                    "No identifiqué el servicio. Indica uno de: Oracle, DB2, "
                    "OpenShift, Kafka o S3."
                )
            form.service = route.service
            form.guide_key = route.guide_key
            return ""
        if field == "environment":
            env = _ENV_TOKENS.get(text.strip().lower())
            if env is None:
                return "Entorno no válido. Responde dev, pre o pro."
            form.environment = env
            return ""
        setattr(form, field, text.strip())
        return ""

    # ---- Construcción de respuestas -----------------------------------

    def _ask(self, user_id: str, *, intro: str, question: str) -> AgentResponse:
        parts = [p for p in (intro, question) if p]
        parts.append(self._prefix_reminder())
        return self._reply(
            user_id, "\n\n".join(parts), status=SessionStatus.RUNNING
        )

    def _summary(self, form: FolioForm) -> str:
        guide = ORDER_GUIDES.get(form.guide_key)
        instance_url = self._sn.instance_url or DEFAULT_INSTANCE_URL
        lines = [
            "Listo. Con estos datos puedes levantar el folio en ServiceNow:",
            "",
            f"- Servicio: {form.service}",
            f"- Componente: {form.component}",
            f"- Entorno: {form.environment}",
            f"- Descripción: {form.short_description}",
            f"- Contacto: {form.email} / {form.phone}",
        ]
        if guide is not None:
            url = build_guide_url(guide, instance_url)
            lines += [
                "",
                f"Order Guide: {guide.name}",
                f"Enlace: {url}",
                "",
                "Pasos:",
                "1. Abre el enlace (requiere tu login SSO).",
                f"2. Selecciona el servicio '{form.service}'.",
                "3. Completa 'Requested for' (tú), 'Company requester' "
                "(Santander México), email y teléfono de contacto.",
                f"4. En la descripción indica: {form.short_description}.",
                "5. Pulsa 'Order Now' y guarda el número de folio (REQ...).",
            ]
        lines += [
            "",
            "Nota: la creación automática estará disponible cuando se habiliten "
            "las credenciales de integración (API).",
            "",
            self._prefix_reminder(),
        ]
        return "\n".join(lines)

    @staticmethod
    def _prefix_reminder() -> str:
        return (
            'Recuerda anteponer "SoporteGD" a tus respuestas para que el flujo '
            "las lea."
        )

    @staticmethod
    def _reply(user_id: str, message: str, *, status: SessionStatus) -> AgentResponse:
        return AgentResponse(
            session_id=f"folio_{user_id}",
            status=status,
            message=message,
            integration_metadata={"assistant": "folio"},
        )
