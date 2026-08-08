"""
tests/test_pr006_integration.py
-----------------------------------
Sprint 10C.2 (PR-006) — Integração automática.

Testa dashboard_service.persist_event() de ponta a ponta: um evento com
line_id/camera_id (como o VisionWorker gera) deve resultar em uma
Inspection com esses campos preenchidos, e com inspection_run_id
resolvido automaticamente a partir do InspectionRun ATIVO daquela linha
— tudo sem nenhum preenchimento manual.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base
from app.models import Inspection, Product  # noqa: F401
from app.models.production_line import ProductionLine
from app.models.inspection_run import InspectionRun, RunStatus
from app.services.dashboard_service import persist_event

SQLITE_URL = "sqlite:///./test_pr006_integration.db"
engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _base_event(**overrides) -> dict:
    base = {
        "type": "inspection",
        "barcode": "555444333",
        "valid": True,
        "confidence": 0.95,
        "weight": 1.0,
        "product_name": "Produto PR006",
        "reason": None,
    }
    base.update(overrides)
    return base


class TestPreenchimentoAutomaticoDeLineECamera:

    def test_evento_com_line_id_preenche_inspection_line_id(self, db):
        line = ProductionLine(code="L01", name="Linha 01")
        db.add(line)
        db.commit()
        db.refresh(line)

        event = _base_event(line_id=line.id, camera_id=None)
        inspection = persist_event(db, event)

        assert inspection is not None
        assert inspection.line_id == line.id

    def test_evento_com_camera_id_preenche_inspection_camera_id(self, db):
        line = ProductionLine(code="L01", name="Linha 01")
        db.add(line)
        db.commit()
        db.refresh(line)

        event = _base_event(line_id=line.id, camera_id=99)
        inspection = persist_event(db, event)

        assert inspection.camera_id == 99

    def test_evento_sem_line_id_persiste_com_null_como_antes(self, db):
        """Retrocompatibilidade: evento 'legado' (sem line_id) → NULL."""
        event = _base_event()  # sem line_id/camera_id
        inspection = persist_event(db, event)

        assert inspection.line_id is None
        assert inspection.camera_id is None
        assert inspection.inspection_run_id is None


class TestResolucaoAutomaticaDeInspectionRun:

    def test_com_run_ativo_resolve_inspection_run_id(self, db):
        line = ProductionLine(code="L01", name="Linha 01")
        db.add(line)
        db.commit()
        db.refresh(line)

        run = InspectionRun(production_line_id=line.id, status=RunStatus.ACTIVE.value)
        db.add(run)
        db.commit()
        db.refresh(run)

        event = _base_event(line_id=line.id, camera_id=None)
        inspection = persist_event(db, event)

        assert inspection.inspection_run_id == run.id

    def test_sem_run_ativo_inspection_run_id_fica_none(self, db):
        line = ProductionLine(code="L01", name="Linha 01")
        db.add(line)
        db.commit()
        db.refresh(line)
        # nenhum InspectionRun criado

        event = _base_event(line_id=line.id)
        inspection = persist_event(db, event)

        assert inspection.inspection_run_id is None

    def test_run_finalizado_nao_e_resolvido_como_ativo(self, db):
        from datetime import datetime, timezone

        line = ProductionLine(code="L01", name="Linha 01")
        db.add(line)
        db.commit()
        db.refresh(line)

        finished_run = InspectionRun(
            production_line_id=line.id,
            status=RunStatus.FINISHED.value,
            finished_at=datetime.now(timezone.utc),
        )
        db.add(finished_run)
        db.commit()

        event = _base_event(line_id=line.id)
        inspection = persist_event(db, event)

        assert inspection.inspection_run_id is None

    def test_run_ativo_de_outra_linha_nao_e_usado(self, db):
        line1 = ProductionLine(code="L01", name="Linha 01")
        line2 = ProductionLine(code="L02", name="Linha 02")
        db.add_all([line1, line2])
        db.commit()
        db.refresh(line1)
        db.refresh(line2)

        run_line2 = InspectionRun(production_line_id=line2.id, status=RunStatus.ACTIVE.value)
        db.add(run_line2)
        db.commit()

        # Evento vem da linha 1 — run ativo é da linha 2, não deve ser usado
        event = _base_event(line_id=line1.id)
        inspection = persist_event(db, event)

        assert inspection.inspection_run_id is None

    def test_falha_ao_resolver_run_nao_impede_persistencia(self, db, monkeypatch):
        """
        Se a resolução do run ativo falhar por qualquer motivo, a
        inspeção ainda deve ser persistida (com inspection_run_id=None) —
        nunca falhar a inspeção por causa disso.
        """
        line = ProductionLine(code="L01", name="Linha 01")
        db.add(line)
        db.commit()
        db.refresh(line)

        import app.repositories.inspection_run_repository as run_repo_module

        def _boom(self, production_line_id):
            raise RuntimeError("falha simulada")

        monkeypatch.setattr(
            run_repo_module.InspectionRunRepository, "get_active_by_line", _boom
        )

        event = _base_event(line_id=line.id)
        inspection = persist_event(db, event)

        assert inspection is not None
        assert inspection.inspection_run_id is None


class TestNaoQuebraContratoAntigo:

    def test_persist_event_retorna_none_para_evento_nao_inspection(self, db):
        result = persist_event(db, {"type": "heartbeat"})
        assert result is None

    def test_persist_event_sem_jpeg_bytes_funciona(self, db):
        event = _base_event()
        inspection = persist_event(db, event)
        assert inspection is not None
        assert inspection.barcode == "555444333"
