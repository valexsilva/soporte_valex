"""Endpoint de ingesta de logs hacia el pipeline de auditoría Kafka."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter

from src.workflows.audit import AuditLogger, build_audit_logger

router = APIRouter(prefix="/api/kafka", tags=["audit"])


@lru_cache
def _get_audit_logger() -> AuditLogger:
    """Inicializa el logger de auditoría de forma diferida (lazy)."""

    return build_audit_logger()


@router.post("/logs")
async def publish_log(event: dict[str, Any]) -> dict[str, Any]:
    """Publica un evento externo al tópico de auditoría."""

    await _get_audit_logger().log(
        event.get("session_id", "external"),
        event.get("event_type", "external_log"),
        event.get("payload", event),
    )
    return {"status": "published"}
