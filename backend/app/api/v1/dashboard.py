"""
app/api/v1/dashboard.py
-------------------------
Endpoints REST do Sprint 6 — histórico, métricas e dashboard.

Prefixo: /api/v1   (distinto do /inspection legado das Sprints 2/3,
que permanece intacto para compatibilidade retroativa)

  GET /api/v1/inspections          — histórico paginado com filtros
  GET /api/v1/inspections/{id}     — detalhe de uma inspeção
  GET /api/v1/metrics              — métricas agregadas em tempo real
  GET /api/v1/dashboard            — payload do dashboard operacional
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
from app.models.user import User
from sqlalchemy.orm import Session

from app.core.events import event_bus
from app.database.session import get_db
from app.repositories.inspection_repository import InspectionRepository
from app.schemas.dashboard import (
    DashboardResponse,
    InspectionItem,
    MetricsResponse,
    PaginatedInspections,
)
from app.services.dashboard_service import get_dashboard, get_metrics

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


def _resolve_fps(line_id: int | None) -> float:
    """
    Sprint 10C.2 — resolve o FPS a reportar.

    Sem line_id (comportamento padrão/legado): usa o `event_bus` singleton
    diretamente, exatamente como antes da Sprint 10C.2 — zero mudança de
    comportamento quando o parâmetro não é usado.

    Com line_id: consulta o LineRegistry pelo bus daquela linha. Se a
    linha não estiver registrada em runtime (ex: linha inativa, ou
    processo rodando em modo de fallback single-worker), retorna 0.0 em
    vez de lançar erro — FPS é uma métrica "best effort".
    """
    if line_id is None:
        return event_bus.fps
    try:
        from app.core.line_registry import line_registry
        ctx = line_registry.get(line_id)
        if ctx is not None and ctx.event_bus is not None:
            return ctx.event_bus.fps
    except Exception:
        pass
    return 0.0


@router.get(
    "/inspections",
    response_model=PaginatedInspections,
    summary="Listar inspeções com filtros e paginação",
)
def list_inspections_v1(
    barcode: str | None = Query(None, description="Filtro parcial por barcode"),
    valid: bool | None = Query(None, description="Filtrar por aprovado/rejeitado"),
    product_name: str | None = Query(None, description="Filtro parcial por nome do produto"),
    date_from: datetime | None = Query(None, description="Data inicial (ISO 8601)"),
    date_to: datetime | None = Query(None, description="Data final (ISO 8601)"),
    sort: str = Query(
        "newest",
        pattern="^(newest|oldest|confidence_desc|confidence_asc)$",
        description="newest | oldest | confidence_desc | confidence_asc",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PaginatedInspections:
    repo = InspectionRepository(db)
    offset = (page - 1) * page_size

    items, total = repo.query(
        barcode=barcode,
        valid=valid,
        product_name=product_name,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        limit=page_size,
        offset=offset,
    )

    return PaginatedInspections(
        items=[InspectionItem.from_orm_inspection(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/inspections/{inspection_id}",
    response_model=InspectionItem,
    summary="Detalhe de uma inspeção",
)
def get_inspection_v1(
    inspection_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> InspectionItem:
    repo = InspectionRepository(db)
    inspection = repo.get_by_id(inspection_id)
    if inspection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inspeção {inspection_id} não encontrada.",
        )
    return InspectionItem.from_orm_inspection(inspection)


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Métricas agregadas em tempo real",
)
def metrics_v1(
    line_id: int | None = Query(
        None, description="Sprint 10C.2 — filtra métricas por linha de produção. "
                            "Omitido = agregado de todas as linhas (comportamento padrão)."
    ),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MetricsResponse:
    fps = _resolve_fps(line_id)
    return get_metrics(db, fps=fps, line_id=line_id)


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Dashboard operacional",
)
def dashboard_v1(
    line_id: int | None = Query(
        None, description="Sprint 10C.2 — filtra o dashboard por linha de produção. "
                            "Omitido = agregado de todas as linhas (comportamento padrão)."
    ),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DashboardResponse:
    return get_dashboard(db, line_id=line_id)
