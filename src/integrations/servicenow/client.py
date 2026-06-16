"""Cliente de ServiceNow para la creación de folios.

Levanta folios cuando el diagnóstico concluye un problema de infraestructura
o cuando se escala un caso al Área correspondiente. Respeta ``servicenow_mode``:

- ``simulated``: genera un número de folio representativo sin llamadas externas.
- ``webhook`` / ``mcp``: realiza un POST real según ``servicenow.folio_method``:
    * ``incident``: a la tabla de incidentes (/api/now/table/{table}).
    * ``catalog`` : pide un item de Service Catalog vía order_now
      (/api/sn_sc/servicecatalog/items/{item}/order_now); devuelve un REQ.
  Autenticación según ``servicenow.auth``:
    * ``basic``: Basic Auth con usuario/contraseña (api_user/api_token).
    * ``oauth``: OAuth password grant (client_id/secret + usuario) -> Bearer.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from src.core.config import IntegrationMode, ServiceNowSettings, get_settings
from src.core.exceptions import IntegrationError
from src.integrations.servicenow.catalog import DEFAULT_INSTANCE_URL, build_guidance


class ServiceNowClient:
    """Crea folios en ServiceNow (real o simulado según configuración)."""

    def __init__(
        self,
        settings: ServiceNowSettings | None = None,
        mode: IntegrationMode | None = None,
    ) -> None:
        root = get_settings()
        self._settings = settings or root.servicenow
        self._mode = mode or root.servicenow_mode

    async def create_folio(
        self,
        *,
        short_description: str,
        description: str = "",
        component_name: str = "",
        environment: str = "",
        category: str | None = None,
        urgency: str = "medium",
        service: str = "",
    ) -> dict[str, Any]:
        """Crea un folio (o devuelve la guía manual) y sus datos."""

        category = category or self._settings.default_category

        # Modo 'guidance': no se crea el folio (sin API key); se devuelven los
        # pasos para que el usuario lo levante por sí mismo en el catálogo.
        if self._settings.folio_method.lower() == "guidance":
            return self._guidance_folio(
                service_hint=service or category,
                component_name=component_name,
                short_description=short_description,
                description=description,
            )

        payload = {
            "short_description": short_description,
            "description": description,
            "category": category,
            "urgency": urgency,
            "assignment_group": self._settings.default_assignment_group,
            "u_component": component_name,
            "u_environment": environment,
        }

        if self._mode == IntegrationMode.SIMULATED or not self._settings.instance_url:
            return self._simulated_folio(payload)

        if self._settings.folio_method.lower() == "catalog":
            return await self._order_catalog_item(description or short_description)
        return await self._create_remote(payload)

    def _guidance_folio(
        self,
        *,
        service_hint: str,
        component_name: str,
        short_description: str,
        description: str,
    ) -> dict[str, Any]:
        instance_url = self._settings.instance_url or DEFAULT_INSTANCE_URL
        contact = {
            k: v
            for k, v in self._settings.catalog_variables.items()
            if k in {"email", "phone"}
        }
        return build_guidance(
            service_hint=service_hint,
            component_name=component_name,
            short_description=short_description,
            description=description,
            instance_url=instance_url,
            contact=contact,
        )

    @staticmethod
    def _simulated_folio(payload: dict[str, Any]) -> dict[str, Any]:
        folio = f"INC{uuid4().hex[:8].upper()}"
        return {
            "folio": folio,
            "status": "created",
            "assignment_group": payload["assignment_group"],
            "category": payload["category"],
            "urgency": payload["urgency"],
            "simulated": True,
        }

    async def _create_remote(self, payload: dict[str, Any]) -> dict[str, Any]:
        base = self._settings.instance_url.rstrip("/")
        url = f"{base}/api/now/table/{self._settings.table}"
        data = await self._post(url, json=payload)
        result = data.get("result", data)
        return {
            "folio": result.get("number", ""),
            "sys_id": result.get("sys_id", ""),
            "status": "created",
            "assignment_group": payload["assignment_group"],
            "category": payload["category"],
            "urgency": payload["urgency"],
            "simulated": False,
        }

    async def _order_catalog_item(self, description: str) -> dict[str, Any]:
        """Crea el folio pidiendo un item de Service Catalog (order_now).

        Forma real en Santander: el folio es un REQ de sc_request. Las
        variables fijas (requested_for, product_service, type_of_request, ...)
        vienen de ``catalog_variables``; si hay ``catalog_description_variable``
        se añade la descripción del diagnóstico.
        """

        base = self._settings.instance_url.rstrip("/")
        item = self._settings.catalog_item_sysid
        if not item:
            raise IntegrationError(
                "ServiceNow catalog: falta SERVICENOW_CATALOG_ITEM_SYSID."
            )
        url = f"{base}/api/sn_sc/servicecatalog/items/{item}/order_now"

        variables = dict(self._settings.catalog_variables)
        if self._settings.catalog_description_variable and description:
            variables[self._settings.catalog_description_variable] = description
        payload = {
            "sysparm_quantity": self._settings.catalog_quantity,
            "variables": variables,
        }
        data = await self._post(url, json=payload)
        result = data.get("result", data)
        return {
            "folio": result.get("number", "")
            or result.get("request_number", ""),
            "sys_id": result.get("sys_id", ""),
            "table": result.get("table", "sc_request"),
            "status": "created",
            "simulated": False,
        }

    async def _post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        """POST autenticado (Basic u OAuth Bearer) que devuelve el JSON."""

        base = self._settings.instance_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=self._settings.timeout_seconds) as client:
                if self._settings.auth.lower() == "oauth":
                    token = await self._fetch_oauth_token(client, base)
                    headers = {"Authorization": f"Bearer {token}"}
                    response = await client.post(url, json=json, headers=headers)
                else:
                    auth = (self._settings.api_user, self._settings.api_token)
                    response = await client.post(url, json=json, auth=auth)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise IntegrationError(f"ServiceNow error: {exc}") from exc

    async def _fetch_oauth_token(self, client: httpx.AsyncClient, base: str) -> str:
        """Obtiene un access_token vía OAuth password grant de ServiceNow.

        Usa client_id/client_secret de la app registrada y api_user/api_token
        como credenciales del usuario (grant_type=password).
        """

        token_url = self._settings.oauth_token_url or f"{base}/oauth_token.do"
        form = {
            "grant_type": "password",
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret,
            "username": self._settings.api_user,
            "password": self._settings.api_token,
        }
        response = await client.post(token_url, data=form)
        response.raise_for_status()
        token = response.json().get("access_token", "")
        if not token:
            raise IntegrationError("ServiceNow OAuth: respuesta sin access_token.")
        return token
