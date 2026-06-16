"""Construcción del registro de tools por defecto."""

from __future__ import annotations

from src.tools.base import ToolRegistry
from src.tools.openshift import OpenShiftDiagnosticsTool
from src.tools.pipeline import PipelineActionTool
from src.tools.servicenow_folio import CreateServiceNowFolioTool
from src.tools.telemetry import TelemetryTool


def build_default_registry() -> ToolRegistry:
    """Crea el registro con las tools estándar del agente."""

    registry = ToolRegistry()
    registry.register(TelemetryTool())
    registry.register(OpenShiftDiagnosticsTool())
    registry.register(PipelineActionTool())
    registry.register(CreateServiceNowFolioTool())
    return registry
