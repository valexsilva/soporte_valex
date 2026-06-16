"""Proveedor LLM local (Llama 3 8B vía endpoint OpenAI-compatible)."""

from __future__ import annotations

from typing import Any

import httpx

from src.core.config import get_settings
from src.core.exceptions import LLMProviderError
from src.integrations.base import LLMResult


class LocalLLMProvider:
    """Proveedor de inferencia local (fallback) sobre endpoint vLLM."""

    name = "local"

    def __init__(self, endpoint: str | None = None) -> None:
        self._endpoint = endpoint or get_settings().local_llm_endpoint

    async def complete(self, prompt: str, **kwargs: Any) -> LLMResult:
        """Invoca el endpoint local con formato chat/completions."""

        url = f"{self._endpoint.rstrip('/')}/chat/completions"
        payload = {
            "model": kwargs.get("model", "llama3-8b"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.1),
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Local LLM error: {exc}") from exc

        text = ""
        choices = data.get("choices") or []
        if choices:
            text = choices[0].get("message", {}).get("content", "")

        return LLMResult(text=text, provider=self.name, raw=data)
