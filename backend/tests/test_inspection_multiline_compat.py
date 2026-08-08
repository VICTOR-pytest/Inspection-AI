"""
tests/test_inspection_multiline_compat.py
--------------------------------------------
Sprint 10C.1 — Garante que a API de Inspection existente continua
funcionando sem nenhuma alteração de payload após a adição dos campos
opcionais line_id, camera_id, inspection_run_id.

Zero regressões: nada que funcionava antes deixa de funcionar.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base, get_db
import app.models  # noqa: F401 — deve vir antes do import abaixo
from app.main import app
from app.models.inspection import Inspection
from app.models.production_line import ProductionLine

SQLITE_URL = "sqlite:///./test_inspection_multiline_compat.db"

engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


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


@pytest.fixture()
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestInspectionModelCompat:

    def test_inspection_pode_ser_criada_sem_campos_multiline(self, db):
        """Simula uma inspeção 'antiga', sem nenhum dos novos campos."""
        insp = Inspection(
            barcode="OLD001",
            weight=100.0,
            is_valid=True,
            confidence=0.95,
            product_name="Produto Antigo",
            decision="APPROVED",
        )
        db.add(insp)
        db.commit()
        db.refresh(insp)
        assert insp.id is not None
        assert insp.line_id is None
        assert insp.camera_id is None
        assert insp.inspection_run_id is None

    def test_inspection_aceita_line_id_quando_informado(self, db):
        line = ProductionLine(code="L01", name="Linha 01")
        db.add(line)
        db.commit()
        db.refresh(line)

        insp = Inspection(
            barcode="NEW001",
            weight=100.0,
            is_valid=True,
            confidence=0.95,
            decision="APPROVED",
            line_id=line.id,
        )
        db.add(insp)
        db.commit()
        db.refresh(insp)
        assert insp.line_id == line.id


class TestInspectionApiCompat:
    """
    Confirma que POST /inspection/check e o restante da API de Inspection
    continuam funcionando exatamente como antes, sem exigir os novos campos.
    """

    @pytest.fixture()
    def produto(self, client):
        resp = client.post("/products/", json={
            "name": "Produto Compat",
            "barcode": "COMPAT001",
            "expected_weight": 1.0,
            "tolerance": 0.05,
            "is_active": True,
        })
        assert resp.status_code == 201
        return resp.json()

    def test_post_inspection_check_sem_campos_multiline_funciona(self, client, produto):
        resp = client.post("/inspection/check", json={
            "barcode": produto["barcode"],
            "weight": 1.0,
        })
        assert resp.status_code == 200

    def test_resposta_de_inspection_check_nao_exige_novos_campos(self, client, produto):
        resp = client.post("/inspection/check", json={
            "barcode": produto["barcode"],
            "weight": 1.0,
        })
        body = resp.json()
        # A resposta deve manter exatamente o contrato antigo
        # (InspectionResult) — nenhum campo novo é exigido nem quebra a
        # serialização existente.
        assert set(body.keys()) == {
            "barcode_ok", "weight_ok", "valid", "product_name", "reason",
        }
