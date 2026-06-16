"""Cliente de OpenShift basado en el CLI 'oc'.

Ejecuta el binario ``oc`` como subproceso para diagnosticar componentes:
estado de pods, eventos y logs. Cada componente/entorno se asocia a una o más
contextos de ``oc`` (``--context``); cada contexto fija el clúster y el
namespace (proyecto). Cuando un entorno tiene varios clústeres (mx1/mx2), se
consulta cada uno y se agregan los resultados.

No requiere SDK de Kubernetes: se apoya en el ``oc`` ya instalado y autenticado
(o en un ``KUBECONFIG`` indicado en la configuración).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Awaitable, Callable

from src.core.config import OpenShiftSettings, get_settings

# Runner: recibe los argumentos de 'oc' y devuelve (returncode, stdout, stderr).
Runner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]


class OpenShiftCliClient:
    """Diagnóstico de OpenShift ejecutando comandos ``oc``."""

    def __init__(
        self,
        settings: OpenShiftSettings | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._settings = settings or get_settings().openshift
        self._run = runner or self._default_runner

    async def _default_runner(self, args: list[str]) -> tuple[int, str, str]:
        env = os.environ.copy()
        if self._settings.kubeconfig:
            env["KUBECONFIG"] = self._settings.kubeconfig
        proc = await asyncio.create_subprocess_exec(
            self._settings.oc_path,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=self._settings.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            return 124, "", "Tiempo de espera agotado ejecutando 'oc'."
        return (
            proc.returncode or 0,
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
        )

    def _resolve(
        self, component: str, environment: str, override_ns: str | None
    ) -> tuple[list[str], str, str]:
        """Devuelve (contextos, namespace, deployment) para el componente/entorno.

        - contextos: del component_map[componente][entorno]['contexts'] si existe;
          si no, los env_contexts del entorno (clústeres mx1/mx2).
        - namespace: override explícito > component_map 'namespace' > plantilla
          mx-{component}-{environment}.
        - deployment: component_map 'deployment' > nombre del componente.
        """

        entry = self._lookup(self._settings.component_map, component)
        env_entry = entry.get(environment, {}) if isinstance(entry, dict) else {}

        contexts = env_entry.get("contexts") or self._settings.env_contexts.get(
            environment, []
        )

        namespace = override_ns or env_entry.get("namespace") or ""
        if not namespace:
            template = self._settings.namespace_template
            namespace = (
                template.format(component=component, environment=environment)
                if template
                else ""
            )

        deployment = env_entry.get("deployment") or component
        return list(contexts), namespace, deployment

    @staticmethod
    def _lookup(cmap: dict[str, Any], component: str) -> Any:
        """Busca el componente en un map (match exacto en minúsculas o subcadena)."""

        if not cmap:
            return None
        key = component.lower()
        if key in cmap:
            return cmap[key]
        for name, entry in cmap.items():
            if name.lower() in key or key in name.lower():
                return entry
        return None

    @staticmethod
    def _base_args(context: str, namespace: str | None) -> list[str]:
        args: list[str] = []
        if context:
            args += ["--context", context]
        if namespace:
            args += ["--namespace", namespace]
        return args

    async def diagnostics(
        self,
        *,
        component_name: str,
        environment: str,
        resource: str = "pods",
        namespace: str | None = None,
        tail_lines: int | None = None,
    ) -> dict[str, Any]:
        """Ejecuta el diagnóstico en cada clúster del entorno y agrega resultados."""

        result: dict[str, Any] = {
            "component_name": component_name,
            "environment": environment,
            "resource": resource,
            "simulated": False,
        }

        if environment == "pro":
            result.update(
                {
                    "access": "denied",
                    "permissions_limited": True,
                    "findings": [],
                    "clusters": [],
                    "note": (
                        "OpenShift no se usa para diagnóstico en pro. Utiliza "
                        "Dynatrace en modo solo lectura."
                    ),
                }
            )
            return result

        result["permissions_limited"] = environment == "pre"
        contexts, ns, deployment = self._resolve(
            component_name, environment, namespace
        )
        result["namespace"] = ns
        if not contexts:
            result.update(
                {
                    "access": "not_configured",
                    "findings": [],
                    "clusters": [],
                    "note": (
                        f"No hay contexto 'oc' configurado para "
                        f"'{component_name}' en {environment}."
                    ),
                }
            )
            return result

        clusters: list[dict[str, Any]] = []
        for context in contexts:
            clusters.append(
                await self._diagnose_context(
                    context, resource, ns, deployment, tail_lines,
                )
            )

        # Acceso global: granted si algún clúster respondió; restricted si todos
        # fueron denegados por RBAC; si no, error.
        statuses = {c["access"] for c in clusters}
        if "granted" in statuses:
            access = "granted"
        elif statuses == {"restricted"}:
            access = "restricted"
        else:
            access = "error" if "error" in statuses else statuses.pop()

        findings: list[dict[str, Any]] = []
        for cluster in clusters:
            for finding in cluster.get("findings", []):
                findings.append({**finding, "context": cluster["context"]})

        result.update({"access": access, "clusters": clusters, "findings": findings})
        return result

    async def _diagnose_context(
        self,
        context: str,
        resource: str,
        namespace: str | None,
        deployment: str,
        tail_lines: int | None,
    ) -> dict[str, Any]:
        """Diagnóstico contra un único contexto/clúster."""

        base: dict[str, Any] = {"context": context, "namespace": namespace or ""}
        args = self._base_args(context, namespace)

        if resource == "logs":
            tail = tail_lines or self._settings.tail_lines
            rc, out, err = await self._run(
                args + ["logs", f"deployment/{deployment}", f"--tail={tail}"]
            )
            return self._finish_logs(base, rc, out, err)

        kind = "events" if resource == "events" else "pods"
        rc, out, err = await self._run(args + ["get", kind, "-o", "json"])
        return self._finish_get(base, kind, rc, out, err)

    @staticmethod
    def _access_error(base: dict[str, Any], rc: int, err: str) -> dict[str, Any]:
        # 'oc' usa exit code 1 también para RBAC; detectamos negación por mensaje.
        lowered = err.lower()
        restricted = (
            "forbidden" in lowered
            or "cannot " in lowered
            or "unauthorized" in lowered
        )
        base.update(
            {
                "access": "restricted" if restricted else "error",
                "findings": [],
                "note": err.strip() or f"'oc' devolvió código {rc}.",
            }
        )
        return base

    def _finish_logs(
        self, base: dict[str, Any], rc: int, out: str, err: str
    ) -> dict[str, Any]:
        if rc != 0:
            return self._access_error(base, rc, err)
        lines = [line for line in out.splitlines() if line.strip()]
        base["access"] = "granted"
        base["findings"] = [{"line": line} for line in lines]
        return base

    def _finish_get(
        self, base: dict[str, Any], kind: str, rc: int, out: str, err: str
    ) -> dict[str, Any]:
        if rc != 0:
            return self._access_error(base, rc, err)
        try:
            data = json.loads(out or "{}")
        except json.JSONDecodeError:
            base.update({"access": "error", "findings": [], "note": "JSON inválido de 'oc'."})
            return base

        items = data.get("items", []) if isinstance(data, dict) else []
        base["access"] = "granted"
        base["findings"] = (
            self._parse_pods(items) if kind == "pods" else self._parse_events(items)
        )
        return base

    @staticmethod
    def _parse_pods(items: list[Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata", {})
            status = item.get("status", {})
            containers = status.get("containerStatuses", []) or []
            restarts = sum(int(c.get("restartCount", 0)) for c in containers)
            ready_n = sum(1 for c in containers if c.get("ready"))
            findings.append(
                {
                    "pod": meta.get("name", ""),
                    "phase": status.get("phase", ""),
                    "ready": f"{ready_n}/{len(containers)}" if containers else "0/0",
                    "restarts": restarts,
                }
            )
        return findings

    @staticmethod
    def _parse_events(items: list[Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            findings.append(
                {
                    "type": item.get("type", ""),
                    "reason": item.get("reason", ""),
                    "message": item.get("message", ""),
                    "count": int(item.get("count", 0) or 0),
                }
            )
        return findings
