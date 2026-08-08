from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class DecisionStatus(str, Enum):
    """
    Status de decisão humana de uma inspeção.

    PENDING  → ainda não revisada pelo operador (estado inicial)
    APPROVED → operador aprovou a inspeção
    REJECTED → operador reprovou a inspeção (motivo em decision_reason)

    Herda de str para serialização JSON automática pelo Pydantic.
    """
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Inspection(Base):
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    barcode: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # Sprint 6 — campos desnormalizados, espelham o evento WebSocket do EventBus
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # FK opcional — NULL quando barcode não existe no catálogo
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    product: Mapped["Product | None"] = relationship("Product", lazy="joined")  # noqa: F821

    # Sprint 7B → Sprint 8C — imagens associadas à inspeção (0..N)
    images: Mapped[list["InspectionImage"]] = relationship(  # noqa: F821
        "InspectionImage",
        back_populates="inspection",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    # Sprint 9A — decisão humana do operador
    # decision: estado de revisão (PENDING por default, sem migração de dados existentes)
    # decision_reason: motivo (obrigatório pelo endpoint quando REJECTED)
    # reviewed_at: preenchido automaticamente pelo servidor no momento da decisão
    decision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DecisionStatus.PENDING.value,
        index=True,
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Sprint 10C.1 — fundação multi-linha (Foundation Multi-Line)
    # Todos nullable para compatibilidade total com inspeções existentes.
    # Inspeções antigas são migradas para a linha padrão "L01" via migration 0007;
    # camera_id e inspection_run_id permanecem NULL para dados históricos, pois
    # não é possível inferir retroativamente qual câmera/run gerou o registro.
    line_id: Mapped[int | None] = mapped_column(
        ForeignKey("production_lines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"),
        nullable=True,
    )
    inspection_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("inspection_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    production_line: Mapped["ProductionLine | None"] = relationship(  # noqa: F821
        "ProductionLine", lazy="noload"
    )
    camera: Mapped["Camera | None"] = relationship("Camera", lazy="noload")  # noqa: F821
    inspection_run: Mapped["InspectionRun | None"] = relationship(  # noqa: F821
        "InspectionRun", lazy="noload"
    )

    def __repr__(self) -> str:
        return (
            f"<Inspection id={self.id} barcode={self.barcode!r} "
            f"valid={self.is_valid} decision={self.decision} at={self.created_at}>"
        )
