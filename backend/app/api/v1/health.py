"""
app/api/v1/health.py
---------------------
Sprint 9B.4 — Health check real com verificações de dependências.

GET /health

Verifica:
  database     → SELECT 1 com timeout (5s padrão)
  vision_worker → VisionWorker.is_running
  event_bus    → EventBus._running, queue_size, fps
  storage      → diretório existe, uso de disco (warning/critical)
  yolo         → modelo disponível quando YOLO_ENABLED=true

Status HTTP:
  200 → "healthy" (todas as verificações ok)
  200 → "degraded" (algum componente subótimo, sistema funciona)
  503 → "unhealthy" (banco inacessível — sem persistência)

Endpoint público (sem autenticação):
  Docker healthcheck e load balancers não enviam Bearer token.
  Não expõe dados sensíveis — apenas status operacional.

Sprint anterior: retornava {"status": "healthy"} fixo sem verificar nada.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.health_service import run_health_checks

router = APIRouter()


@router.get(
    "/health",
    summary="Health check operacional",
    description=(
        "Verifica o estado de todas as dependências críticas: banco de dados, "
        "VisionWorker, EventBus, storage e modelo YOLO. "
        "Retorna 200 para 'healthy'/'degraded' e 503 para 'unhealthy'. "
        "Endpoint público — sem autenticação necessária."
    ),
    tags=["health"],
    responses={
        200: {"description": "Sistema saudável ou degradado (mas operacional)"},
        503: {"description": "Sistema não operacional (banco inacessível)"},
    },
)
async def health_check(request: Request) -> JSONResponse:
    """
    Health check rico — verifica todas as dependências críticas.

    O worker é injetado via app.state.worker (definido no lifespan de main.py).
    Se não disponível (módulo vision ausente), retorna "degraded" para o check
    de vision_worker, mas não "unhealthy" — o sistema ainda processa via API.
    """
    worker = getattr(request.app.state, "worker", None)
    supervisor = getattr(request.app.state, "supervisor", None)

    # Sprint 10C.2: passa `supervisor` apenas quando o alvo (a função real,
    # ou um mock/monkeypatch usado em teste) de fato declara esse parâmetro
    # — via inspect.signature, não try/except, para nunca mascarar um
    # TypeError genuíno vindo de dentro da própria função.
    import inspect
    accepts_supervisor = "supervisor" in inspect.signature(run_health_checks).parameters
    if accepts_supervisor:
        result = await run_health_checks(worker=worker, supervisor=supervisor)
    else:
        result = await run_health_checks(worker=worker)

    http_status = 503 if result["status"] == "unhealthy" else 200
    return JSONResponse(content=result, status_code=http_status)
