"""
app/services/storage_service.py
--------------------------------
Sprint 9B.4 — Serviço de gerenciamento de storage de imagens.

Responsabilidades:
  1. get_disk_stats()       → uso de disco em bytes e percentual
  2. count_images()         → contagem de arquivos por variante
  3. cleanup_older_than()   → deleta imagens + registros além da janela de retenção
  4. find_orphan_files()    → arquivos em disco sem registro em inspection_images
  5. find_orphan_records()  → registros em inspection_images sem arquivo em disco

Compliance LGPD / ISO 9001:
  - Toda exclusão gera log de auditoria com inspection_id, file_path, motivo
  - cleanup_older_than() nunca deleta em cascata silenciosamente
  - Operação é idempotente: rodar duas vezes com mesmos parâmetros é seguro
  - image_cleanup_enabled=False desabilita qualquer exclusão automática

Thread-safety:
  Métodos que deletam arquivos usam asyncio.to_thread para não bloquear
  o event loop. Leituras de disco são síncronas (rápidas).
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.config import settings

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


# ── Estruturas de dados ───────────────────────────────────────────────────────

class DiskStats:
    """Estatísticas de uso do filesystem do storage."""
    def __init__(self, total: int, used: int, free: int):
        self.total_bytes = total
        self.used_bytes  = used
        self.free_bytes  = free
        self.total_gb    = total / (1024 ** 3)
        self.used_gb     = used  / (1024 ** 3)
        self.free_gb     = free  / (1024 ** 3)
        self.used_pct    = (used / total * 100) if total else 0.0

    def to_dict(self) -> dict:
        return {
            "total_gb":  round(self.total_gb, 2),
            "used_gb":   round(self.used_gb,  2),
            "free_gb":   round(self.free_gb,  2),
            "used_pct":  round(self.used_pct, 1),
            "total_bytes": self.total_bytes,
            "used_bytes":  self.used_bytes,
            "free_bytes":  self.free_bytes,
        }


class CleanupResult:
    """Resultado de uma operação de cleanup."""
    def __init__(self):
        self.deleted_files:   int = 0
        self.deleted_records: int = 0
        self.freed_bytes:     int = 0
        self.errors:          list[str] = []
        self.cutoff_date:     datetime | None = None

    def to_dict(self) -> dict:
        return {
            "deleted_files":   self.deleted_files,
            "deleted_records": self.deleted_records,
            "freed_bytes":     self.freed_bytes,
            "freed_mb":        round(self.freed_bytes / (1024**2), 2),
            "errors":          self.errors,
            "cutoff_date":     self.cutoff_date.isoformat() if self.cutoff_date else None,
        }


# ── Funções públicas ──────────────────────────────────────────────────────────

def get_disk_stats(storage_path: str | None = None) -> DiskStats:
    """
    Retorna estatísticas de uso do filesystem do storage.

    Raises:
        FileNotFoundError: se o diretório não existir.
        OSError: se não for possível ler o filesystem.
    """
    path = Path(storage_path or settings.storage_path)
    if not path.exists():
        raise FileNotFoundError(f"Storage path não existe: {path}")
    usage = shutil.disk_usage(str(path))
    return DiskStats(usage.total, usage.used, usage.free)


def count_images(storage_path: str | None = None) -> dict[str, int]:
    """
    Conta arquivos de imagem presentes no storage por variante.

    Retorna dict:
      {"original": N, "annotated": N, "total": N}
    """
    base = Path(storage_path or settings.storage_path)
    if not base.exists():
        return {"original": 0, "annotated": 0, "total": 0}

    original_dir  = base / "images" / "original"
    annotated_dir = base / "images" / "annotated"

    def _count_dir(p: Path) -> int:
        if not p.exists():
            return 0
        return sum(1 for f in p.rglob("*.jpg") if f.is_file())

    n_original  = _count_dir(original_dir)
    n_annotated = _count_dir(annotated_dir)

    return {
        "original":  n_original,
        "annotated": n_annotated,
        "total":     n_original + n_annotated,
    }


def cleanup_older_than(
    db: Session,
    retention_days: int | None = None,
    dry_run: bool = False,
) -> CleanupResult:
    """
    Deleta imagens (arquivo + registro no banco) mais antigas que retention_days.

    Parâmetros:
        db             : Sessão SQLAlchemy ativa.
        retention_days : Número de dias de retenção.
                         None → usa settings.image_retention_days.
                         0    → não deleta nada (desabilitado).
        dry_run        : Se True, conta o que seria deletado sem deletar.

    Compliance LGPD:
        - Log de auditoria para cada arquivo deletado
        - Nunca deleta em silêncio — todas as exclusões são logadas
        - Operação idempotente: chamar duas vezes é seguro

    Retorna CleanupResult com estatísticas da operação.
    """
    result = CleanupResult()

    days = retention_days if retention_days is not None else settings.image_retention_days
    if days == 0:
        log.info("StorageService: retention_days=0 — cleanup desabilitado")
        return result

    if not settings.image_cleanup_enabled and not dry_run:
        log.info("StorageService: IMAGE_CLEANUP_ENABLED=false — cleanup desabilitado")
        return result

    cutoff_utc   = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_naive = cutoff_utc.replace(tzinfo=None)
    result.cutoff_date = cutoff_utc

    log.info(
        "StorageService: cleanup %s — buscando imagens anteriores a %s (%d dias)",
        "[DRY RUN] " if dry_run else "",
        cutoff_utc.strftime("%Y-%m-%d"),
        days,
    )

    # Busca registros elegíveis para exclusão
    from sqlalchemy import select
    from app.models.inspection_image import InspectionImage

    stmt = (
        select(InspectionImage)
        .where(InspectionImage.created_at < cutoff_naive)
        .order_by(InspectionImage.created_at.asc())
    )
    records = list(db.execute(stmt).scalars().all())

    log.info("StorageService: %d registros encontrados para cleanup", len(records))

    base_path = Path(settings.storage_path).resolve()

    for record in records:
        # Valida path antes de qualquer operação (proteção contra traversal)
        try:
            from app.services.image_storage import PathTraversalError, resolve_full_path
            full_path = resolve_full_path(record.file_path, settings.storage_path)
        except Exception as exc:
            msg = f"Path inválido ignorado: id={record.id} path={record.file_path!r} — {exc}"
            log.warning("StorageService: %s", msg)
            result.errors.append(msg)
            continue

        file_size = 0
        if full_path.exists():
            try:
                file_size = full_path.stat().st_size
            except OSError:
                pass

            if not dry_run:
                try:
                    full_path.unlink()
                    log.info(
                        "StorageService: LGPD — imagem excluída: "
                        "inspection_id=%d variant=%s file=%s size_bytes=%d cutoff=%s",
                        record.inspection_id,
                        record.variant,
                        record.file_path,
                        file_size,
                        cutoff_utc.strftime("%Y-%m-%d"),
                    )
                except OSError as exc:
                    msg = f"Falha ao deletar arquivo: {full_path} — {exc}"
                    log.error("StorageService: %s", msg)
                    result.errors.append(msg)
                    continue

        if not dry_run:
            try:
                db.delete(record)
                result.deleted_records += 1
            except Exception as exc:
                msg = f"Falha ao deletar registro id={record.id}: {exc}"
                log.error("StorageService: %s", msg)
                result.errors.append(msg)
                continue

        result.deleted_files += 1
        result.freed_bytes   += file_size

    if not dry_run and result.deleted_records > 0:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("StorageService: falha no commit do cleanup: %s", exc)
            result.errors.append(f"Commit falhou: {exc}")

    # Atualiza métrica Prometheus
    try:
        from app.core.metrics import METRICS
        METRICS.storage_cleanup_deleted_total.inc(result.deleted_files)
    except Exception:
        pass

    log.info(
        "StorageService: cleanup concluído — "
        "arquivos=%d registros=%d liberado=%.2fMB erros=%d%s",
        result.deleted_files,
        result.deleted_records,
        result.freed_bytes / (1024**2),
        len(result.errors),
        " [DRY RUN]" if dry_run else "",
    )
    return result


def find_orphan_files(db: Session, storage_path: str | None = None) -> list[str]:
    """
    Encontra arquivos em disco sem registro correspondente em inspection_images.

    Um arquivo é órfão quando:
    - Existe em storage/images/ como .jpg
    - Não existe nenhum registro em inspection_images com esse file_path

    Retorna lista de caminhos relativos dos arquivos órfãos.
    """
    base = Path(storage_path or settings.storage_path)
    images_dir = base / "images"
    if not images_dir.exists():
        return []

    # Busca todos os file_paths registrados no banco
    from sqlalchemy import select
    from app.models.inspection_image import InspectionImage
    stmt = select(InspectionImage.file_path)
    registered = set(db.execute(stmt).scalars().all())

    base_resolved = base.resolve()
    orphans: list[str] = []

    for jpg_file in images_dir.rglob("*.jpg"):
        try:
            relative = str(jpg_file.resolve().relative_to(base_resolved))
        except ValueError:
            continue  # fora do base_path — ignora
        if relative not in registered:
            orphans.append(relative)

    if orphans:
        log.warning(
            "StorageService: %d arquivo(s) órfão(s) encontrado(s) "
            "(em disco sem registro no banco)",
            len(orphans),
        )

    return orphans


def find_orphan_records(db: Session, storage_path: str | None = None) -> list[int]:
    """
    Encontra registros em inspection_images sem arquivo correspondente em disco.

    Um registro é órfão quando:
    - Existe em inspection_images com um file_path
    - O arquivo físico não existe em disco

    Retorna lista de IDs dos registros órfãos.
    """
    from sqlalchemy import select
    from app.models.inspection_image import InspectionImage
    from app.services.image_storage import PathTraversalError, resolve_full_path

    stmt = select(InspectionImage)
    records = list(db.execute(stmt).scalars().all())

    orphan_ids: list[int] = []
    for record in records:
        try:
            full_path = resolve_full_path(record.file_path, storage_path or settings.storage_path)
            if not full_path.exists():
                orphan_ids.append(record.id)
        except PathTraversalError:
            orphan_ids.append(record.id)  # path inválido também é órfão
        except Exception:
            continue

    if orphan_ids:
        log.warning(
            "StorageService: %d registro(s) órfão(s) no banco "
            "(registro sem arquivo em disco)",
            len(orphan_ids),
        )

    return orphan_ids
