from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.inspection_run import InspectionRun, RunStatus
from app.schemas.inspection_run import InspectionRunCreate


class InspectionRunRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, run_id: int) -> InspectionRun | None:
        return self.db.query(InspectionRun).filter(InspectionRun.id == run_id).first()

    def list_all(self) -> list[InspectionRun]:
        return self.db.query(InspectionRun).order_by(InspectionRun.id.desc()).all()

    def get_active_by_line(self, production_line_id: int) -> InspectionRun | None:
        """
        Retorna o InspectionRun ativo (finished_at IS NULL) da linha, se existir.

        Usado pela camada de API para checar a regra de "um run ativo por
        linha" ANTES do INSERT e devolver HTTP 409 com uma mensagem clara.
        A garantia definitiva contra condições de corrida fica a cargo do
        índice único parcial criado na migration 0007
        (ix_inspection_runs_active_line_unique).
        """
        return (
            self.db.query(InspectionRun)
            .filter(
                InspectionRun.production_line_id == production_line_id,
                InspectionRun.finished_at.is_(None),
            )
            .first()
        )

    def create(self, data: InspectionRunCreate) -> InspectionRun:
        run = InspectionRun(
            production_line_id=data.production_line_id,
            product_id=data.product_id,
            operator=data.operator,
            started_at=datetime.now(timezone.utc),
            finished_at=None,
            status=RunStatus.ACTIVE.value,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def end(self, run: InspectionRun) -> InspectionRun:
        """Encerra um run ativo: preenche finished_at e status=FINISHED."""
        run.finished_at = datetime.now(timezone.utc)
        run.status = RunStatus.FINISHED.value
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run
