"""Tool: create_servicenow_folio (creación de folios de infraestructura).

El agente la invoca cuando concluye que la causa es un problema de
infraestructura que requiere intervención del Área correspondiente.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.integrations.servicenow.client import ServiceNowClient
from src.tools.base import Tool


class CreateFolioInput(BaseModel):
    """Esquema de entrada de la tool de creación de folio."""

    component_name: str
    environment: Literal["dev", "pre", "pro"]
    short_description: str = Field(..., min_length=5)
    description: str = ""
    category: str = "infrastructure"
    urgency: Literal["low", "medium", "high"] = "medium"
    # Servicio afectado para enrutar al Order Guide correcto en modo 'guidance'
    # (p. ej. 'Oracle', 'DB2', 'OpenShift', 'Kafka', 'S3').
    service: str = ""


class CreateServiceNowFolioTool(Tool):
    """Crea un folio (incidente) en ServiceNow para problemas de infraestructura."""

    name = "create_servicenow_folio"
    description = (
        "Levanta un folio en ServiceNow cuando el diagnóstico concluye que la "
        "causa es un problema de infraestructura/servicio que requiere "
        "intervención del Área correspondiente. Indica 'service' (Oracle, DB2, "
        "OpenShift, Kafka, S3...). Si la creación automática no está habilitada, "
        "devuelve los pasos para levantar la petición en el catálogo."
    )
    input_model = CreateFolioInput

    def __init__(self, client: ServiceNowClient | None = None) -> None:
        self._client = client or ServiceNowClient()

    async def run(self, payload: BaseModel) -> dict[str, Any]:
        assert isinstance(payload, CreateFolioInput)
        return await self._client.create_folio(
            short_description=payload.short_description,
            description=payload.description,
            component_name=payload.component_name,
            environment=payload.environment,
            category=payload.category,
            urgency=payload.urgency,
            service=payload.service,
        )
