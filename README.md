# Soporte Valex — Sistema Multi-Agente de Soporte Transversal

Agente inteligente de soporte basado en el patrón **ReAct** (Reasoning + Acting), con
integración **MCP Teams**, **Devin API** como LLM prioritario (fallback a Llama 3 8B local),
y workflows **Human-in-the-loop (HITL)** con persistencia híbrida Redis/Kafka.

## Arquitectura

| Capa | Componentes |
|------|-------------|
| **Canales** | Webhook Teams, Callback MCP, Webhook ServiceNow |
| **API (FastAPI)** | `/api/teams/*`, `/api/servicenow/*`, `/api/ingestion/*`, `/api/finops/metrics`, `/api/kafka/logs` |
| **Orquestación** | `AgentOrchestrator` ReAct (límite 3 ciclos, escalamiento al Área X) |
| **Tools** | `get_component_telemetry_and_logs`, `execute_pipeline_action` (+ PRO Shield, Schema Guard) |
| **IA** | Router Devin/local con degradación automática |
| **Integraciones Teams** | Adapter unificado + cliente MCP JSON-RPC + Adaptive Cards |
| **Estado y Auditoría** | Sesiones (Redis/memoria), auditoría asíncrona (Kafka/memoria) |

## Estructura del proyecto

```
src/
├── agents/orchestrator/   # Bucle ReAct, prompts, parser
├── adapters/mcp_teams/    # Adapter, cliente JSON-RPC, cards, contratos
├── integrations/          # Devin API, LLM local, router
├── tools/                 # Telemetría, pipeline, schema guard, registry
├── workflows/             # Estado (HITL), aprobaciones, auditoría
├── ingestion/             # Chunking, embeddings, worker background
├── api/                   # FastAPI: endpoints y dependencias
└── core/                  # Config parametrizable, modelos, excepciones
schemas/
├── mcp/                   # Contratos JSON-RPC v1 y v1.1
└── oracle/                # DDL (WF_* y KB_*)
tests/                     # Pruebas unitarias
```

## Decisiones técnicas

- **LLM**: Devin API prioritario, fallback a LLM local (`LLM_PRIMARY` / `LLM_FALLBACK`).
- **Motor de workflows**: híbrido — la IA razona y el estado HITL se persiste en Redis con
  auditoría en Kafka (Punto 4 del doc).
- **Integraciones**: MCP real desde el inicio (`TEAMS_MODE=mcp`), conmutable a `simulated`/`webhook`.
- **Seguridad**: PRO Shield bloquea mutaciones en producción; Schema Guard valida payloads del LLM.

## Configuración

Copia `.env.example` a `.env` y ajusta los valores (Devin, MCP, Redis, Kafka, Oracle).

## Ejecución local

```bash
pip install -r requirements.txt
uvicorn src.api.main:app --reload --port 8080
# o con infraestructura completa:
docker compose up --build
```

API docs interactiva en `http://localhost:8080/docs`.

## Pruebas

```bash
pytest -q
```

Cobertura: configuración, parser ReAct, tools (PRO Shield / Schema Guard), contratos MCP,
orquestador (flujo completo, HITL suspend/resume, escalamiento) e ingesta.

## CI/CD

`.github/workflows/ci.yml`: tests → Trivy scan (CVEs) → build de imagen multi-stage
(`python:3.11-slim`, ejecución Non-Root con UID 10001) según estándares OpenShift.

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/teams/webhook` | Mención desde Teams → flujo ReAct |
| POST | `/api/teams/mcp/action` | Callback Adaptive Card → reanuda HITL |
| POST | `/api/servicenow/webhook` | Incidente desde ServiceNow |
| POST | `/api/ingestion/upload` | Carga documento (background) |
| GET | `/api/ingestion/status/{job_id}` | Estado del job de ingesta |
| GET | `/api/finops/metrics` | KPIs de costo/performance |
| POST | `/api/kafka/logs` | Publica evento de auditoría |
| GET | `/health` | Healthcheck |