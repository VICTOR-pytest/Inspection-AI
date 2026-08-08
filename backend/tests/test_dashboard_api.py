"""
Testes de integração dos endpoints REST do Sprint 6:
  GET /api/v1/inspections
  GET /api/v1/inspections/{id}
  GET /api/v1/metrics
  GET /api/v1/dashboard

Usa SQLite em memória — não requer PostgreSQL. A agregação horária
(hourly_breakdown) é feita em Python no repository, portável entre
SQLite e PostgreSQL.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base, get_db
from app.main import app
from app.models import Inspection, Product  # noqa: F401
from app.services.dashboard_service import persist_event

SQLITE_URL = "sqlite:///./test_dashboard_api.db"
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
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def produto_a(client):
    resp = client.post("/products/", json={
        "name": "Produto Teste A",
        "barcode": "789123456",
        "expected_weight": 1.0,
        "tolerance": 0.05,
        "is_active": True,
    })
    assert resp.status_code == 201
    return resp.json()


def _seed_inspections(db_factory, n_approved=3, n_rejected=2):
    db = db_factory()
    try:
        for _ in range(n_approved):
            persist_event(db, {
                "type": "inspection", "barcode": "789123456",
                "valid": True, "confidence": 0.95, "weight": 1.0,
                "product_name": "Produto Teste A", "reason": None,
            })
        for _ in range(n_rejected):
            persist_event(db, {
                "type": "inspection", "barcode": "789123456",
                "valid": False, "confidence": 0.60, "weight": 0.5,
                "product_name": "Produto Teste A", "reason": "Peso fora da tolerância.",
            })
    finally:
        db.close()


class TestListInspectionsV1:
    def test_lista_vazia(self, client):
        resp = client.get("/api/v1/inspections")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 50

    def test_lista_com_dados(self, client, produto_a):
        _seed_inspections(TestingSessionLocal, n_approved=3, n_rejected=2)
        resp = client.get("/api/v1/inspections")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5

    def test_filtro_por_valid_true(self, client, produto_a):
        _seed_inspections(TestingSessionLocal, n_approved=3, n_rejected=2)
        resp = client.get("/api/v1/inspections?valid=true")
        data = resp.json()
        assert data["total"] == 3
        assert all(item["valid"] is True for item in data["items"])

    def test_filtro_por_valid_false(self, client, produto_a):
        _seed_inspections(TestingSessionLocal, n_approved=3, n_rejected=2)
        resp = client.get("/api/v1/inspections?valid=false")
        assert resp.json()["total"] == 2

    def test_filtro_por_barcode(self, client, produto_a):
        _seed_inspections(TestingSessionLocal, n_approved=1, n_rejected=0)
        resp = client.get("/api/v1/inspections?barcode=789123456")
        assert resp.json()["total"] == 1
        resp_miss = client.get("/api/v1/inspections?barcode=000000")
        assert resp_miss.json()["total"] == 0

    def test_paginacao(self, client, produto_a):
        _seed_inspections(TestingSessionLocal, n_approved=5, n_rejected=0)
        resp = client.get("/api/v1/inspections?page=1&page_size=2")
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2

        resp_p2 = client.get("/api/v1/inspections?page=2&page_size=2")
        assert len(resp_p2.json()["items"]) == 2

    def test_ordenacao_oldest(self, client, produto_a):
        _seed_inspections(TestingSessionLocal, n_approved=2, n_rejected=0)
        resp = client.get("/api/v1/inspections?sort=oldest")
        assert resp.status_code == 200

    def test_sort_invalido_retorna_422(self, client):
        resp = client.get("/api/v1/inspections?sort=invalido")
        assert resp.status_code == 422


class TestGetInspectionV1:
    def test_detalhe_existente(self, client, produto_a):
        _seed_inspections(TestingSessionLocal, n_approved=1, n_rejected=0)
        list_resp = client.get("/api/v1/inspections")
        inspection_id = list_resp.json()["items"][0]["id"]

        resp = client.get(f"/api/v1/inspections/{inspection_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == inspection_id

    def test_detalhe_inexistente_404(self, client):
        resp = client.get("/api/v1/inspections/99999")
        assert resp.status_code == 404


class TestMetricsV1:
    def test_metrics_vazio(self, client):
        resp = client.get("/api/v1/metrics")
        assert resp.status_code == 200
        data = resp.json()
        # fps vem do event_bus singleton e pode não ser zero se outros testes
        # ativaram o VisionWorker — verificamos apenas os campos do banco.
        assert data["total"] == 0
        assert data["approved"] == 0
        assert data["rejected"] == 0
        assert data["error_rate"] == 0.0
        assert "fps" in data

    def test_metrics_com_dados(self, client, produto_a):
        _seed_inspections(TestingSessionLocal, n_approved=3, n_rejected=1)
        resp = client.get("/api/v1/metrics")
        data = resp.json()
        assert data["total"] == 4
        assert data["approved"] == 3
        assert data["rejected"] == 1
        assert data["error_rate"] == 0.25


class TestDashboardV1:
    def test_dashboard_vazio(self, client):
        resp = client.get("/api/v1/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_inspections"] == 0
        assert data["approved"] == 0
        assert data["rejected"] == 0
        assert data["last_24h"] == []

    def test_dashboard_com_dados(self, client, produto_a):
        _seed_inspections(TestingSessionLocal, n_approved=3, n_rejected=2)
        resp = client.get("/api/v1/dashboard")
        data = resp.json()
        assert data["total_inspections"] == 5
        assert data["approved"] == 3
        assert data["rejected"] == 2
        assert data["error_rate"] == 0.4
        assert len(data["last_24h"]) >= 1
        bucket = data["last_24h"][0]
        assert "hour" in bucket
        assert bucket["total"] == 5
