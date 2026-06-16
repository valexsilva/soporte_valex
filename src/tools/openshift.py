"""Tool: get_openshift_diagnostics (consola de OpenShift).

Fuente de diagnóstico para entornos donde Dynatrace no aplica o complementa
la telemetría. Cobertura por entorno:
- ``dev``: acceso pleno (pods, logs, eventos).
- ``pre``: permisos limitados (pods y eventos; logs restringidos).
- ``pro``: no es la fuente de diagnóstico (se usa Dynatrace, solo lectura).

En esta fase opera en modo simulado, devolviendo datos representativos para
el bucle ReAct.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.core.config import OpenShiftMode, Settings, get_settings
from src.integrations.openshift.client import OpenShiftCliClient
from src.tools.base import Tool


class OpenShiftInput(BaseModel):
    """Esquema de entrada de la tool de diagnóstico de OpenShift."""

    component_name: str
    environment: Literal["dev", "pre", "pro"]
    resource: Literal["pods", "logs", "events"] = "pods"
    namespace: str | None = None
    tail_lines: int = Field(default=100, ge=1, le=2000)


class OpenShiftDiagnosticsTool(Tool):
    """Consulta estado de pods, logs y eventos vía la consola de OpenShift."""

    name = "get_openshift_diagnostics"
    description = (
        "Consulta el estado de pods, logs y eventos de un componente en la "
        "consola de OpenShift. Úsala para diagnosticar en 'dev' (donde no hay "
        "Dynatrace) y como complemento en 'pre' (permisos limitados: los logs "
        "crudos pueden estar restringidos)."
    )
    input_model = OpenShiftInput

    def __init__(
        self,
        settings: Settings | None = None,
        client: OpenShiftCliClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client

    async def run(self, payload: BaseModel) -> dict[str, Any]:
        assert isinstance(payload, OpenShiftInput)

        if self._settings.openshift_mode == OpenShiftMode.CLI:
            client = self._client or OpenShiftCliClient(self._settings.openshift)
            return await client.diagnostics(
                component_name=payload.component_name,
                environment=payload.environment,
                resource=payload.resource,
                namespace=payload.namespace,
                tail_lines=payload.tail_lines,
            )

        namespace = payload.namespace or f"{payload.component_name}-{payload.environment}"
        base: dict[str, Any] = {
            "component_name": payload.component_name,
            "environment": payload.environment,
            "namespace": namespace,
            "resource": payload.resource,
            "simulated": True,
        }

        # En pro la fuente de diagnóstico es Dynatrace, no OpenShift.
        if payload.environment == "pro":
            base.update(
                {
                    "access": "denied",
                    "permissions_limited": True,
                    "findings": [],
                    "note": (
                        "OpenShift no se usa para diagnóstico en pro. Utiliza "
                        "Dynatrace (get_component_telemetry_and_logs) en modo "
                        "solo lectura."
                    ),
                }
            )
            return base

        limited = payload.environment == "pre"
        base["permissions_limited"] = limited

        if payload.resource == "logs" and limited:
            # En pre los logs crudos suelen estar restringidos.
            base.update(
                {
                    "access": "restricted",
                    "findings": [],
                    "note": (
                        "Logs crudos restringidos en pre por permisos. Revisa "
                        "pods/eventos o solicita acceso temporal."
                    ),
                }
            )
            return base

        base["access"] = "granted"
        base["findings"] = self._simulated_findings(payload)
        return base

    @staticmethod
    def _simulated_findings(payload: OpenShiftInput) -> list[dict[str, Any]]:
        component = payload.component_name
        if payload.resource == "pods":
            return [
                {
                    "pod": f"{component}-7d8c9b6f4-abcde",
                    "phase": "Running",
                    "ready": "1/1",
                    "restarts": 0,
                },
                {
                    "pod": f"{component}-7d8c9b6f4-fghij",
                    "phase": "CrashLoopBackOff",
                    "ready": "0/1",
                    "restarts": 7,
                    "reason": "Liveness probe failed",
                },
            ]
        if payload.resource == "events":
            return [
                {
                    "type": "Warning",
                    "reason": "BackOff",
                    "message": f"Back-off restarting failed container in {component}",
                    "count": 7,
                },
                {
                    "type": "Warning",
                    "reason": "Unhealthy",
                    "message": "Readiness probe failed: connection refused",
                    "count": 3,
                },
            ]
        # logs (acceso pleno)
        return [
            {
                "severity": "ERROR",
                "message": f"Connection refused to Oracle from {component}",
                "occurrences": 12,
            },
            {
                "severity": "WARN",
                "message": "HikariPool timeout awaiting connection",
                "occurrences": 5,
            },
        ]
