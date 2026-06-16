"""Pipeline de auditoría asíncrona (doc sección 13.2).

Publica cada pensamiento, payload y observación al tópico Kafka
`agent-audit-logs` de forma no bloqueante. Backend conmutable a memoria
para desarrollo/tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol

from src.core.config import AuditBackend, Settings, get_settings


class AuditSink(Protocol):
    """Contrato de destino de eventos de auditoría."""

    async def emit(self, event: dict[str, Any]) -> None: ...


class InMemoryAuditSink:
    """Sink en memoria para desarrollo y pruebas."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class KafkaAuditSink:
    """Sink que publica eventos al tópico de auditoría en Kafka."""

    def __init__(self, settings: Settings | None = None) -> None:
        from kafka import KafkaProducer  # noqa: PLC0415

        cfg = settings or get_settings()
        self._topic = cfg.kafka.audit_topic
        self._producer = KafkaProducer(**self._build_producer_config(cfg))

    @staticmethod
    def _build_producer_config(cfg: Settings) -> dict[str, Any]:
        """Construye los kwargs del productor según el protocolo de seguridad."""

        k = cfg.kafka
        config: dict[str, Any] = {
            "bootstrap_servers": [s.strip() for s in k.bootstrap_servers.split(",")],
            "value_serializer": lambda v: json.dumps(v).encode("utf-8"),
            "security_protocol": k.security_protocol,
            "acks": k.acks,
            "retries": k.retries,
            "request_timeout_ms": k.request_timeout_ms,
        }

        # TLS para protocolos SSL / SASL_SSL.
        if "SSL" in k.security_protocol:
            config["ssl_check_hostname"] = k.ssl_check_hostname
            if k.ssl_cafile:
                config["ssl_cafile"] = k.ssl_cafile

        # Autenticación SASL.
        if k.security_protocol.startswith("SASL"):
            config["sasl_mechanism"] = k.sasl_mechanism
            if k.sasl_mechanism == "GSSAPI":
                config["sasl_kerberos_service_name"] = k.sasl_kerberos_service_name
            else:
                config["sasl_plain_username"] = k.sasl_plain_username
                config["sasl_plain_password"] = k.sasl_plain_password

        return config

    async def emit(self, event: dict[str, Any]) -> None:
        self._producer.send(self._topic, event)


class AuditLogger:
    """Fachada de auditoría que normaliza y despacha eventos."""

    def __init__(self, sink: AuditSink) -> None:
        self._sink = sink

    async def log(
        self, session_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        await self._sink.emit(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "event_type": event_type,
                "payload": payload,
            }
        )


def build_audit_logger(settings: Settings | None = None) -> AuditLogger:
    """Crea el logger de auditoría según el backend configurado."""

    cfg = settings or get_settings()
    if cfg.audit_backend == AuditBackend.KAFKA:
        return AuditLogger(KafkaAuditSink(cfg))
    return AuditLogger(InMemoryAuditSink())
