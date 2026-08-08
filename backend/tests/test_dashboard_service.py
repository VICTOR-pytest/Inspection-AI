"""
Testes unitários do dashboard_service.
Cobrem persist_event() e cálculo de métricas com SQLite em memória.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base
from app.models import Inspection, Product  # noqa: F401
from app.services.dashboard_service import get_metrics, persist_event

SQLITE_URL = "sqlite:///./test_dashboard_service.db"
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


def _make_product(db, barcode="789123456", name="Produto Teste A",
                   expected_weight=1.0, tolerance=0.05):
    p = Product(
        name=name, barcode=barcode,
        expected_weight=expected_weight, tolerance=tolerance, is_active=True,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


class TestPersistEvent:
    def test_persiste_evento_valido(self, db):
        _make_product(db)
        event = {
            "type": "inspection", "barcode": "789123456",
            "valid": True, "confidence": 0.95, "weight": 1.02,
            "product_name": "Produto Teste A", "reason": None,
        }
        persist_event(db, event)

        rows = db.query(Inspection).all()
        assert len(rows) == 1
        assert rows[0].barcode == "789123456"
        assert rows[0].is_valid is True
        assert rows[0].confidence == 0.95
        assert rows[0].product_name == "Produto Teste A"
        assert rows[0].product_id is not None

    def test_persiste_evento_barcode_desconhecido(self, db):
        event = {
            "type": "inspection", "barcode": "NAOEXISTE",
            "valid": False, "confidence": 0.80, "weight": 1.0,
            "product_name": None, "reason": "Barcode não encontrado no catálogo.",
        }
        persist_event(db, event)

        rows = db.query(Inspection).all()
        assert len(rows) == 1
        assert rows[0].product_id is None
        assert rows[0].is_valid is False

    def test_ignora_eventos_que_nao_sao_inspection(self, db):
        event = {"type": "line_status", "status": "online"}
        persist_event(db, event)
        assert db.query(Inspection).count() == 0

    def test_barcode_nulo_vira_undetected(self, db):
        event = {
            "type": "inspection", "barcode": None,
            "valid": False, "confidence": 0.0, "weight": 1.0,
            "product_name": None, "reason": "Nenhum barcode detectado.",
        }
        persist_event(db, event)
        row = db.query(Inspection).first()
        assert row.barcode == "UNDETECTED"


class TestGetMetrics:
    def test_metricas_vazias(self, db):
        m = get_metrics(db, fps=0.0)
        assert m.total == 0
        assert m.approved == 0
        assert m.rejected == 0
        assert m.error_rate == 0.0

    def test_metricas_com_dados(self, db):
        _make_product(db)
        for valid in [True, True, True, False]:
            persist_event(db, {
                "type": "inspection", "barcode": "789123456",
                "valid": valid, "confidence": 0.9, "weight": 1.0,
                "product_name": "Produto Teste A", "reason": None,
            })

        m = get_metrics(db, fps=2.5)
        assert m.total == 4
        assert m.approved == 3
        assert m.rejected == 1
        assert m.error_rate == 0.25
        assert m.fps == 2.5
