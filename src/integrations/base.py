"""Interfaz común de proveedores de inferencia (LLM)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class LLMResult(BaseModel):
    """Resultado normalizado de una invocación a un proveedor LLM."""

    text: str
    provider: str
    confidence: float = 1.0
    raw: dict | None = None


@runtime_checkable
class LLMProviderProtocol(Protocol):
    """Contrato que deben cumplir todos los proveedores de inferencia."""

    name: str

    async def complete(self, prompt: str, **kwargs: object) -> LLMResult:
        """Genera una respuesta a partir de un prompt."""
        ...
