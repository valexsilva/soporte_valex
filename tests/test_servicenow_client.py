"""Pruebas del cliente ServiceNow (Basic y OAuth, con httpx mockeado)."""

from __future__ import annotations

import httpx
import pytest

from src.core.config import IntegrationMode, ServiceNowSettings
from src.integrations.servicenow import client as snow_mod
from src.integrations.servicenow.client import ServiceNowClient


def _patch_httpx(monkeypatch, handler) -> None:
    """Hace que ServiceNowClient use un MockTransport con el handler dado."""

    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(snow_mod.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_basic_auth_creates_folio(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(201, json={"result": {"number": "INC0012345", "sys_id": "abc"}})

    _patch_httpx(monkeypatch, handler)
    settings = ServiceNowSettings(
        _env_file=None,
        instance_url="https://santander.service-now.com",
        api_user="n616242",
        api_token="secret",
        auth="basic",
    )
    client = ServiceNowClient(settings, mode=IntegrationMode.WEBHOOK)
    out = await client.create_folio(short_description="prueba")
    assert out["folio"] == "INC0012345"
    assert out["simulated"] is False
    assert seen["url"].endswith("/api/now/table/incident")
    assert seen["auth"].startswith("Basic ")


@pytest.mark.asyncio
async def test_oauth_fetches_token_then_creates_folio(monkeypatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/oauth_token.do":
            assert b"grant_type=password" in request.content
            assert b"client_id=cid" in request.content
            return httpx.Response(200, json={"access_token": "TOK123"})
        # Llamada a la tabla: debe traer el Bearer del token.
        assert request.headers.get("authorization") == "Bearer TOK123"
        return httpx.Response(201, json={"result": {"number": "INC9999", "sys_id": "z"}})

    _patch_httpx(monkeypatch, handler)
    settings = ServiceNowSettings(
        _env_file=None,
        instance_url="https://santander.service-now.com",
        api_user="n616242",
        api_token="secret",
        auth="oauth",
        client_id="cid",
        client_secret="csecret",
    )
    client = ServiceNowClient(settings, mode=IntegrationMode.WEBHOOK)
    out = await client.create_folio(short_description="prueba oauth")
    assert out["folio"] == "INC9999"
    assert any("/oauth_token.do" in c for c in calls)
    assert any("/api/now/table/incident" in c for c in calls)


@pytest.mark.asyncio
async def test_catalog_order_now_creates_req(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            return httpx.Response(200, json={"access_token": "TOK"})
        captured["path"] = request.url.path
        captured["body"] = request.content
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            json={
                "result": {
                    "sys_id": "d18ae730c3ad47d4e258364a050131de",
                    "number": "REQ020934282",
                    "request_number": "REQ020934282",
                    "table": "sc_request",
                }
            },
        )

    _patch_httpx(monkeypatch, handler)
    settings = ServiceNowSettings(
        _env_file=None,
        instance_url="https://santander.service-now.com",
        api_user="n616242",
        api_token="secret",
        auth="oauth",
        client_id="cid",
        client_secret="csecret",
        folio_method="catalog",
        catalog_item_sysid="b6c0e9173374a61013cc7e282e5c7bbc",
        catalog_variables={
            "requested_for": "ba24ee9887dd2e5070e5ec640cbb3510",
            "product_service": "416afbda2b16e2102a08f35fee91bf01",
            "type_of_request": "09eb33d22b56e2102a08f35fee91bf4a",
        },
        catalog_description_variable="short_description",
    )
    client = ServiceNowClient(settings, mode=IntegrationMode.WEBHOOK)
    out = await client.create_folio(
        short_description="Filenet caido", description="CrashLoopBackOff en pre"
    )
    assert out["folio"] == "REQ020934282"
    assert out["table"] == "sc_request"
    assert out["simulated"] is False
    assert captured["path"].endswith(
        "/api/sn_sc/servicecatalog/items/b6c0e9173374a61013cc7e282e5c7bbc/order_now"
    )
    assert captured["auth"] == "Bearer TOK"
    assert b"requested_for" in captured["body"]
    # La descripción se vuelca en la variable configurada.
    assert b"CrashLoopBackOff" in captured["body"]


@pytest.mark.asyncio
async def test_catalog_requires_item_sysid(monkeypatch) -> None:
    from src.core.exceptions import IntegrationError

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, json={"result": {}})

    _patch_httpx(monkeypatch, handler)
    settings = ServiceNowSettings(
        _env_file=None,
        instance_url="https://santander.service-now.com",
        api_user="u",
        api_token="p",
        folio_method="catalog",
    )
    client = ServiceNowClient(settings, mode=IntegrationMode.WEBHOOK)
    with pytest.raises(IntegrationError):
        await client.create_folio(short_description="x")


@pytest.mark.asyncio
async def test_simulated_when_no_instance_url(monkeypatch) -> None:
    settings = ServiceNowSettings(_env_file=None, auth="oauth")
    client = ServiceNowClient(settings, mode=IntegrationMode.WEBHOOK)
    out = await client.create_folio(short_description="x")
    assert out["simulated"] is True
    assert out["folio"].startswith("INC")


@pytest.mark.asyncio
async def test_guidance_routes_openshift_to_middleware_guide() -> None:
    settings = ServiceNowSettings(
        _env_file=None,
        instance_url="https://santander.service-now.com",
        folio_method="guidance",
    )
    client = ServiceNowClient(settings, mode=IntegrationMode.WEBHOOK)
    out = await client.create_folio(
        short_description="Pods en CrashLoopBackOff",
        component_name="linea-pf-service",
        service="OpenShift",
    )
    assert out["status"] == "manual_guidance"
    assert out["automated"] is False
    assert out["service"] == "DevOps para CaaS OpenShift"
    assert out["guide"] == "Middleware Services"
    assert "b6c0e9173374a61013cc7e282e5c7bbc" in out["guide_url"]
    assert any("Order Now" in step for step in out["instructions"])


@pytest.mark.asyncio
async def test_guidance_routes_s3_to_iaas_storage() -> None:
    settings = ServiceNowSettings(
        _env_file=None,
        instance_url="https://santander.service-now.com",
        folio_method="guidance",
    )
    client = ServiceNowClient(settings, mode=IntegrationMode.WEBHOOK)
    out = await client.create_folio(
        short_description="Bucket S3 inaccesible", service="S3"
    )
    assert out["service"] == "Scality para S3"
    assert out["guide"] == "Order Guide - IaaS - Storage"


@pytest.mark.asyncio
async def test_guidance_unknown_service_lists_options() -> None:
    settings = ServiceNowSettings(_env_file=None, folio_method="guidance")
    client = ServiceNowClient(settings, mode=IntegrationMode.SIMULATED)
    out = await client.create_folio(short_description="algo raro sin servicio claro")
    assert out["status"] == "manual_guidance"
    assert out["service"] is None
    assert len(out["options"]) == 2
