"""
app/repositories/decision_repository.py
-----------------------------------------
Sprint 9B.1 — Repositório do audit trail de decisões humanas.

Design: APPEND-ONLY — nunca atualiza ou deleta registros.
Cada chamada a create() gera um novo registro imutável.

Permite:
  - Rastrear o histórico completo de decisões sobre uma inspeção
  - Saber quem tomou cada decisão e quando
  - Cumprir requisitos de auditoria ISO 9001
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.inspection_decision import InspectionDecision


class DecisionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        inspection_id: int,
        user_id: int,
        decision: str,
        reason: str | None = None,
    ) -> InspectionDecision:
        """
        Registra uma decisão no audit trail.

        Esta operação é SEMPRE um INSERT — nunca um UPDATE.
        O registro criado é imutável: reflete o estado exato no momento da decisão.
        """
        record = InspectionDecision(
            inspection_id=inspection_id,
            user_id=user_id,
            decision=decision,
            reason=reason,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_by_inspection(self, inspection_id: int) -> list[InspectionDecision]:
        """
        Lista todas as decisões de uma inspeção em ordem cronológica.

        A última decisão da lista é a mais recente (estado atual).
        """
        stmt = (
            select(InspectionDecision)
            .where(InspectionDecision.inspection_id == inspection_id)
            .order_by(InspectionDecision.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_by_user(self, user_id: int, limit: int = 100) -> list[InspectionDecision]:
        """Lista as decisões mais recentes de um usuário específico."""
        stmt = (
            select(InspectionDecision)
            .where(InspectionDecision.user_id == user_id)
            .order_by(InspectionDecision.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_by_user(self, user_id: int) -> int:
        """Conta total de decisões tomadas por um usuário."""
        from sqlalchemy import func
        return self.db.execute(
            select(func.count())
            .select_from(InspectionDecision)
            .where(InspectionDecision.user_id == user_id)
        ).scalar_one()
