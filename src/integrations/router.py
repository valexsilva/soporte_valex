"""Router de proveedores LLM (Punto 2: enrutamiento Devin/local).

Conmuta entre el proveedor primario (Devin) y el fallback (LLM local)
según configuración, aplicando degradación automática ante fallos.
"""

from __future__ import annotations

from typing import Any

from src.core.config import LLMProvider, Settings, get_settings
from src.core.exceptions import LLMProviderError
from src.integrations.base import LLMProviderProtocol, LLMResult
from src.integrations.devin.sessions import DevinProvider
from src.integrations.llm_local.provider import LocalLLMProvider


class LLMRouter:
    """Selecciona y orquesta los proveedores de inferencia."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._providers: dict[LLMProvider, LLMProviderProtocol] = {
            LLMProvider.DEVIN: DevinProvider(),
            LLMProvider.LOCAL: LocalLLMProvider(),
        }

    def _provider(self, key: LLMProvider) -> LLMProviderProtocol:
        return self._providers[key]

    async def complete(self, prompt: str, **kwargs: Any) -> LLMResult:
        """Invoca el proveedor primario con fallback automático.

        Permite override puntual del proveedor vía `provider` en kwargs
        (p.ej. desde el campo `ai_provider` del request).
        """

        override = kwargs.pop("provider", None)
        if override:
            primary = LLMProvider(override)
            fallback = (
                LLMProvider.LOCAL
                if primary == LLMProvider.DEVIN
                else LLMProvider.DEVIN
            )
        else:
            primary = self._settings.llm_primary
            fallback = self._settings.llm_fallback

        try:
            return await self._provider(primary).complete(prompt, **kwargs)
        except LLMProviderError:
            if fallback == primary:
                raise
            return await self._provider(fallback).complete(prompt, **kwargs)
