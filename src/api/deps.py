"""Dependencias compartidas (singletons) de la capa API."""

from __future__ import annotations

from functools import lru_cache

from src.adapters.mcp_teams.adapter import TeamsAdapter
from src.agents.orchestrator.react_loop import AgentOrchestrator
from src.ingestion.background import IngestionManager


@lru_cache
def get_orchestrator() -> AgentOrchestrator:
    """Instancia singleton del orquestador."""

    return AgentOrchestrator()


@lru_cache
def get_teams_adapter() -> TeamsAdapter:
    """Instancia singleton del adapter de Teams."""

    return TeamsAdapter()


@lru_cache
def get_ingestion_manager() -> IngestionManager:
    """Instancia singleton del gestor de ingesta."""

    return IngestionManager()
