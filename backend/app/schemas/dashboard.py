"""
app/schemas/dashboard.py
-------------------------
Sprint 6: histórico paginado, métricas e dashboard operacional.
Sprint 9A: campos de decisão humana em InspectionItem e métricas operacionais.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class InspectionItem(BaseModel):
    """Registro de inspeção — usado nas listagens paginadas."""

    id:            int
    barcode:       str
    valid:         bool
    confidence:    float
    weight:        float
    product_name:  str | None
    reason:        str | None
    created_at:    datetime

    # Sprint 9A — decisão humana do operador
    decision:         str = "PENDING"
    decision_reason:  str | None = None
    reviewed_at:      datetime | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_inspection(cls, inspection) -> "InspectionItem":
        """
        Constrói o schema a partir do model ORM Inspection.
        Mapeia is_valid → valid; inclui campos de decisão (Sprint 9A).
        """
        return cls(
            id=inspection.id,
            barcode=inspection.barcode,
            valid=inspection.is_valid,
            confidence=inspection.confidence,
            weight=inspection.weight,
            product_name=inspection.product_name,
            reason=inspection.reason,
            created_at=inspection.created_at,
            # Sprint 9A
            decision=getattr(inspection, "decision", "PENDING"),
            decision_reason=getattr(inspection, "decision_reason", None),
            reviewed_at=getattr(inspection, "reviewed_at", None),
        )


class PaginatedInspections(BaseModel):
    items:     list[InspectionItem]
    total:     int
    page:      int
    page_size: int


class MetricsResponse(BaseModel):
    """Métricas do sistema — Sprint 6 + métricas de decisão Sprint 9A."""
    total:      int
    approved:   int   # aprovados automaticamente (is_valid=True)
    rejected:   int   # reprovados automaticamente (is_valid=False)
    error_rate: float
    fps:        float

    # Sprint 9A — métricas de decisão humana
    decision_approved: int   = 0
    decision_rejected: int   = 0
    decision_pending:  int   = 0
    approval_rate:     float = 0.0
    rejection_rate:    float = 0.0


class HourlyBucket(BaseModel):
    hour:     str
    total:    int
    approved: int
    rejected: int


class DashboardResponse(BaseModel):
    total_inspections: int
    approved:          int
    rejected:          int
    error_rate:        float
    last_24h:          list[HourlyBucket]

    # Sprint 9A — métricas de decisão humana
    decision_approved: int   = 0
    decision_rejected: int   = 0
    decision_pending:  int   = 0
    approval_rate:     float = 0.0
    rejection_rate:    float = 0.0
