"""Schema Guard: validación estricta de payloads generados por el LLM.

Mitiga la alucinación estructural (doc sección 13.1). Si el modelo produce
un payload que no cumple el esquema de la tool, se bloquea la ejecución y
se devuelve la traza de error para forzar auto-corrección en el siguiente
ciclo ReAct.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from src.core.exceptions import SchemaValidationError


def validate_tool_input(model: type[BaseModel], payload: dict[str, Any]) -> BaseModel:
    """Valida `payload` contra un modelo Pydantic de entrada de tool.

    Args:
        model: clase Pydantic que define el esquema de entrada.
        payload: datos crudos generados por el LLM.

    Returns:
        Instancia validada del modelo.

    Raises:
        SchemaValidationError: con detalle del error sintáctico para
            reinyectar al modelo.
    """

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise SchemaValidationError(
            f"Payload inválido para {model.__name__}: {exc.errors()}"
        ) from exc
