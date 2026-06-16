"""Catálogo de ServiceNow (Order Guides) y generación de guía manual.

Mientras no haya credenciales de API (API key / ESM Integration) para crear
folios automáticamente, el agente devuelve los PASOS a seguir para que quien
reporta el problema levante la petición por sí mismo en el Catálogo Técnico.

Datos provistos por el negocio (instancia Santander):
- Order Guide "Middleware Services" -> Oracle, DB2, OpenShift (CaaS), Kafka.
- Order Guide "IaaS - Storage" -> Scality (S3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

DEFAULT_INSTANCE_URL = "https://santander.service-now.com"
# Catálogo técnico al que pertenecen estos Order Guides.
TECHNICAL_CATALOG_SYSID = "719aafd0db031f448c6c7cde3b9619f8"


@dataclass(frozen=True)
class OrderGuide:
    """Un Order Guide del catálogo y los servicios que ofrece."""

    key: str
    name: str
    guide_sysid: str
    services: tuple[str, ...]
    catalog_sysid: str = TECHNICAL_CATALOG_SYSID


# Order Guides conocidos.
ORDER_GUIDES: dict[str, OrderGuide] = {
    "middleware": OrderGuide(
        key="middleware",
        name="Middleware Services",
        guide_sysid="b6c0e9173374a61013cc7e282e5c7bbc",
        services=(
            "Oracle instance",
            "DB2 Subsystem",
            "DevOps para CaaS OpenShift",
            "Confluent - Kafka",
        ),
    ),
    "iaas_storage": OrderGuide(
        key="iaas_storage",
        name="Order Guide - IaaS - Storage",
        guide_sysid="ae1f26ffeb9bd2d0b5b5f30e8ad0cd01",
        services=("Scality para S3",),
    ),
}


@dataclass(frozen=True)
class ServiceRoute:
    """Ruta de un servicio: a qué Order Guide y opción corresponde."""

    guide_key: str
    service: str
    keywords: tuple[str, ...] = field(default_factory=tuple)


# Reglas de inferencia: palabra clave -> (Order Guide, servicio a seleccionar).
SERVICE_ROUTES: tuple[ServiceRoute, ...] = (
    ServiceRoute("middleware", "Oracle instance", ("oracle", "ora-", "hikari", "ora01")),
    ServiceRoute("middleware", "DB2 Subsystem", ("db2", "subsystem")),
    ServiceRoute(
        "middleware",
        "DevOps para CaaS OpenShift",
        ("openshift", "ocp", "caas", "pod", "deployment", "namespace", "crashloop"),
    ),
    ServiceRoute("middleware", "Confluent - Kafka", ("kafka", "confluent", "topic", "broker")),
    ServiceRoute("iaas_storage", "Scality para S3", ("s3", "scality", "bucket", "storage", "object")),
)


def build_guide_url(guide: OrderGuide, instance_url: str = DEFAULT_INSTANCE_URL) -> str:
    """Construye el enlace al Order Guide en el Catálogo Técnico (UI clásica)."""

    base = instance_url.rstrip("/")
    target = (
        "com.glideapp.servicecatalog_cat_item_guide_view.do"
        f"?v=1&sysparm_initial=true&sysparm_guide={guide.guide_sysid}"
        f"&sysparm_catalog={guide.catalog_sysid}"
        "&sysparm_catalog_view=catalog_technical_catalog"
    )
    return f"{base}/now/nav/ui/classic/params/target/{quote(target, safe='')}"


def resolve_service(text: str) -> ServiceRoute | None:
    """Infiera el servicio/Order Guide a partir del texto del problema."""

    haystack = (text or "").lower()
    for route in SERVICE_ROUTES:
        if any(kw in haystack for kw in route.keywords):
            return route
    return None


def build_guidance(
    *,
    service_hint: str = "",
    component_name: str = "",
    short_description: str = "",
    description: str = "",
    instance_url: str = DEFAULT_INSTANCE_URL,
    contact: dict[str, str] | None = None,
) -> dict[str, object]:
    """Genera los pasos para levantar la petición manualmente en ServiceNow.

    Si se identifica el servicio, apunta al Order Guide y opción concretos;
    si no, lista los Order Guides disponibles para que el usuario elija.
    """

    contact = contact or {}
    text = " ".join([service_hint, component_name, short_description, description])
    route = resolve_service(text)

    problem = short_description or description or "incidencia de servicio"
    common_tail = [
        "Completa los datos del formulario: 'Requested for' (tú), "
        "'Company requester' (Santander México), 'Product / Service', "
        "'Type of request' = Support, email y teléfono de contacto.",
        f"En la descripción/justificación indica el problema: {problem}.",
        "Pulsa 'Order Now' y guarda el número de folio (REQ...) que devuelve.",
    ]

    if route is not None:
        guide = ORDER_GUIDES[route.guide_key]
        url = build_guide_url(guide, instance_url)
        instructions = [
            "Entra al Catálogo Técnico de ServiceNow (requiere tu login SSO).",
            f"Abre el Order Guide '{guide.name}': {url}",
            f"Selecciona el servicio '{route.service}'.",
            *common_tail,
        ]
        return {
            "status": "manual_guidance",
            "automated": False,
            "service": route.service,
            "guide": guide.name,
            "guide_url": url,
            "instructions": instructions,
            "contact_hint": contact,
            "note": (
                "Conexión con ServiceNow preparada; pendiente la API key "
                "(ESM - Integration / API User) para automatizar la creación."
            ),
        }

    # Sin servicio identificado: ofrecer los Order Guides disponibles.
    options = [
        {
            "guide": g.name,
            "services": list(g.services),
            "guide_url": build_guide_url(g, instance_url),
        }
        for g in ORDER_GUIDES.values()
    ]
    instructions = [
        "Entra al Catálogo Técnico de ServiceNow (requiere tu login SSO).",
        "Elige el Order Guide y servicio que corresponda al problema "
        "(ver 'options').",
        *common_tail,
    ]
    return {
        "status": "manual_guidance",
        "automated": False,
        "service": None,
        "options": options,
        "instructions": instructions,
        "contact_hint": contact,
        "note": (
            "Conexión con ServiceNow preparada; pendiente la API key "
            "(ESM - Integration / API User) para automatizar la creación."
        ),
    }
