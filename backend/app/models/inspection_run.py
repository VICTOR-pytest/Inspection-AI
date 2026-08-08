"""
app/models/inspection_run.py
------------------------------
Sprint 10C.1 — Model SQLAlchemy para a tabela inspection_runs.

Representa uma execução de produção (turno/lote) em uma ProductionLine:
o intervalo de tempo em que um operador está rodando um determinado
produto naquela linha, agregando as inspeções realizadas nesse período.

Regra de negócio central:
  Apenas um InspectionRun ATIVO (finished_at IS NULL) é permitido por
  linha de produção. Isso é garantido em duas camadas:
    1. Banco de dados — índice único parcial
       ix_inspection_runs_active_line_unique
       ON inspection_runs (production_line_id) WHERE finished_at IS NULL
    2. Aplicação — InspectionRunRepository.get_active_by_line() checa
       antes do INSERT e a API retorna HTTP 409 em caso de conflito.

Campos:
  id                  → PK auto-incremento
  production_line_id  → FK obrigatória para a linha
  product_id          → FK opcional para o produto sendo rodado
  started_at          → timestamp UTC de início do run
  finished_at         → timestamp UTC de término (NULL = run ativo)
  operator            → identificação livre do operador (nome/matrícula)
  status               → "ACTIVE" | "FINISHED" (espelha finished_at,
                          mantido como coluna para queries e filtros diretos)

Compatibilidade:
  Tabela nova — não altera nenhuma tabela existente.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class RunStatus(str, Enum):
    """
    Status de uma execução de produção.

    ACTIVE   → run em andamento (finished_at IS NULL)
    FINISHED → run encerrado (finished_at preenchido)

    Herda de str para serialização JSON automática pelo Pydantic.
    """
    ACTIVE   = "ACTIVE"
    FINISHED = "FINISHED"


class InspectionRun(Base):
    __tablename__ = "inspection_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    production_line_id: Mapped[int] = mapped_column(
        ForeignKey("production_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    operator: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RunStatus.ACTIVE.value,
        index=True,
    )

    production_line: Mapped["ProductionLine"] = relationship(  # noqa: F821
        "ProductionLine",
        back_populates="runs",
        lazy="joined",
    )

    product: Mapped["Product | None"] = relationship(  # noqa: F821
        "Product",
        lazy="joined",
    )

    def __repr__(self) -> str:
        return (
            f"<InspectionRun id={self.id} line_id={self.production_line_id} "
            f"status={self.status} started_at={self.started_at}>"
        )
