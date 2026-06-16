"""Pruebas del cliente OpenShift CLI (con runner 'oc' simulado)."""

from __future__ import annotations

import json

import pytest

from src.core.config import OpenShiftMode, OpenShiftSettings, Settings
from src.integrations.openshift.client import OpenShiftCliClient
from src.tools.openshift import OpenShiftDiagnosticsTool


def _settings(**kwargs) -> OpenShiftSettings:
    base = {
        "_env_file": None,
        "env_contexts": {"dev": ["dev-ctx"], "pre": ["pre-ctx"]},
    }
    base.update(kwargs)
    return OpenShiftSettings(**base)


def _runner(rc: int, out: str, err: str = ""):
    """Runner que registra TODAS las llamadas (una por contexto)."""

    calls: list[list[str]] = []

    async def run(args: list[str]) -> tuple[int, str, str]:
        calls.append(args)
        return rc, out, err

    run.calls = calls  # type: ignore[attr-defined]
    run.last = lambda: calls[-1]  # type: ignore[attr-defined]
    return run


@pytest.mark.asyncio
async def test_pods_parsed_and_context() -> None:
    pods = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "linea-pf-service-abc"},
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [{"ready": True, "restartCount": 0}],
                    },
                },
                {
                    "metadata": {"name": "linea-pf-service-def"},
                    "status": {
                        "phase": "CrashLoopBackOff",
                        "containerStatuses": [{"ready": False, "restartCount": 7}],
                    },
                },
            ]
        }
    )
    runner = _runner(0, pods)
    client = OpenShiftCliClient(_settings(), runner=runner)
    out = await client.diagnostics(
        component_name="linea-pf-service", environment="dev", resource="pods"
    )
    assert out["access"] == "granted"
    assert out["simulated"] is False
    assert {f["restarts"] for f in out["findings"]} == {0, 7}
    # Cada finding lleva el contexto que lo originó.
    assert all(f["context"] == "dev-ctx" for f in out["findings"])
    assert "--context" in runner.last()
    assert "dev-ctx" in runner.last()
    # Namespace por plantilla mx-{component}-{environment}, vía --namespace.
    assert out["namespace"] == "mx-linea-pf-service-dev"
    assert "--namespace" in runner.last()
    assert "mx-linea-pf-service-dev" in runner.last()


@pytest.mark.asyncio
async def test_component_map_overrides_contexts_namespace_deployment() -> None:
    settings = _settings(
        component_map={
            "apigateway": {
                "pre": {
                    "contexts": ["pre-ocp04-mx1"],
                    "namespace": "mx-api-gateway-pre",
                    "deployment": "api-gateway",
                }
            }
        },
    )
    runner = _runner(0, "")
    client = OpenShiftCliClient(settings, runner=runner)
    out = await client.diagnostics(
        component_name="apigateway",
        environment="pre",
        resource="logs",
        tail_lines=10,
    )
    assert out["clusters"][0]["context"] == "pre-ocp04-mx1"
    assert out["namespace"] == "mx-api-gateway-pre"
    args = runner.last()
    assert "pre-ocp04-mx1" in args  # contexto override (ocp04, no env_contexts)
    assert "mx-api-gateway-pre" in args
    assert "deployment/api-gateway" in args  # deployment override


@pytest.mark.asyncio
async def test_multiple_clusters_queried_and_aggregated() -> None:
    settings = _settings(
        component_map={
            "apigateway": {
                "pre": {"contexts": ["ocp04-pre-mx1", "ocp04-pre-mx2"]}
            }
        }
    )
    pods = json.dumps(
        {"items": [{"metadata": {"name": "apigw-1"}, "status": {"phase": "Running"}}]}
    )
    runner = _runner(0, pods)
    client = OpenShiftCliClient(settings, runner=runner)
    out = await client.diagnostics(
        component_name="apigateway", environment="pre", resource="pods"
    )
    # Se consultó cada clúster (mx1 y mx2).
    assert len(runner.calls) == 2
    assert {c["context"] for c in out["clusters"]} == {"ocp04-pre-mx1", "ocp04-pre-mx2"}
    # Findings agregados de ambos clústeres, cada uno etiquetado.
    assert len(out["findings"]) == 2
    assert {f["context"] for f in out["findings"]} == {"ocp04-pre-mx1", "ocp04-pre-mx2"}


@pytest.mark.asyncio
async def test_not_configured_when_no_contexts() -> None:
    settings = OpenShiftSettings(_env_file=None)  # sin env_contexts ni map
    runner = _runner(0, "{}")
    client = OpenShiftCliClient(settings, runner=runner)
    out = await client.diagnostics(
        component_name="desconocido", environment="dev", resource="pods"
    )
    assert out["access"] == "not_configured"
    assert runner.calls == []  # no ejecuta 'oc'


@pytest.mark.asyncio
async def test_logs_returns_lines() -> None:
    runner = _runner(0, "ERROR conexion rechazada\nWARN timeout\n")
    client = OpenShiftCliClient(_settings(), runner=runner)
    out = await client.diagnostics(
        component_name="linea-pf-service", environment="dev", resource="logs",
        tail_lines=50,
    )
    assert out["access"] == "granted"
    assert len(out["findings"]) == 2
    assert "logs" in runner.last()
    assert "--tail=50" in runner.last()


@pytest.mark.asyncio
async def test_rbac_forbidden_marks_restricted() -> None:
    runner = _runner(1, "", 'Error from server (Forbidden): pods is forbidden')
    client = OpenShiftCliClient(_settings(), runner=runner)
    out = await client.diagnostics(
        component_name="linea-pf-service", environment="pre", resource="logs"
    )
    assert out["access"] == "restricted"
    assert out["permissions_limited"] is True


@pytest.mark.asyncio
async def test_pro_denied_without_running() -> None:
    runner = _runner(0, "{}")
    client = OpenShiftCliClient(_settings(), runner=runner)
    out = await client.diagnostics(
        component_name="x", environment="pro", resource="pods"
    )
    assert out["access"] == "denied"
    assert runner.calls == []  # no ejecuta 'oc' en pro


@pytest.mark.asyncio
async def test_tool_uses_cli_when_mode_cli() -> None:
    settings = Settings(_env_file=None, openshift_mode=OpenShiftMode.CLI)
    runner = _runner(0, json.dumps({"items": []}))
    client = OpenShiftCliClient(_settings(), runner=runner)
    tool = OpenShiftDiagnosticsTool(settings=settings, client=client)
    out = await tool(
        {"component_name": "svc", "environment": "dev", "resource": "events"}
    )
    assert out["simulated"] is False
    assert out["access"] == "granted"
