"""Pruebas de tools y PRO Shield (doc sección 11.1)."""

from __future__ import annotations

import pytest

from src.core.config import IntegrationMode, ServiceNowSettings, Settings
from src.core.exceptions import ProductionMutationBlocked, SchemaValidationError
from src.integrations.servicenow.client import ServiceNowClient
from src.tools.openshift import OpenShiftDiagnosticsTool
from src.tools.pipeline import PipelineActionTool
from src.tools.servicenow_folio import CreateServiceNowFolioTool
from src.tools.telemetry import TelemetryTool


def _sim_openshift_tool() -> OpenShiftDiagnosticsTool:
    """Tool de OpenShift en modo simulado, independiente del .env local."""

    return OpenShiftDiagnosticsTool(settings=Settings(_env_file=None))


def _sim_folio_tool() -> CreateServiceNowFolioTool:
    """Tool de folio en modo simulado (incident), independiente del .env local."""

    client = ServiceNowClient(
        ServiceNowSettings(_env_file=None), mode=IntegrationMode.SIMULATED
    )
    return CreateServiceNowFolioTool(client=client)


@pytest.mark.asyncio
async def test_telemetry_tool_returns_findings() -> None:
    tool = TelemetryTool()
    out = await tool(
        {
            "component_name": "bus-pagos",
            "environment": "pre",
            "fetch_type": "raw_logs",
        }
    )
    assert out["component_name"] == "bus-pagos"
    assert out["findings"]


@pytest.mark.asyncio
async def test_pipeline_blocks_production() -> None:
    tool = PipelineActionTool()
    with pytest.raises(ProductionMutationBlocked):
        await tool(
            {
                "component_name": "bus-pagos",
                "environment": "pro",
                "action": "rollback",
                "idempotency_key": "key-123",
            }
        )


@pytest.mark.asyncio
async def test_pipeline_schema_validation_error() -> None:
    tool = PipelineActionTool()
    with pytest.raises(SchemaValidationError):
        await tool({"component_name": "x", "environment": "pre"})


@pytest.mark.asyncio
async def test_pipeline_pre_executes() -> None:
    tool = PipelineActionTool()
    out = await tool(
        {
            "component_name": "bus-pagos",
            "environment": "pre",
            "action": "rollback",
            "idempotency_key": "key-123",
        }
    )
    assert out["status"] == "triggered"


@pytest.mark.asyncio
async def test_openshift_dev_full_access() -> None:
    tool = _sim_openshift_tool()
    out = await tool(
        {"component_name": "linea-pf-service", "environment": "dev", "resource": "pods"}
    )
    assert out["access"] == "granted"
    assert out["permissions_limited"] is False
    assert out["findings"]


@pytest.mark.asyncio
async def test_openshift_pre_restricts_raw_logs() -> None:
    tool = _sim_openshift_tool()
    out = await tool(
        {"component_name": "linea-pf-service", "environment": "pre", "resource": "logs"}
    )
    assert out["access"] == "restricted"
    assert out["permissions_limited"] is True
    assert out["findings"] == []


@pytest.mark.asyncio
async def test_openshift_pre_pods_allowed() -> None:
    tool = _sim_openshift_tool()
    out = await tool(
        {"component_name": "linea-pf-service", "environment": "pre", "resource": "pods"}
    )
    assert out["access"] == "granted"
    assert out["permissions_limited"] is True
    assert out["findings"]


@pytest.mark.asyncio
async def test_openshift_pro_not_available() -> None:
    tool = _sim_openshift_tool()
    out = await tool(
        {"component_name": "linea-pf-service", "environment": "pro", "resource": "pods"}
    )
    assert out["access"] == "denied"
    assert "Dynatrace" in out["note"]


@pytest.mark.asyncio
async def test_create_folio_tool_returns_number() -> None:
    tool = _sim_folio_tool()
    out = await tool(
        {
            "component_name": "linea-pf-service",
            "environment": "dev",
            "short_description": "Problema de infraestructura en pods",
            "description": "CrashLoopBackOff detectado",
            "urgency": "high",
        }
    )
    assert out["folio"].startswith("INC")
    assert out["status"] == "created"
    assert out["simulated"] is True


@pytest.mark.asyncio
async def test_create_folio_tool_validates_short_description() -> None:
    tool = CreateServiceNowFolioTool()
    with pytest.raises(SchemaValidationError):
        await tool(
            {"component_name": "x", "environment": "dev", "short_description": "no"}
        )
