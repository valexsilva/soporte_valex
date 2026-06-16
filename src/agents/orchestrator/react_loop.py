"""Orquestador ReAct: ciclo Thought -> Action -> Observation.

Coordina el razonamiento del LLM (Devin/local), la ejecución de tools con
Schema Guard, la suspensión Human-in-the-loop y el escalamiento al Área X
tras el límite de ciclos (doc secciones 3.2, 5.1, 5.2).
"""

from __future__ import annotations

from typing import Any

from src.agents.orchestrator.parser import LLMDecision, parse_decision
from src.agents.orchestrator.prompts import (
    CONTEXT_TEMPLATE,
    build_system_prompt,
)
from src.core.config import LLMProvider, Settings, get_settings
from src.core.exceptions import SchemaValidationError
from src.core.models import (
    AgentRequest,
    AgentResponse,
    AgentSession,
    ReActStep,
    SessionStatus,
    StepType,
)
from src.integrations.devin.sessions import DevinProvider
from src.integrations.router import LLMRouter
from src.integrations.servicenow.client import ServiceNowClient
from src.tools.base import ToolRegistry
from src.tools.registry import build_default_registry
from src.workflows.approval import build_approval_request, requires_approval
from src.workflows.audit import AuditLogger, build_audit_logger
from src.workflows.folio_assistant import FolioAssistant
from src.workflows.state_manager import SessionStore, build_session_store


class AgentOrchestrator:
    """Orquestador principal del sistema multi-agente."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        router: LLMRouter | None = None,
        tools: ToolRegistry | None = None,
        store: SessionStore | None = None,
        audit: AuditLogger | None = None,
        devin: DevinProvider | None = None,
        servicenow: ServiceNowClient | None = None,
        folio_assistant: FolioAssistant | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._router = router or LLMRouter(self._settings)
        self._tools = tools or build_default_registry()
        self._store = store or build_session_store(self._settings)
        self._audit = audit or build_audit_logger(self._settings)
        self._devin: DevinProvider | None = devin or self._resolve_devin(self._router)
        self._servicenow = servicenow or ServiceNowClient(
            self._settings.servicenow, self._settings.servicenow_mode
        )
        self._folio = folio_assistant or FolioAssistant(settings=self._settings)

    @staticmethod
    def _resolve_devin(router: Any) -> DevinProvider | None:
        """Obtiene el proveedor Devin del router si existe (sin forzar creación)."""

        providers = getattr(router, "_providers", None)
        if providers and LLMProvider.DEVIN in providers:
            prov = providers[LLMProvider.DEVIN]
            if isinstance(prov, DevinProvider):
                return prov
        return None

    def _devin_provider(self) -> DevinProvider:
        """Devuelve el proveedor Devin, creándolo perezosamente si hace falta."""

        if self._devin is None:
            self._devin = DevinProvider(settings=self._settings.devin)
        return self._devin

    def _provider_for(self, session: AgentSession) -> LLMProvider:
        override = session.request.ai_provider
        if override:
            return LLMProvider(override)
        return self._settings.llm_primary

    def _is_devin_async(self, session: AgentSession) -> bool:
        """True si la sesión debe usar el despacho asíncrono a Devin."""

        return (
            self._settings.devin_async
            and self._provider_for(session) == LLMProvider.DEVIN
        )

    # ---- API pública --------------------------------------------------

    async def handle(self, request: AgentRequest) -> AgentResponse:
        """Procesa una solicitud nueva creando una sesión y ejecutando ReAct."""

        # Asistente de folio (multi-turno): si hay un folio en curso para el
        # usuario o pide ayuda para levantarlo, se atiende de forma
        # conversacional sin pasar por el bucle ReAct.
        folio_resp = await self._folio.handle(request)
        if folio_resp is not None:
            await self._audit.log(
                folio_resp.session_id, "folio_assistant", {"user": request.user_id}
            )
            return folio_resp

        session = AgentSession(request=request)
        await self._store.save(session)
        await self._audit.log(
            session.session_id, "session_created", request.model_dump()
        )
        return await self._run(session, context="")

    async def resume(
        self, session_id: str, *, approved: bool, user_choice: str = ""
    ) -> AgentResponse:
        """Reanuda una sesión suspendida tras una decisión humana (HITL)."""

        session = await self._store.load(session_id)
        await self._audit.log(
            session_id,
            "approval_decision",
            {"approved": approved, "user_choice": user_choice},
        )

        if not approved:
            session.status = SessionStatus.COMPLETED
            session.steps.append(
                ReActStep(
                    type=StepType.OBSERVATION,
                    content="Acción rechazada por el administrador. Flujo cerrado.",
                )
            )
            await self._store.save(session)
            return self._build_response(
                session, "La acción fue rechazada por el administrador."
            )

        # Aprobada: ejecutar la acción pendiente.
        return await self._execute_pending_action(session, user_choice)

    async def resume_devin(self, session_id: str) -> AgentResponse:
        """Reanuda una sesión que esperaba el resultado de Devin (Opción A).

        Consulta el estado de la sesión Devin asociada; si sigue en curso,
        responde 'en progreso'. Si terminó, integra el resultado como la
        decisión del ciclo actual y continúa el bucle ReAct.
        """

        session = await self._store.load(session_id)
        if session.status != SessionStatus.WAITING_DEVIN:
            return self._build_response(
                session, "La sesión no está esperando a Devin."
            )

        result = await self._devin_provider().poll_result(
            session.devin_session_id or ""
        )
        if result is None:
            await self._audit.log(
                session_id, "devin_polled", {"status": "in_progress"}
            )
            return self._in_progress_response(
                session, {"session_id": session.devin_session_id, "url": None}
            )

        await self._audit.log(session_id, "devin_result", result.model_dump())
        decision = parse_decision(result.text)
        await self._record_decision(session, decision)

        resp = await self._apply_decision(session, decision)
        if resp is not None:
            return resp

        # La tool continuó el flujo: avanzar al siguiente ciclo de razonamiento.
        return await self._loop(session, context="")

    # ---- Núcleo ReAct -------------------------------------------------

    async def _run(self, session: AgentSession, *, context: str) -> AgentResponse:
        return await self._loop(session, context=context)

    async def _loop(self, session: AgentSession, *, context: str) -> AgentResponse:
        """Avanza el bucle ReAct hasta un estado terminal o de espera.

        Para proveedores síncronos ejecuta varios ciclos seguidos. Para Devin
        (asíncrono) cada ciclo despacha la sesión y suspende con WAITING_DEVIN;
        el bucle se reanuda vía `resume_devin`.
        """

        while session.cycle_count < self._settings.react_max_cycles:
            outcome = await self._reason(session, context)
            if isinstance(outcome, AgentResponse):
                return outcome  # despacho async a Devin (en progreso)

            decision = outcome
            await self._record_decision(session, decision)
            resp = await self._apply_decision(session, decision)
            if resp is not None:
                return resp
            # Tool ejecutada: continuar con el siguiente ciclo.

        # Límite de ciclos alcanzado -> escalar.
        return await self._escalate(session, None)

    async def _reason(
        self, session: AgentSession, context: str
    ) -> AgentResponse | LLMDecision:
        """Obtiene la siguiente decisión del LLM o despacha a Devin (async)."""

        session.cycle_count += 1
        system_prompt = build_system_prompt(
            self._tools.schemas(),
            self._settings.react_max_cycles,
            self._settings.react_confidence_threshold,
        )
        prompt = self._compose_prompt(system_prompt, session, context)

        if self._is_devin_async(session):
            info = await self._devin_provider().start(
                prompt, session_id=session.devin_session_id
            )
            session.devin_session_id = info.get("session_id")
            session.status = SessionStatus.WAITING_DEVIN
            await self._store.save(session)
            await self._audit.log(session.session_id, "devin_dispatched", info)
            return self._in_progress_response(session, info)

        llm_result = await self._router.complete(
            prompt,
            provider=session.request.ai_provider,
            session_id=session.devin_session_id,
        )
        if llm_result.raw and "session_id" in (llm_result.raw or {}):
            session.devin_session_id = llm_result.raw["session_id"]
        return parse_decision(llm_result.text)

    async def _record_decision(
        self, session: AgentSession, decision: LLMDecision
    ) -> None:
        session.steps.append(
            ReActStep(type=StepType.THOUGHT, content=decision.thought)
        )
        await self._audit.log(session.session_id, "thought", decision.model_dump())

    async def _apply_decision(
        self, session: AgentSession, decision: LLMDecision
    ) -> AgentResponse | None:
        """Aplica una decisión del LLM. Devuelve respuesta terminal o None."""

        # Escalamiento explícito o por baja certidumbre.
        if decision.action == "escalate" or (
            decision.confidence < self._settings.react_confidence_threshold
            and decision.action == "final"
        ):
            return await self._escalate(session, decision)

        if decision.action == "final":
            session.status = SessionStatus.COMPLETED
            await self._store.save(session)
            return self._build_response(session, decision.final_answer)

        if decision.action == "tool":
            return await self._handle_tool(session, decision)

        # Acción no reconocida: cerrar de forma segura.
        session.status = SessionStatus.COMPLETED
        await self._store.save(session)
        return self._build_response(
            session, decision.final_answer or decision.thought
        )

    async def _handle_tool(
        self, session: AgentSession, decision: LLMDecision
    ) -> AgentResponse | None:
        """Ejecuta una tool o suspende el flujo si requiere aprobación.

        Devuelve un AgentResponse si el flujo se suspende/termina; None si
        debe continuar el bucle ReAct.
        """

        tool = self._tools.get(decision.tool_name or "")
        if tool is None:
            session.steps.append(
                ReActStep(
                    type=StepType.OBSERVATION,
                    content=f"Tool desconocida: {decision.tool_name}",
                )
            )
            return None

        inputs = decision.tool_inputs()
        if not inputs:
            session.steps.append(
                ReActStep(
                    type=StepType.OBSERVATION,
                    content=f"tool_input vacío o inválido para {decision.tool_name}.",
                    tool_name=decision.tool_name,
                )
            )
            await self._store.save(session)
            return None

        # Human-in-the-loop: si alguna entrada requiere aprobación, suspender
        # en esa acción sensible antes de ejecutar nada.
        for tool_input in inputs:
            if decision.tool_name == "execute_pipeline_action" and requires_approval(
                tool_input.get("action", ""), session.request.environment
            ):
                session.status = SessionStatus.SUSPENDED
                session.pending_action = {
                    "tool_name": decision.tool_name,
                    "tool_input": tool_input,
                }
                await self._store.save(session)
                approval = build_approval_request(session, tool_input)
                await self._audit.log(
                    session.session_id,
                    "suspended_for_approval",
                    approval.model_dump(),
                )
                return self._build_response(
                    session,
                    "Acción de mitigación pendiente de aprobación de Administrador.",
                    requires_approval=True,
                    extra={"approval": approval.model_dump()},
                )

        # Ejecución directa (read-only / sin aprobación) con Schema Guard.
        # Soporta varias entradas en paralelo emitidas por el modelo.
        for tool_input in inputs:
            try:
                output = await tool(tool_input)
            except SchemaValidationError as exc:
                # Reinyectar el error para auto-corrección en el siguiente ciclo.
                session.steps.append(
                    ReActStep(
                        type=StepType.OBSERVATION,
                        content=f"Error de esquema: {exc}",
                        tool_name=decision.tool_name,
                        tool_input=tool_input,
                    )
                )
                continue

            session.steps.append(
                ReActStep(
                    type=StepType.ACTION,
                    content=f"Ejecutando {decision.tool_name}",
                    tool_name=decision.tool_name,
                    tool_input=tool_input,
                )
            )
            session.steps.append(
                ReActStep(
                    type=StepType.OBSERVATION,
                    content="Resultado de tool obtenido.",
                    tool_name=decision.tool_name,
                    tool_output=output,
                )
            )
            await self._audit.log(
                session.session_id, "tool_executed",
                {"tool": decision.tool_name, "output": output},
            )

        await self._store.save(session)
        return None

    async def _execute_pending_action(
        self, session: AgentSession, user_choice: str
    ) -> AgentResponse:
        """Ejecuta la acción pendiente tras la aprobación humana."""

        pending = session.pending_action or {}
        tool = self._tools.get(pending.get("tool_name", ""))
        if tool is None:
            session.status = SessionStatus.FAILED
            await self._store.save(session)
            return self._build_response(session, "No hay acción pendiente válida.")

        output = await tool(pending.get("tool_input", {}))
        session.steps.append(
            ReActStep(
                type=StepType.ACTION,
                content=f"Acción aprobada por administrador ({user_choice}).",
                tool_name=pending.get("tool_name"),
                tool_input=pending.get("tool_input"),
                tool_output=output,
            )
        )
        session.status = SessionStatus.COMPLETED
        session.pending_action = None
        await self._store.save(session)
        await self._audit.log(
            session.session_id, "pending_action_executed", output
        )
        return self._build_response(
            session, "Acción de mitigación ejecutada tras aprobación."
        )

    async def _escalate(
        self, session: AgentSession, decision: LLMDecision | None
    ) -> AgentResponse:
        """Escala el caso al Área X vía ServiceNow (doc 3.2 / 5.2)."""

        session.status = SessionStatus.ESCALATED
        reason = (
            "Límite de ciclos ReAct alcanzado sin certidumbre suficiente."
            if decision is None
            else "Certidumbre insuficiente; se requiere intervención humana."
        )
        session.steps.append(
            ReActStep(type=StepType.OBSERVATION, content=reason)
        )

        # Levanta un folio real en ServiceNow para el Área correspondiente.
        req = session.request
        detail = (decision.final_answer if decision else "") or ""
        folio = await self._servicenow.create_folio(
            short_description=(
                f"Escalamiento soporte transversal: "
                f"{req.component_name or 'componente no especificado'}"
            ),
            description=f"{reason}\n{detail}".strip(),
            component_name=req.component_name or "",
            environment=req.environment.value,
            category="infrastructure",
        )
        folio_number = folio.get("folio", "")
        is_guidance = folio.get("status") == "manual_guidance"
        session.steps.append(
            ReActStep(
                type=StepType.ACTION,
                content=(
                    "Guía para levantar la petición en ServiceNow"
                    if is_guidance
                    else "Folio de ServiceNow creado"
                ),
                tool_name="create_servicenow_folio",
                tool_output=folio,
            )
        )
        await self._store.save(session)
        await self._audit.log(
            session.session_id,
            "escalated",
            {"reason": reason, "folio": folio_number or folio.get("status", "")},
        )

        # En modo 'guidance' (sin API key) no hay folio automático: se entregan
        # los pasos para que quien reporta levante la petición por sí mismo.
        if is_guidance:
            message = self._format_guidance(folio)
        else:
            message = (
                f"He escalado el caso al Área X mediante el folio {folio_number} "
                "en ServiceNow."
            )
        # Si el agente aportó una aclaración o respuesta parcial al escalar
        # (p. ej. pedir un dato faltante), se incluye para no perderla.
        if detail.strip():
            message = f"{detail.strip()}\n\n---\n{message}"
        return self._build_response(
            session, message, extra={"folio": folio}
        )

    @staticmethod
    def _format_guidance(folio: dict[str, Any]) -> str:
        """Construye un mensaje con los pasos para levantar la petición."""

        lines = [
            "No fue posible resolverlo automáticamente. Para atenderlo, levanta "
            "la petición en ServiceNow siguiendo estos pasos:",
            "",
        ]
        instructions = folio.get("instructions") or []
        for i, step in enumerate(instructions, start=1):
            lines.append(f"{i}. {step}")
        # Si no se identificó el servicio, listar los Order Guides disponibles.
        options = folio.get("options") or []
        if options:
            lines.append("")
            lines.append("Order Guides disponibles:")
            for opt in options:
                services = ", ".join(opt.get("services", []))
                lines.append(f"- {opt.get('guide')} ({services}): {opt.get('guide_url')}")
        note = folio.get("note")
        if note:
            lines.extend(["", f"Nota: {note}"])
        lines.extend(
            [
                "",
                'Si quieres, te guío paso a paso para llenarlo: responde '
                '"SoporteGD folio" y te iré pidiendo los datos.',
            ]
        )
        return "\n".join(lines)

    # ---- Helpers ------------------------------------------------------

    def _compose_prompt(
        self, system_prompt: str, session: AgentSession, context: str
    ) -> str:
        history = "\n".join(
            f"[{step.type.value}] {step.content}" for step in session.steps
        )
        req = session.request
        context_block = CONTEXT_TEMPLATE.format(
            context=context or "(sin contexto previo)",
            user_id=req.user_id,
            user_role=req.user_role,
            component_name=req.component_name or "(no especificado)",
            environment=req.environment.value,
            text=req.text,
            history=history or "(sin pasos previos)",
        )
        return f"{system_prompt}\n\n{context_block}"

    def _build_response(
        self,
        session: AgentSession,
        message: str,
        *,
        requires_approval: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> AgentResponse:
        return AgentResponse(
            session_id=session.session_id,
            status=session.status,
            message=message,
            steps=session.steps,
            requires_approval=requires_approval,
            integration_metadata=extra or {},
        )

    def _in_progress_response(
        self, session: AgentSession, info: dict[str, Any]
    ) -> AgentResponse:
        """Respuesta 'en progreso' mientras Devin procesa de forma asíncrona."""

        return self._build_response(
            session,
            "Devin está procesando la solicitud de forma asíncrona. "
            "Te notificaré cuando termine.",
            extra={
                "devin": {
                    "session_id": info.get("session_id"),
                    "url": info.get("url"),
                    "resume_endpoint": "/api/devin/callback",
                }
            },
        )
