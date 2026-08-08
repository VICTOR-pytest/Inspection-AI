"""
app/api/v1/storage_api.py
---------------------------
Sprint 9B.4 — Endpoints de gerenciamento de storage de imagens.

GET  /api/v1/storage/stats    → estatísticas de disco e contagem de imagens
POST /api/v1/storage/cleanup  → executa cleanup manual de imagens antigas
GET  /api/v1/storage/orphans  → detecta arquivos e registros órfãos

Todos os endpoints requerem role ADMIN.
O cleanup é auditado via log estruturado (LGPD compliance).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.database.session import get_db
from app.models.user import User
from app.services import storage_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


@router.get(
    "/stats",
    summary="Estatísticas de storage",
    description="Retorna uso de disco e contagem de imagens por variante. Requer ADMIN.",
    responses={
        200: {"description": "Estatísticas de storage"},
        401: {"description": "Token ausente ou inválido"},
        403: {"description": "Requer role ADMIN"},
        503: {"description": "Storage inacessível"},
    },
)
def get_storage_stats(
    _: User = Depends(require_admin),
) -> dict:
    """
    Retorna estatísticas completas do storage:
      - Uso de disco (total, usado, livre, percentual)
      - Contagem de imagens por variante (original, annotated)
    """
    try:
        disk  = storage_service.get_disk_stats()
        count = storage_service.count_images()
        return {
            "disk":   disk.to_dict(),
            "images": count,
        }
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Storage inacessível: {exc}",
        )
    except Exception as exc:
        log.error("get_storage_stats: erro inesperado: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Erro ao acessar storage.",
        )


@router.post(
    "/cleanup",
    summary="Executar cleanup de imagens",
    description=(
        "Deleta imagens mais antigas que retention_days do storage e banco. "
        "Toda exclusão é registrada em log de auditoria (LGPD compliance). "
        "dry_run=true simula a operação sem deletar. Requer ADMIN."
    ),
    responses={
        200: {"description": "Resultado do cleanup"},
        401: {"description": "Token ausente ou inválido"},
        403: {"description": "Requer role ADMIN"},
    },
)
def trigger_cleanup(
    retention_days: int = Query(
        default=None,
        description="Dias de retenção (default: IMAGE_RETENTION_DAYS do .env)",
        ge=1,
    ),
    dry_run: bool = Query(
        default=False,
        description="Se true, simula a operação sem deletar nada",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """
    Executa cleanup manual de imagens antigas.

    Auditado: log INFO para cada arquivo deletado com inspection_id, variant, path.
    """
    log.info(
        "StorageCleanup: iniciado por admin user_id=%d retention_days=%s dry_run=%s",
        current_user.id,
        retention_days,
        dry_run,
    )

    result = storage_service.cleanup_older_than(
        db=db,
        retention_days=retention_days,
        dry_run=dry_run,
    )
    return result.to_dict()


@router.get(
    "/orphans",
    summary="Detectar arquivos e registros órfãos",
    description=(
        "Detecta: (1) arquivos em disco sem registro no banco, "
        "(2) registros no banco sem arquivo em disco. Requer ADMIN."
    ),
    responses={
        200: {"description": "Listas de órfãos encontrados"},
        401: {"description": "Token ausente ou inválido"},
        403: {"description": "Requer role ADMIN"},
    },
)
def get_orphans(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """
    Detecta inconsistências entre filesystem e banco de dados.

    Não deleta nada — apenas reporta para ação manual ou cleanup direcionado.
    """
    orphan_files   = storage_service.find_orphan_files(db)
    orphan_records = storage_service.find_orphan_records(db)

    return {
        "orphan_files": {
            "count": len(orphan_files),
            "paths": orphan_files[:50],  # limita a 50 para não sobrecarregar o response
            "truncated": len(orphan_files) > 50,
        },
        "orphan_records": {
            "count": len(orphan_records),
            "ids":   orphan_records[:50],
            "truncated": len(orphan_records) > 50,
        },
    }
