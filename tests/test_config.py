"""Pruebas de configuración parametrizable (Punto 8)."""

from __future__ import annotations

from src.core.config import (
    IntegrationMode,
    LLMProvider,
    Settings,
)


def test_default_routing_devin_primary() -> None:
    # _env_file=None aisla los defaults del .env local del entorno.
    settings = Settings(_env_file=None)
    assert settings.llm_primary == LLMProvider.DEVIN
    assert settings.llm_fallback == LLMProvider.LOCAL


def test_teams_mode_webhook_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.teams_mode == IntegrationMode.WEBHOOK


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("REACT_MAX_CYCLES", "5")
    settings = Settings(_env_file=None)
    assert settings.react_max_cycles == 5
