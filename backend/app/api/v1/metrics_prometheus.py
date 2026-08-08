"""
app/api/v1/metrics_prometheus.py
----------------------------------
Sprint 9B.4 — Endpoint GET /metrics em formato Prometheus text/plain.

Retorna todas as métricas instrumentadas da aplicação no formato
Prometheus exposition format (text/plain; version=0.0.4).

Antes de retornar, atualiza os Gauges dinâmicos (fps, queue, pool, etc.)
com os valores atuais do sistema — esses valores mudam frequentemente
e não podem ser pré-calculados no momento do registro da métrica.

Acesso:
  - Habilitado por padrão (prometheus_enabled=True em settings)
  - Desabilitado com PROMETHEUS_ENABLED=false
  - Não requer autenticação por padrão — configurar firewall para restringir
    ao scraper do Prometheus (boa prática: expor apenas na rede interna)

Scraping recomendado: interval=15s, timeout=5s
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import settings
from app.core.metrics import METRICS

log = logging.getLogger(__name__)

router = APIRouter(tags=["observability"])


def _update_dynamic_metrics(request: Request) -> None:
    """
    Atualiza Gauges com valores atuais antes de gerar o output.

    Métricas de Counter e Histogram são atualizadas pelos próprios eventos
    (middleware HTTP, EventBus, etc.). Gauges dinâmicos (fps, queue_size,
    conexões, pool) precisam ser atualizados no momento do scraping.
    """
    from app.core.events import event_bus

    # EventBus
    METRICS.inspection_fps.set(event_bus.fps)
    METRICS.websocket_connections_active.set(event_bus.client_count)
    queue = getattr(event_bus, "_queue", None)
    METRICS.eventbus_queue_size.set(queue.qsize() if queue is not None else 0)

    # Inspection error rate
    total    = getattr(event_bus, "_total",    0)
    rejected = getattr(event_bus, "_rejected", 0)
    METRICS.inspection_error_rate.set((rejected / total) if total else 0.0)

    # VisionWorker
    worker = getattr(request.app.state, "worker", None)
    running = (worker is not None and getattr(worker, "is_running", False))
    METRICS.vision_worker_running.set(1.0 if running else 0.0)

    # Circuit Breakers
    _update_cb_metrics(event_bus, worker)

    # Sprint 10C.2 — métricas por linha de produção (aditivo)
    _update_per_line_metrics()

    # Database pool
    try:
        from app.database.session import engine
        pool = engine.pool
        METRICS.db_pool_size.set(getattr(pool, "size", lambda: settings.db_pool_size)())
        METRICS.db_pool_checked_out.set(getattr(pool, "checkedout", lambda: 0)())
        METRICS.db_pool_overflow.set(getattr(pool, "overflow", lambda: 0)())
    except Exception:
        pass

    # Storage disk usage
    try:
        import shutil
        from pathlib import Path
        path = Path(settings.storage_path)
        if path.exists():
            usage = shutil.disk_usage(str(path))
            METRICS.storage_disk_bytes_used.set(usage.used)
            METRICS.storage_disk_bytes_free.set(usage.free)
    except Exception:
        pass


def _update_per_line_metrics() -> None:
    """
    Sprint 10C.2 (PR-004) — atualiza os Gauges com label por linha.

    Puramente aditivo: se o LineRegistry estiver vazio (modo fallback
    legado single-worker, ou ambiente sem nenhuma linha registrada),
    simplesmente não emite nenhuma série com label `line_id`/`line_code`
    — os Gauges globais (sem label) continuam sendo a única fonte,
    exatamente como antes da 10C.2.
    """
    try:
        from app.core.line_registry import line_registry
        for ctx in line_registry.all():
            labels = {"line_id": str(ctx.line_id), "line_code": ctx.code}
            running = bool(ctx.worker and ctx.worker.is_running)
            METRICS.line_worker_running.labels(**labels).set(1.0 if running else 0.0)
            fps = getattr(ctx.event_bus, "fps", 0.0) if ctx.event_bus else 0.0
            METRICS.line_inspection_fps.labels(**labels).set(fps)
            clients = getattr(ctx.event_bus, "client_count", 0) if ctx.event_bus else 0
            METRICS.line_websocket_connections_active.labels(**labels).set(clients)
            METRICS.line_restart_count.labels(**labels).set(ctx.restart_count)
    except Exception as exc:
        log.warning("Falha ao atualizar métricas por linha: %s", exc)


def _update_cb_metrics(bus, worker) -> None:
    """Atualiza métricas de estado dos circuit breakers."""
    _CB_STATE_MAP = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}

    # CB de persistência (EventBus)
    cb_persist = getattr(bus, "_persist_cb", None)
    if cb_persist is not None:
        try:
            state_val = _CB_STATE_MAP.get(cb_persist.state.value, 0)
            METRICS.circuit_breaker_state.labels(name="persistence").set(state_val)
        except Exception:
            pass

    # CB de detector (VisionWorker)
    cb_detector = getattr(worker, "_detector_cb", None) if worker else None
    if cb_detector is not None:
        try:
            state_val = _CB_STATE_MAP.get(cb_detector.state.value, 0)
            METRICS.circuit_breaker_state.labels(name="detector").set(state_val)
        except Exception:
            pass


@router.get(
    "/metrics",
    summary="Métricas Prometheus",
    description=(
        "Expõe métricas no formato Prometheus text exposition format. "
        "Habilitado quando PROMETHEUS_ENABLED=true (padrão). "
        "Configurar firewall para restringir acesso ao scraper Prometheus."
    ),
    responses={
        200: {"description": "Métricas em texto Prometheus"},
        404: {"description": "Prometheus desabilitado via PROMETHEUS_ENABLED=false"},
    },
)
async def prometheus_metrics(request: Request) -> Response:
    """
    Endpoint de métricas Prometheus.

    Atualiza Gauges dinâmicos antes de gerar o output para garantir
    que o scraper receba os valores mais recentes do sistema.
    """
    if not settings.prometheus_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prometheus desabilitado. Configure PROMETHEUS_ENABLED=true para habilitar.",
        )

    try:
        _update_dynamic_metrics(request)
    except Exception as exc:
        log.warning("Falha ao atualizar métricas dinâmicas: %s", exc)

    output = generate_latest()
    return Response(
        content=output,
        media_type=CONTENT_TYPE_LATEST,
    )
