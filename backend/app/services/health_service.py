"""
app/services/health_service.py
-------------------------------
Sprint 9B.4 — Serviço de health check com verificações reais de dependências.

Verifica:
  database     → SELECT 1 com timeout configurável
  vision_worker → worker.is_running (thread ativa)
  event_bus    → bus._running + queue size
  storage      → diretório existe + estatísticas de disco
  circuit_breakers → estado de cada CB (persistence + detector)
  yolo         → se habilitado, verifica se o arquivo de modelo existe

Contrato de resposta:
  status "healthy"  → todas as verificações ok
  status "degraded" → algum componente em estado subótimo mas sistema funciona
  status "unhealthy" → banco inacessível (sistema não consegue persistir dados)

HTTP status:
  200 → healthy ou degraded  (Docker healthcheck espera 200)
  503 → unhealthy
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Resultado de uma verificação de health."""
    status:  str                     # "ok" | "warning" | "error"
    details: dict[str, Any] = field(default_factory=dict)
    error:   str | None = None


async def _check_database(timeout_seconds: float) -> CheckResult:
    """
    Verifica conectividade com PostgreSQL via SELECT 1.

    Usa asyncio.to_thread para executar a query síncrona sem bloquear
    o event loop. Timeout via asyncio.wait_for.
    """
    def _ping() -> float:
        from app.database.session import SessionLocal
        db = SessionLocal()
        try:
            from sqlalchemy import text
            t0 = time.perf_counter()
            db.execute(text("SELECT 1"))
            return (time.perf_counter() - t0) * 1000  # ms
        finally:
            db.close()

    try:
        latency_ms = await asyncio.wait_for(
            asyncio.to_thread(_ping),
            timeout=timeout_seconds,
        )
        return CheckResult(
            status="ok",
            details={"latency_ms": round(latency_ms, 2)},
        )
    except asyncio.TimeoutError:
        return CheckResult(
            status="error",
            error=f"Timeout após {timeout_seconds}s",
        )
    except Exception as exc:
        return CheckResult(
            status="error",
            error=str(exc),
        )


def _check_vision_worker(worker: Any | None) -> CheckResult:
    """Verifica se o VisionWorker está ativo."""
    if worker is None:
        return CheckResult(
            status="warning",
            details={"running": False},
            error="VisionWorker não disponível (módulo vision não carregado)",
        )
    running = getattr(worker, "is_running", False)
    cb = getattr(worker, "_detector_cb", None)
    cb_state = cb.state.value if cb is not None else "N/A"

    return CheckResult(
        status="ok" if running else "warning",
        details={
            "running": running,
            "detector_circuit_breaker": cb_state,
        },
        error=None if running else "VisionWorker não está rodando",
    )


def _check_event_bus(bus: Any) -> CheckResult:
    """Verifica EventBus: running, queue size, circuit breaker."""
    running = getattr(bus, "_running", False)
    client_count = getattr(bus, "client_count", 0)
    queue = getattr(bus, "_queue", None)
    queue_size = queue.qsize() if queue is not None else 0
    fps = getattr(bus, "fps", 0.0)

    cb = getattr(bus, "_persist_cb", None)
    cb_state = cb.state.value if cb is not None else "N/A"

    return CheckResult(
        status="ok" if running else "warning",
        details={
            "running": running,
            "queue_size": queue_size,
            "clients_connected": client_count,
            "fps": fps,
            "persistence_circuit_breaker": cb_state,
        },
        error=None if running else "EventBus não está rodando",
    )


def _check_storage(storage_path: str, warning_pct: float, critical_pct: float) -> CheckResult:
    """Verifica diretório de storage e uso de disco."""
    path = Path(storage_path)

    if not path.exists():
        return CheckResult(
            status="error",
            details={"path": storage_path, "exists": False},
            error=f"Diretório de storage não existe: {storage_path}",
        )

    try:
        usage = shutil.disk_usage(str(path))
        used_pct = (usage.used / usage.total) * 100
        free_gb = usage.free / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)

        if used_pct >= critical_pct:
            status = "error"
            error = f"Disco crítico: {used_pct:.1f}% utilizado (limite crítico: {critical_pct}%)"
        elif used_pct >= warning_pct:
            status = "warning"
            error = f"Disco com atenção: {used_pct:.1f}% utilizado (limite warning: {warning_pct}%)"
        else:
            status = "ok"
            error = None

        return CheckResult(
            status=status,
            details={
                "path":      storage_path,
                "free_gb":   round(free_gb, 2),
                "used_gb":   round(used_gb, 2),
                "total_gb":  round(total_gb, 2),
                "used_pct":  round(used_pct, 1),
            },
            error=error,
        )
    except Exception as exc:
        return CheckResult(
            status="warning",
            details={"path": storage_path},
            error=f"Não foi possível verificar disco: {exc}",
        )


def _check_yolo(yolo_enabled: bool, model_path: str) -> CheckResult:
    """Verifica se o modelo YOLO está disponível quando habilitado."""
    if not yolo_enabled:
        return CheckResult(
            status="warning",
            details={"enabled": False},
            error="YOLO desabilitado — FallbackDetector ativo",
        )
    path = Path(model_path)
    if path.exists():
        return CheckResult(
            status="ok",
            details={"enabled": True, "model_path": str(path), "exists": True},
        )
    return CheckResult(
        status="warning",
        details={"enabled": True, "model_path": str(path), "exists": False},
        error=f"Modelo YOLO não encontrado: {model_path}",
    )


async def run_health_checks(
    worker: Any | None = None,
    bus: Any | None = None,
    supervisor: Any | None = None,
) -> dict[str, Any]:
    """
    Executa todas as verificações de health e retorna o resultado consolidado.

    Parameters
    ----------
    worker : VisionWorker | None
        Instância do VisionWorker injetada via app.state.worker.
        None indica que o módulo vision não está disponível.
    bus : EventBus | None
        Instância do EventBus (default: importa o singleton global).
    supervisor : WorkerSupervisor | None
        Sprint 10C.2 — quando fornecido (modo multi-linha ativo), adiciona
        ao resultado um campo "lines" com o snapshot de saúde de cada
        linha registrada (WorkerSupervisor.health_snapshot()). Campo
        puramente aditivo — ausente quando supervisor é None (modo
        legado/fallback single-worker), preservando o contrato de
        resposta anterior à 10C.2 nesse caso.

    Returns
    -------
    dict com:
      status    : "healthy" | "degraded" | "unhealthy"
      timestamp : ISO 8601 UTC
      version   : app version
      checks    : dict com resultado de cada verificação
      lines     : list[dict] — apenas se `supervisor` for fornecido (10C.2)
    """
    from datetime import datetime, timezone
    from app.core.config import settings
    from app.core.events import event_bus as default_bus

    if bus is None:
        bus = default_bus

    # Executa todas as verificações — DB é async, demais são síncronas
    db_result      = await _check_database(settings.health_timeout_seconds)
    worker_result  = _check_vision_worker(worker)
    bus_result     = _check_event_bus(bus)
    storage_result = _check_storage(
        settings.storage_path,
        settings.disk_warning_percent,
        settings.disk_critical_percent,
    )
    yolo_result    = _check_yolo(settings.yolo_enabled, settings.yolo_model_path)

    checks = {
        "database":     db_result,
        "vision_worker": worker_result,
        "event_bus":    bus_result,
        "storage":      storage_result,
        "yolo":         yolo_result,
    }

    # Determina status global:
    # - "unhealthy" se banco inacessível (sem persistência = sistema não funciona)
    # - "degraded" se qualquer outro componente com error ou warning
    # - "healthy" se todos ok
    has_error   = any(r.status == "error"   for r in checks.values())
    has_warning = any(r.status == "warning" for r in checks.values())

    if db_result.status == "error":
        overall = "unhealthy"
    elif has_error or has_warning:
        overall = "degraded"
    else:
        overall = "healthy"

    # Serializa para JSON-safe dict
    checks_dict = {}
    for name, result in checks.items():
        entry: dict[str, Any] = {"status": result.status, **result.details}
        if result.error:
            entry["message"] = result.error
        checks_dict[name] = entry

    response: dict[str, Any] = {
        "status":    overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version":   settings.app_version,
        "checks":    checks_dict,
    }

    # Sprint 10C.2 (PR-001) — saúde por linha, apenas quando o modo
    # multi-linha estiver ativo (supervisor injetado pelo lifespan).
    if supervisor is not None:
        try:
            response["lines"] = supervisor.health_snapshot()
        except Exception as exc:
            log.warning("Falha ao obter health_snapshot do supervisor: %s", exc)

    return response
