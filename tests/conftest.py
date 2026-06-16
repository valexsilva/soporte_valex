"""Fixtures y dobles de prueba compartidos."""

from __future__ import annotations

import pytest

from src.core.config import (
    AuditBackend,
    LLMProvider,
    OpenShiftSettings,
    ServiceNowSettings,
    Settings,
    StateBackend,
)
from src.integrations.base import LLMResult


class StubLLMRouter:
    """Router de LLM falso que devuelve decisiones predefinidas en orden."""

    def __init__(self, scripted: list[str]) -> None:
        self._scripted = scripted
        self._index = 0

    async def complete(self, prompt: str, **kwargs: object) -> LLMResult:  # noqa: ARG002
        text = self._scripted[min(self._index, len(self._scripted) - 1)]
        self._index += 1
        return LLMResult(text=text, provider="stub", confidence=1.0)


@pytest.fixture
def test_settings() -> Settings:
    """Settings con backends en memoria para pruebas deterministas."""

    return Settings(
        _env_file=None,
        state_backend=StateBackend.MEMORY,
        audit_backend=AuditBackend.MEMORY,
        llm_primary=LLMProvider.LOCAL,
        llm_fallback=LLMProvider.LOCAL,
        react_max_cycles=3,
        # Sub-configuraciones herméticas (no leen el .env del desarrollador).
        servicenow=ServiceNowSettings(_env_file=None),
        openshift=OpenShiftSettings(_env_file=None),
    )
