"""Configuración parametrizable del sistema.

Mapea los puntos de la matriz de atención (doc sección 14.1) a settings
tipados con Pydantic. Permite conmutar proveedores (LLM, integraciones,
estado) sin tocar código, solo variables de entorno.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _sub_config(prefix: str) -> SettingsConfigDict:
    """Config para sub-settings: lee del .env con el prefijo indicado."""

    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class IntegrationMode(str, Enum):
    """Modo de operación de un canal de integración."""

    SIMULATED = "simulated"
    WEBHOOK = "webhook"


class LLMProvider(str, Enum):
    """Proveedor de inferencia disponible."""

    DEVIN = "devin"
    LOCAL = "local"


class StateBackend(str, Enum):
    """Backend para persistencia de estados de workflow."""

    MEMORY = "memory"
    REDIS = "redis"


class AuditBackend(str, Enum):
    """Backend para auditoría de eventos del agente."""

    MEMORY = "memory"
    KAFKA = "kafka"


class DevinSettings(BaseSettings):
    """Configuración de la integración con Devin API (prioritaria)."""

    model_config = _sub_config("DEVIN_")

    api_base: str = "https://api.devin.ai/v3"
    org_id: str = ""
    api_key: str = ""
    timeout_seconds: float = 30.0
    poll_interval_seconds: float = 3.0
    poll_max_attempts: int = 40


class TeamsWebhookSettings(BaseSettings):
    """Webhooks de Teams (entrada/salida) con Adaptive Cards.

    - ``incoming_url``: URL del *Incoming Webhook* (o flujo de Workflows)
      del canal; el agente POSTea tarjetas aquí (SALIDA hacia Teams).
    - ``security_token``: token HMAC del *Outgoing Webhook* de Teams para
      validar las peticiones ENTRANTES (cuando @mencionan al webhook).
    """

    model_config = _sub_config("TEAMS_WEBHOOK_")

    incoming_url: str = ""
    security_token: str = ""
    timeout_seconds: float = 10.0
    # Palabra clave que dispara el flujo de Power Automate (ENTRADA). Para
    # evitar bucles, se neutraliza en TODA salida del agente hacia el canal
    # (se inserta un carácter invisible para romper la coincidencia literal).
    loop_guard_keyword: str = "SoporteGD"
    # Intervalo del poller que reanuda sesiones Devin en espera y publica la
    # respuesta final en el canal (segundos).
    poller_interval_seconds: float = 20.0


class TeamsEmailSettings(BaseSettings):
    """ENTRADA: leer notificaciones de Teams desde Outlook de escritorio (COM).

    El listener ``OutlookComListener`` se apoya en el Outlook ya autenticado en
    la máquina (Windows) para leer los correos de notificación de Teams
    (@menciones / actividad) y la respuesta del agente se publica de vuelta por
    el Incoming Webhook. No requiere IMAP ni credenciales.
    """

    model_config = _sub_config("TEAMS_EMAIL_")

    # Filtro del remitente de las notificaciones de Teams.
    sender_filter: str = "teams.microsoft.com"
    # Filtro por asunto (para flujos de Power Automate que reenvían el canal
    # al correo). Si se define, un correo coincide si su asunto lo contiene.
    subject_filter: str = ""
    poll_interval_seconds: float = 30.0
    # Prefijo de disparo: solo se procesan los mensajes cuyo texto comienza con
    # este prefijo (evita responder a chatter/ecos del propio bot en el canal).
    # El prefijo se elimina antes de pasar el texto al agente. Vacío = sin filtro.
    trigger_prefix: str = "SoporteGD"


class RedisSettings(BaseSettings):
    """Configuración de Redis para cache y estados HITL."""

    model_config = _sub_config("REDIS_")

    url: str = "redis://localhost:6379/0"
    state_ttl_seconds: int = 3600
    # Protocolo RESP: 3 (Redis >=6) o 2 (compatibilidad con servidores antiguos).
    protocol: int = 3


class KafkaSettings(BaseSettings):
    """Configuración de Kafka para auditoría asíncrona.

    Soporta PLAINTEXT (dev) y SASL_SSL/SSL/SASL_PLAINTEXT (corporativo).
    Para Kerberos (GSSAPI) usar sasl_mechanism=GSSAPI y definir el
    service name; el ticket Kerberos (keytab/principal vía krb5.conf) y el
    CA en formato PEM deben existir en el entorno de ejecución.
    """

    model_config = _sub_config("KAFKA_")

    bootstrap_servers: str = "localhost:9092"
    audit_topic: str = "agent-audit-logs"

    # Seguridad: PLAINTEXT | SSL | SASL_PLAINTEXT | SASL_SSL
    security_protocol: str = "PLAINTEXT"
    # SASL: PLAIN | SCRAM-SHA-256 | SCRAM-SHA-512 | GSSAPI
    sasl_mechanism: str = ""
    sasl_plain_username: str = ""
    sasl_plain_password: str = ""
    sasl_kerberos_service_name: str = ""
    # TLS: ruta a CA en formato PEM (convertir desde JKS si aplica)
    ssl_cafile: str = ""
    ssl_check_hostname: bool = True
    # Garantías de entrega del productor
    acks: str = "all"
    retries: int = 5
    request_timeout_ms: int = 15000


class OracleSettings(BaseSettings):
    """Configuración de Oracle para workflows y knowledge base."""

    model_config = _sub_config("ORACLE_")

    dsn: str = ""
    user: str = ""
    password: str = ""
    enabled: bool = False


class ServiceNowSettings(BaseSettings):
    """Configuración de ServiceNow para creación de folios (incidentes)."""

    model_config = _sub_config("SERVICENOW_")

    instance_url: str = ""
    # Para Basic Auth: api_user = usuario, api_token = contraseña/PIN.
    # Para OAuth (password grant): api_user/api_token son las credenciales del
    # usuario y client_id/client_secret las de la app OAuth registrada.
    api_user: str = ""
    api_token: str = ""
    timeout_seconds: float = 15.0
    # Autenticación: 'basic' (usuario+contraseña) u 'oauth' (token bearer).
    auth: str = "basic"
    # OAuth (ServiceNow Application Registry -> Endpoint for external clients).
    client_id: str = ""
    client_secret: str = ""
    # URL del token OAuth; por defecto {instance_url}/oauth_token.do.
    oauth_token_url: str = ""
    # Método de creación de folio:
    #  - 'incident': POST a /api/now/table/{table}.
    #  - 'catalog' : POST a /api/sn_sc/servicecatalog/items/{item}/order_now
    #    (forma real en Santander; devuelve un REQ de sc_request).
    folio_method: str = "incident"
    # Tabla/endpoint de incidentes y valores por defecto del folio.
    table: str = "incident"
    default_category: str = "infrastructure"
    default_assignment_group: str = "Area-X"
    # --- Service Catalog (folio_method='catalog') ---
    # sys_id del catalog item (p. ej. 'Middleware Services').
    catalog_item_sysid: str = ""
    catalog_quantity: str = "1"
    # Variables fijas del item (sys_ids/valores propios de la instancia). JSON:
    # SERVICENOW_CATALOG_VARIABLES={"requested_for":"...","company_requester":"...","product_service":"...","type_of_request":"...","email":"...","phone":"..."}
    catalog_variables: dict[str, str] = Field(default_factory=dict)
    # Nombre de la variable del item donde volcar la descripción (si existe).
    catalog_description_variable: str = ""


class OpenShiftMode(str, Enum):
    """Modo de operación de la integración con OpenShift."""

    SIMULATED = "simulated"
    CLI = "cli"


class OpenShiftSettings(BaseSettings):
    """Configuración de OpenShift vía CLI 'oc' (diagnóstico de pods/eventos/logs)."""

    model_config = _sub_config("OPENSHIFT_")

    # Ruta al binario 'oc' (o nombre si está en el PATH).
    oc_path: str = "oc"
    # Ruta opcional a un kubeconfig; si se define, se exporta como KUBECONFIG.
    kubeconfig: str = ""
    # Contextos 'oc' por entorno (un contexto = un clúster). Un entorno puede
    # tener varios clústeres (mx1/mx2): se consultan todos y se agregan. El
    # namespace se pasa con --namespace (los contextos dan acceso a varios
    # proyectos). JSON en OPENSHIFT_ENV_CONTEXTS. Ejemplo:
    # {"dev": ["dev-str01-mx1"], "pre": ["pre-mex02-mx1", "pre-mex02-mx2"]}
    env_contexts: dict[str, list[str]] = Field(default_factory=dict)
    # Plantilla de namespace por componente/entorno (respaldo cuando no hay
    # entrada en component_map). En estos clústeres el patrón es mx-<comp>-<env>.
    namespace_template: str = "mx-{component}-{environment}"
    # Override por componente -> entorno -> {contexts?, namespace?, deployment?}.
    # 'contexts' reemplaza los env_contexts (p. ej. apigateway vive en ocp04);
    # 'namespace' fija el proyecto; 'deployment' el nombre para 'oc logs'.
    # JSON en OPENSHIFT_COMPONENT_MAP. Ejemplo (una línea):
    # {"apigateway":{"pre":{"contexts":["pre-ocp04-mx1","pre-ocp04-mx2"],"namespace":"mx-api-gateway-pre"}}}
    component_map: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)
    tail_lines: int = 100
    timeout_seconds: float = 20.0


class Settings(BaseSettings):
    """Settings raíz del sistema multi-agente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = "soporte-valex"
    environment: str = "dev"

    # Usa el almacen de certificados del SO para TLS saliente (CA corporativa).
    use_os_truststore: bool = True

    # Punto 1: Integraciones
    teams_mode: IntegrationMode = IntegrationMode.WEBHOOK
    servicenow_mode: IntegrationMode = IntegrationMode.SIMULATED
    openshift_mode: OpenShiftMode = OpenShiftMode.SIMULATED

    # Punto 2: Enrutamiento LLM (Devin prioritario, local fallback)
    llm_primary: LLMProvider = LLMProvider.DEVIN
    llm_fallback: LLMProvider = LLMProvider.LOCAL
    # Devin es un agente autónomo de larga duración: cuando es el proveedor,
    # se despacha de forma asíncrona (la sesión se reanuda vía callback) en
    # lugar de bloquear el bucle ReAct haciendo polling.
    devin_async: bool = True

    # Punto 3 / 4: Estado y auditoría
    state_backend: StateBackend = StateBackend.REDIS
    audit_backend: AuditBackend = AuditBackend.KAFKA

    # Punto 5: Control del bucle ReAct
    react_max_cycles: int = 3
    react_confidence_threshold: float = 0.9

    # LLM local fallback
    local_llm_endpoint: str = "http://localhost:8000/v1"

    # Sub-configuraciones
    devin: DevinSettings = Field(default_factory=DevinSettings)
    teams_webhook: TeamsWebhookSettings = Field(default_factory=TeamsWebhookSettings)
    teams_email: TeamsEmailSettings = Field(default_factory=TeamsEmailSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    oracle: OracleSettings = Field(default_factory=OracleSettings)
    servicenow: ServiceNowSettings = Field(default_factory=ServiceNowSettings)
    openshift: OpenShiftSettings = Field(default_factory=OpenShiftSettings)


@lru_cache
def get_settings() -> Settings:
    """Devuelve la instancia singleton de configuración."""

    return Settings()
