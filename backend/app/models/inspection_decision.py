"""
app/models/inspection_decision.py
----------------------------------
Sprint 9B.1 — Audit trail imutável de decisões humanas.

Design intencional:
  - Tabela APPEND-ONLY: nenhuma row é deletada ou atualizada
  - Cada decisão cria um novo registro, preservando histórico completo
  - inspection.decision continua como "estado atual" para queries rápidas
  - Esta tabela responde a: quem decidiu o quê, quando, sobre qual inspeção

Cardinalidade:
  1 Inspection → 0..N InspectionDecision
  1 User       → 0..N InspectionDecision

Compliance:
  Satisfaz requisitos ISO 9001 de rastreabilidade de decisões de qualidade.
  Permite auditoria: "quem aprovou inspeção X às 14h23 de ontem?"
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class InspectionDecision(Base):
    __tablename__ = "inspection_decisions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # FK para a inspeção sobre a qual foi tomada a decisão
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Inspeção sobre a qual foi tomada esta decisão",
    )

    # FK para o operador que tomou a decisão
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
        comment="Operador que tomou a decisão",
    )

    # Valor da decisão no momento do registro
    decision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Decisão tomada: APPROVED | REJECTED | PENDING",
    )

    # Motivo (obrigatório para REJECTED, opcional para outros)
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Motivo da decisão — obrigatório quando REJECTED",
    )

    # Timestamp imutável — definido no momento da inserção, nunca atualizado
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Timestamp UTC da decisão — imutável",
    )

    # Relacionamentos de leitura (lazy=noload por padrão — não carrega automaticamente)
    user: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="decisions",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return (
            f"<InspectionDecision id={self.id} "
            f"inspection_id={self.inspection_id} "
            f"user_id={self.user_id} "
            f"decision={self.decision!r} "
            f"at={self.created_at}>"
        )
