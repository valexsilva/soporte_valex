"""Aplicación FastAPI principal del sistema multi-agente Soporte Valex."""

from __future__ import annotations

from fastapi import FastAPI

from src.api import audit, devin, finops, ingestion, servicenow, teams
from src.core.config import get_settings


def create_app() -> FastAPI:
    """Crea y configura la aplicación FastAPI."""

    settings = get_settings()

    # Confía en la CA raíz del SO para TLS saliente (inspección corporativa).
    if settings.use_os_truststore:
        try:
            import truststore  # noqa: PLC0415

            truststore.inject_into_ssl()
        except Exception:  # noqa: BLE001
            pass
    app = FastAPI(
        title="Soporte Valex - Agente de Soporte Transversal",
        version="0.1.0",
        description=(
            "Orquestador ReAct con integración MCP Teams, Devin API y "
            "workflows Human-in-the-loop."
        ),
    )

    app.include_router(teams.router)
    app.include_router(devin.router)
    app.include_router(servicenow.router)
    app.include_router(ingestion.router)
    app.include_router(finops.router)
    app.include_router(audit.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "environment": settings.environment,
            "llm_primary": settings.llm_primary.value,
            "teams_mode": settings.teams_mode.value,
        }

    return app


app = create_app()
