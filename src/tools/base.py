"""Infraestructura base para el catálogo de tools del agente."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from src.tools.schema_guard import validate_tool_input


class Tool(ABC):
    """Tool ejecutable por el agente con validación de esquema."""

    name: str
    description: str
    input_model: type[BaseModel]

    async def __call__(self, raw_input: dict[str, Any]) -> dict[str, Any]:
        """Valida la entrada y ejecuta la tool."""

        validated = validate_tool_input(self.input_model, raw_input)
        return await self.run(validated)

    @abstractmethod
    async def run(self, payload: BaseModel) -> dict[str, Any]:
        """Lógica concreta de la tool sobre la entrada ya validada."""

    def json_schema(self) -> dict[str, Any]:
        """Devuelve el JSON Schema de entrada para exponer al LLM."""

        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    """Registro central de tools disponibles para el orquestador."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.json_schema() for tool in self._tools.values()]
