"""
tests/test_multiline_models.py
---------------------------------
Sprint 10C.1 — Testes diretos de models e repositories (sem HTTP):
ProductionLine, Camera, InspectionRun.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.session import Base
import app.models  # noqa: F401
from app.models.inspection_run import RunStatus
from app.models.production_line import ProductionLine
from app.repositories.camera_repository import CameraRepository
from app.repositories.inspection_run_repository import InspectionRunRepository
from app.repositories.production_line_repository import ProductionLineRepository
from app.schemas.camera import CameraCreate
from app.schemas.inspection_run import InspectionRunCreate
from app.schemas.production_line import ProductionLineCreate

SQLITE_URL = "sqlite:///./test_multiline_models.db"

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


class TestProductionLineModel:

    def test_criar_linha_via_repository(self, db):
        repo = ProductionLineRepository(db)
        line = repo.create(ProductionLineCreate(code="L01", name="Linha 01"))
        assert line.id is not None
        assert line.is_active is True
        assert line.created_at is not None
        assert line.updated_at is not None

    def test_code_unico_a_nivel_de_banco(self, db):
        db.add(ProductionLine(code="L01", name="Linha 01"))
        db.commit()
        db.add(ProductionLine(code="L01", name="Linha Duplicada"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_get_by_code(self, db):
        repo = ProductionLineRepository(db)
        repo.create(ProductionLineCreate(code="L01", name="Linha 01"))
        found = repo.get_by_code("L01")
        assert found is not None
        assert found.name == "Linha 01"

    def test_get_by_code_inexistente_retorna_none(self, db):
        repo = ProductionLineRepository(db)
        assert repo.get_by_code("INEXISTENTE") is None

    def test_list_all_ordenado_por_id(self, db):
        repo = ProductionLineRepository(db)
        repo.create(ProductionLineCreate(code="L02", name="Linha 02"))
        repo.create(ProductionLineCreate(code="L01", name="Linha 01"))
        lines = repo.list_all()
        assert [l.id for l in lines] == sorted(l.id for l in lines)


class TestCameraModel:

    def test_criar_camera_via_repository(self, db):
        line = ProductionLineRepository(db).create(
            ProductionLineCreate(code="L01", name="Linha 01")
        )
        repo = CameraRepository(db)
        cam = repo.create(CameraCreate(
            production_line_id=line.id, name="Cam 1", source="0",
        ))
        assert cam.id is not None
        assert cam.production_line_id == line.id
        assert cam.enabled is True

    def test_list_by_line_filtra_corretamente(self, db):
        l1 = ProductionLineRepository(db).create(ProductionLineCreate(code="L01", name="Linha 01"))
        l2 = ProductionLineRepository(db).create(ProductionLineCreate(code="L02", name="Linha 02"))
        repo = CameraRepository(db)
        repo.create(CameraCreate(production_line_id=l1.id, name="Cam L1", source="0"))
        repo.create(CameraCreate(production_line_id=l2.id, name="Cam L2", source="1"))

        cams_l1 = repo.list_by_line(l1.id)
        assert len(cams_l1) == 1
        assert cams_l1[0].name == "Cam L1"


class TestInspectionRunModel:

    def test_criar_run_via_repository_status_active(self, db):
        line = ProductionLineRepository(db).create(ProductionLineCreate(code="L01", name="Linha 01"))
        repo = InspectionRunRepository(db)
        run = repo.create(InspectionRunCreate(production_line_id=line.id, operator="Op"))
        assert run.status == RunStatus.ACTIVE.value
        assert run.finished_at is None
        assert run.started_at is not None

    def test_get_active_by_line_encontra_run_ativo(self, db):
        line = ProductionLineRepository(db).create(ProductionLineCreate(code="L01", name="Linha 01"))
        repo = InspectionRunRepository(db)
        created = repo.create(InspectionRunCreate(production_line_id=line.id))
        active = repo.get_active_by_line(line.id)
        assert active is not None
        assert active.id == created.id

    def test_get_active_by_line_retorna_none_apos_encerrar(self, db):
        line = ProductionLineRepository(db).create(ProductionLineCreate(code="L01", name="Linha 01"))
        repo = InspectionRunRepository(db)
        run = repo.create(InspectionRunCreate(production_line_id=line.id))
        repo.end(run)
        assert repo.get_active_by_line(line.id) is None

    def test_end_seta_finished_at_e_status(self, db):
        line = ProductionLineRepository(db).create(ProductionLineCreate(code="L01", name="Linha 01"))
        repo = InspectionRunRepository(db)
        run = repo.create(InspectionRunCreate(production_line_id=line.id))
        ended = repo.end(run)
        assert ended.finished_at is not None
        assert ended.status == RunStatus.FINISHED.value

    # A verificação de integridade referencial real (FK enforcement) é
    # testada em test_migration_0007.py contra PostgreSQL — SQLite não
    # aplica FKs por padrão neste projeto (nenhum PRAGMA foreign_keys=ON
    # é configurado), então um teste aqui daria falso-positivo.
