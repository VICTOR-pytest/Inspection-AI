"""
app/models/camera.py
---------------------
Sprint 10C.1 — Model SQLAlchemy para a tabela cameras.

Representa uma câmera física ou simulada associada a uma ProductionLine.
Não deve ser confundida com `vision.camera.Camera`, que é um wrapper de
hardware sobre cv2.VideoCapture — este model é puramente de domínio/banco.

Campos:
  id                 → PK auto-incremento
  production_line_id → FK obrigatória para a linha à qual pertence
  name               → nome legível (ex: "Câmera Entrada")
  source             → identificador da fonte (índice, URL RTSP, path etc.)
  resolution         → resolução no formato "WxH" (ex: "1280x720")
  fps                → taxa de quadros alvo
  enabled            → se a câmera está habilitada para uso
  created_at         → timestamp UTC de criação

Compatibilidade:
  Tabela nova — não altera nenhuma tabela existente.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    production_line_id: Mapped[int] = mapped_column(
        ForeignKey("production_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    source: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Identificador da fonte: índice de webcam, URL RTSP, path de vídeo etc.",
    )

    resolution: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Resolução no formato 'WxH' (ex: '1280x720')",
    )

    fps: Mapped[float | None] = mapped_column(Float, nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    production_line: Mapped["ProductionLine"] = relationship(  # noqa: F821
        "ProductionLine",
        back_populates="cameras",
        lazy="joined",
    )

    def __repr__(self) -> str:
        return (
            f"<Camera id={self.id} name={self.name!r} "
            f"line_id={self.production_line_id} enabled={self.enabled}>"
        )
