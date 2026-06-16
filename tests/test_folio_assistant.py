"""Pruebas del asistente conversacional de folios y del prefijo de disparo."""

from __future__ import annotations

import pytest

from src.adapters.mcp_teams.outlook_listener import strip_trigger_prefix
from src.core.config import ServiceNowSettings
from src.core.models import AgentRequest, Environment, SessionStatus
from src.workflows.folio_assistant import (
    FolioAssistant,
    InMemoryFolioFormStore,
    is_folio_intent,
)


def _assistant() -> FolioAssistant:
    sn = ServiceNowSettings(
        _env_file=None, instance_url="https://santander.service-now.com"
    )
    return FolioAssistant(store=InMemoryFolioFormStore(), servicenow=sn)


def _req(text: str, user: str = "u1") -> AgentRequest:
    return AgentRequest(text=text, user_id=user, environment=Environment.PRE)


# ---- Prefijo de disparo ----------------------------------------------------


def test_strip_prefix_matches_case_insensitive_and_separators() -> None:
    assert strip_trigger_prefix("SoporteGD hola", "SoporteGD") == "hola"
    assert strip_trigger_prefix("soportegd: hola", "SoporteGD") == "hola"
    assert strip_trigger_prefix("  SoporteGD - hola", "SoporteGD") == "hola"


def test_strip_prefix_returns_none_without_prefix() -> None:
    assert strip_trigger_prefix("hola sin prefijo", "SoporteGD") is None


def test_strip_prefix_empty_disables_filter() -> None:
    assert strip_trigger_prefix("cualquier cosa", "") == "cualquier cosa"


# ---- Detección de intención -----------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "quiero levantar un folio",
        "ayuda para llenar el folio",
        "folio",
        "necesito crear un folio en servicenow",
    ],
)
def test_is_folio_intent_true(text: str) -> None:
    assert is_folio_intent(text) is True


@pytest.mark.parametrize(
    "text",
    ["el bus de pagos da timeout", "revisa los pods de linea-pf"],
)
def test_is_folio_intent_false(text: str) -> None:
    assert is_folio_intent(text) is False


# ---- Entrevista completa ---------------------------------------------------


@pytest.mark.asyncio
async def test_non_intent_returns_none() -> None:
    assistant = _assistant()
    assert await assistant.handle(_req("estado del bus de pagos")) is None


@pytest.mark.asyncio
async def test_full_interview_builds_summary() -> None:
    assistant = _assistant()

    r = await assistant.handle(_req("ayuda para levantar un folio"))
    assert r is not None
    assert r.status == SessionStatus.RUNNING
    assert "servicio" in r.message.lower()
    assert "SoporteGD" in r.message

    r = await assistant.handle(_req("OpenShift"))
    assert "componente" in r.message.lower()

    r = await assistant.handle(_req("linea-pf-service"))
    assert "entorno" in r.message.lower()

    r = await assistant.handle(_req("pre"))
    assert "describe" in r.message.lower()

    r = await assistant.handle(_req("Pods en CrashLoopBackOff desde las 10am"))
    assert "correo" in r.message.lower()

    r = await assistant.handle(_req("alsilva@santander.com.mx"))
    assert "tel" in r.message.lower()

    r = await assistant.handle(_req("5579237209"))
    assert r.status == SessionStatus.COMPLETED
    assert "Middleware Services" in r.message
    assert "b6c0e9173374a61013cc7e282e5c7bbc" in r.message
    assert "Order Now" in r.message
    assert "DevOps para CaaS OpenShift" in r.message
    assert "alsilva@santander.com.mx" in r.message

    # Tras completar, el formulario se limpió: un texto normal ya no se atiende.
    assert await assistant.handle(_req("hola")) is None


@pytest.mark.asyncio
async def test_prefill_skips_detected_fields() -> None:
    assistant = _assistant()

    r = await assistant.handle(_req("quiero levantar un folio de kafka en pre"))
    assert r is not None
    # Detectó servicio y entorno, así que NO pregunta por ellos: pasa a componente.
    assert "detect" in r.message.lower()
    assert "componente" in r.message.lower()

    r = await assistant.handle(_req("bus-pagos"))
    # El siguiente campo pendiente es la descripción (entorno ya pre-rellenado).
    assert "describe" in r.message.lower()

    r = await assistant.handle(_req("lag alto en el topic de pagos"))
    assert "correo" in r.message.lower()

    r = await assistant.handle(_req("alsilva@santander.com.mx"))
    assert "tel" in r.message.lower()

    r = await assistant.handle(_req("5579237209"))
    assert r.status == SessionStatus.COMPLETED
    assert "Confluent - Kafka" in r.message
    assert "Middleware Services" in r.message
    assert "Entorno: pre" in r.message


@pytest.mark.asyncio
async def test_invalid_service_reasks() -> None:
    assistant = _assistant()
    await assistant.handle(_req("quiero un folio"))
    r = await assistant.handle(_req("no se cual"))
    assert "no identifiqu" in r.message.lower()
    # Sigue pidiendo el servicio (no avanza).
    r = await assistant.handle(_req("Kafka"))
    assert "componente" in r.message.lower()


@pytest.mark.asyncio
async def test_invalid_environment_reasks() -> None:
    assistant = _assistant()
    await assistant.handle(_req("folio"))
    await assistant.handle(_req("S3"))
    await assistant.handle(_req("mi-bucket"))
    r = await assistant.handle(_req("qa"))
    assert "no válido" in r.message.lower() or "no valido" in r.message.lower()
    r = await assistant.handle(_req("pro"))
    assert "describe" in r.message.lower()


@pytest.mark.asyncio
async def test_cancel_clears_form() -> None:
    assistant = _assistant()
    await assistant.handle(_req("ayuda con folio"))
    r = await assistant.handle(_req("cancelar"))
    assert r.status == SessionStatus.COMPLETED
    assert "cancel" in r.message.lower()
    # Ya no hay folio en curso.
    assert await assistant.handle(_req("hola")) is None
