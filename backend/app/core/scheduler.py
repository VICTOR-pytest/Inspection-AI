"""
app/core/scheduler.py
----------------------
Sprint 10B — Scheduler interno de manutenção usando asyncio puro.

Sem APScheduler, Celery ou qualquer dependência externa.
Utiliza o mesmo padrão das tasks existentes (EventBus, VisionWorker):
asyncio.create_task() no lifespan do main.py, task.cancel() no shutdown.

Responsabilidades do ciclo diário:
  1. Monitoramento de disco — loga WARNING se > disk_warning_percent
  2. Cleanup de imagens antigas — deleta imagens além de image_retention_days
  3. Detecção de órfãos — reporta inconsistências storage ↔ banco
  4. Atualização de métricas Prometheus (storage_images_total, disk_bytes)

Agendamento:
  O scheduler calcula os segundos até a próxima execução em image_cleanup_hour
  UTC. Se o container iniciar ANTES da hora configurada, espera até lá.
  Se iniciar DEPOIS, agenda para o mesmo horário no dia seguinte.
  Isso garante execução consistente independente do horário de inicialização.

Tolerância a falhas:
  Qualquer exceção dentro do ciclo é capturada e logada. O scheduler
  continua rodando — uma falha pontual não derruba o ciclo seguinte.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.database.session import SessionLocal
from app.services import storage_service

log = logging.getLogger(__name__)


def _seconds_until_next_run(target_hour_utc: int) -> float:
    """
    Calcula quantos segundos faltam até a próxima execução em target_hour_utc.

    Exemplos (target_hour_utc=2):
      Agora = 01:00 UTC → retorna 3600.0   (1 hora)
      Agora = 02:00 UTC → retorna 86400.0  (24 horas — já passou hoje)
      Agora = 03:00 UTC → retorna 82800.0  (23 horas)
      Agora = 02:30 UTC → retorna 84600.0  (23h30)

    Garante mínimo de 60 segundos para evitar execução imediata repetida
    no caso de restart exatamente na hora configurada.
    """
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=target_hour_utc, minute=0, second=0, microsecond=0)

    if next_run <= now:
        next_run += timedelta(days=1)

    delta = (next_run - now).total_seconds()
    return max(delta, 60.0)


async def _run_cleanup_cycle() -> None:
    """
    Executa um ciclo completo de manutenção de storage.

    Ordem: monitoramento → cleanup → órfãos → métricas.
    Cada etapa é independente: falha em uma não cancela as demais.
    """
    log.info("Scheduler: iniciando ciclo de manutenção de storage")

    # ── 1. Monitoramento de disco ─────────────────────────────────────────────
    try:
        stats = storage_service.get_disk_stats(settings.storage_path)
        log.info(
            "Scheduler: disco storage — usado=%.1f%% livre=%.2fGB total=%.2fGB",
            stats.used_pct,
            stats.free_gb,
            stats.total_gb,
        )
        if stats.used_pct >= settings.disk_critical_percent:
            log.error(
                "Scheduler: DISCO CRÍTICO — %.1f%% utilizado "
                "(limite crítico: %.0f%%). Ação imediata necessária.",
                stats.used_pct,
                settings.disk_critical_percent,
            )
        elif stats.used_pct >= settings.disk_warning_percent:
            log.warning(
                "Scheduler: disco com atenção — %.1f%% utilizado "
                "(limite warning: %.0f%%)",
                stats.used_pct,
                settings.disk_warning_percent,
            )
    except Exception as exc:
        log.error("Scheduler: falha ao verificar disco — %s", exc)

    # ── 2. Cleanup de imagens antigas ─────────────────────────────────────────
    if settings.image_cleanup_enabled and settings.image_retention_days > 0:
        db = SessionLocal()
        try:
            result = await asyncio.to_thread(
                storage_service.cleanup_older_than,
                db,
                settings.image_retention_days,
                False,
            )
            log.info(
                "Scheduler: cleanup concluído — "
                "deletados=%d arquivos, liberados=%.2fMB, erros=%d",
                result.deleted_files,
                result.freed_bytes / (1024 ** 2),
                len(result.errors),
            )
        except Exception as exc:
            log.error("Scheduler: falha no cleanup de imagens — %s", exc)
        finally:
            db.close()
    else:
        log.info(
            "Scheduler: cleanup ignorado "
            "(image_cleanup_enabled=%s, retention_days=%d)",
            settings.image_cleanup_enabled,
            settings.image_retention_days,
        )

    # ── 3. Detecção de órfãos ─────────────────────────────────────────────────
    if settings.orphan_check_enabled:
        db = SessionLocal()
        try:
            orphan_files   = await asyncio.to_thread(
                storage_service.find_orphan_files, db, settings.storage_path
            )
            orphan_records = await asyncio.to_thread(
                storage_service.find_orphan_records, db, settings.storage_path
            )

            if orphan_files or orphan_records:
                log.warning(
                    "Scheduler: órfãos detectados — "
                    "arquivos_sem_registro=%d registros_sem_arquivo=%d. "
                    "Use POST /api/v1/storage/cleanup ou GET /api/v1/storage/orphans.",
                    len(orphan_files),
                    len(orphan_records),
                )
            else:
                log.info("Scheduler: nenhum órfão detectado")
        except Exception as exc:
            log.error("Scheduler: falha na detecção de órfãos — %s", exc)
        finally:
            db.close()

    # ── 4. Atualiza métricas Prometheus ───────────────────────────────────────
    try:
        from app.core.metrics import METRICS
        counts = storage_service.count_images(settings.storage_path)
        METRICS.storage_images_total.labels(variant="original").set(counts["original"])
        METRICS.storage_images_total.labels(variant="annotated").set(counts["annotated"])
        METRICS.storage_images_total.labels(variant="all").set(counts["total"])

        disk = storage_service.get_disk_stats(settings.storage_path)
        METRICS.storage_disk_bytes_used.set(disk.used_bytes)
        METRICS.storage_disk_bytes_free.set(disk.free_bytes)
    except Exception as exc:
        log.warning("Scheduler: falha ao atualizar métricas — %s", exc)

    log.info("Scheduler: ciclo de manutenção concluído")


async def cleanup_scheduler_loop() -> None:
    """
    Loop principal do scheduler de manutenção.

    Calcula o tempo até a próxima execução configurada (image_cleanup_hour UTC),
    aguarda, executa o ciclo completo e repete indefinidamente.

    Tolerância a falhas: exceções no ciclo são capturadas e logadas.
    O loop continua para o próximo dia — uma falha não derruba o scheduler.

    Cancellation: asyncio.CancelledError é propagado imediatamente
    (não capturado), permitindo shutdown limpo pelo lifespan do main.py.
    """
    log.info(
        "Scheduler: iniciado — cleanup diário às %02d:00 UTC "
        "(retention=%dd, cleanup=%s, orphan_check=%s)",
        settings.image_cleanup_hour,
        settings.image_retention_days,
        settings.image_cleanup_enabled,
        settings.orphan_check_enabled,
    )

    while True:
        wait_seconds = _seconds_until_next_run(settings.image_cleanup_hour)
        next_run_utc = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)

        log.info(
            "Scheduler: próximo ciclo em %.0fs (%s UTC)",
            wait_seconds,
            next_run_utc.strftime("%Y-%m-%d %H:%M"),
        )

        await asyncio.sleep(wait_seconds)

        try:
            await _run_cleanup_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error(
                "Scheduler: erro inesperado no ciclo — %s. "
                "Próximo ciclo agendado normalmente.",
                exc,
                exc_info=True,
            )
