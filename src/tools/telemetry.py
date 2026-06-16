"""Tool: get_component_telemetry_and_logs (doc sección 7.1).

Extrae logs/spans de un componente de forma agnóstica a su tecnología
(.NET, Python, Go, Node.js). En esta fase opera en modo simulado.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.tools.base import Tool


class TelemetryInput(BaseModel):
    """Esquema de entrada de la tool de telemetría."""

    component_name: str
    environment: Literal["dev", "pre", "pro"]
    fetch_type: Literal["dynatrace_spans", "raw_logs"]
    window_minutes: int = Field(default=60, ge=1, le=1440)


class TelemetryTool(Tool):
    """Obtiene telemetría y logs de un microservicio."""

    name = "get_component_telemetry_and_logs"
    description = (
        "Extrae logs estructurados o spans de Dynatrace de un componente "
        "transversal, de forma agnóstica a su tecnología base."
    )
    input_model = TelemetryInput

    async def run(self, payload: BaseModel) -> dict[str, Any]:
        assert isinstance(payload, TelemetryInput)
        # Modo simulado: respuesta representativa para el bucle ReAct.
        return {
            "component_name": payload.component_name,
            "environment": payload.environment,
            "fetch_type": payload.fetch_type,
            "window_minutes": payload.window_minutes,
            "findings": [
                {
                    "severity": "error",
                    "message": f"Timeout en conexión a Oracle para {payload.component_name}",
                    "count": 12,
                },
                {
                    "severity": "warning",
                    "message": "Latencia elevada en pool de conexiones",
                    "count": 4,
                },
            ],
            "simulated": True,
        }
