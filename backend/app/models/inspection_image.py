"""
app/models/inspection_image.py
--------------------------------
Sprint 7B — Modelo SQLAlchemy para a tabela inspection_images.
Sprint 8C — Adiciona coluna `variant` para suportar múltiplas imagens por inspeção.

Cardinalidade: 1 Inspection → 0..N InspectionImage
  Sprint 7B assumia 0..1 (unique em inspection_id).
  Sprint 8B introduziu imagens anotadas, exigindo 0..N com unicidade
  composta em (inspection_id, variant).

Variantes suportadas:
  "original"  → frame bruto capturado pela câmera/simulador
  "annotated" → frame com overlay de bounding boxes YOLO (Sprint 8B)

Constraint no banco: UNIQUE(inspection_id, variant)
  → no máximo 1 original + 1 annotated por inspeção
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

# Tipo literal para as variantes válidas
ImageVariant = Literal["original", "annotated"]


class InspectionImage(Base):
    __tablename__ = "inspection_images"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # FK para a inspeção dona desta imagem
    # Sprint 8C: NÃO é mais unique isolado.
    # O unique composto (inspection_id, variant) é definido na migration 0004.
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,   # índice simples para FK lookups (criado pela migration 0004)
    )

    # Caminho relativo a settings.storage_path
    # Sprint 7B: "images/2026/06/21/inspection_42_abc123.jpg"
    # Sprint 8B: "images/original/2026/06/21/..." ou "images/annotated/..."
    file_path: Mapped[str] = mapped_column(Text, nullable=False)

    # Sprint 8C: tipo da imagem
    # "original"  → frame capturado sem modificação
    # "annotated" → frame com overlay de detecção YOLO (bounding boxes, label, confidence)
    # Constraint UNIQUE(inspection_id, variant) está na migration 0004.
    variant: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="original",
        comment="Tipo da imagem: 'original' ou 'annotated'",
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relacionamento reverso
    inspection: Mapped["Inspection"] = relationship(  # noqa: F821
        "Inspection",
        back_populates="images",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return (
            f"<InspectionImage id={self.id} "
            f"inspection_id={self.inspection_id} "
            f"variant={self.variant!r} "
            f"path={self.file_path!r}>"
        )
