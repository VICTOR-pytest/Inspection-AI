"""
app/models/production_line.py
------------------------------
Sprint 10C.1 — Model SQLAlchemy para a tabela production_lines.

Fundação para suporte a múltiplas linhas de produção. Uma ProductionLine
representa uma linha física (ou lógica) da fábrica, à qual câmeras e
execuções de inspeção (InspectionRun) são associadas.

Campos:
  id          → PK auto-incremento
  code        → identificador curto e único da linha (ex: "L01")
  name        → nome legível (ex: "Linha 01")
  description → descrição livre, opcional
  is_active   → soft-delete: false desativa a linha sem perder histórico
  created_at  → timestamp UTC de criação
  updated_at  → timestamp UTC da última atualização (auto-update)

Compatibilidade:
  Tabela nova — não altera nenhuma tabela existente. A linha padrão "L01"
  é criada pela migration 0007 e usada para backfill de inspeções antigas.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class ProductionLine(Base):
    __tablename__ = "production_lines"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Identificador curto e único da linha (ex: 'L01')",
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Nome legível da linha (ex: 'Linha 01')",
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="false = linha desativada (soft-delete)",
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    cameras: Mapped[list["Camera"]] = relationship(  # noqa: F821
        "Camera",
        back_populates="production_line",
        lazy="noload",
    )

    runs: Mapped[list["InspectionRun"]] = relationship(  # noqa: F821
        "InspectionRun",
        back_populates="production_line",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return (
            f"<ProductionLine id={self.id} code={self.code!r} "
            f"name={self.name!r} active={self.is_active}>"
        )
