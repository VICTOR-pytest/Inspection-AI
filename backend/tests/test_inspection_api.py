"""
Testes de integração para POST /inspection/check e CRUD de produtos.
Usa SQLite em memória — não requer PostgreSQL.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base, get_db
from app.main import app
from app.models import Inspection, Product  # noqa: F401 — registra tabelas

SQLITE_URL = "sqlite:///./test_integration.db"

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


# ---------------------------------------------------------------------------
# Produtos
# ---------------------------------------------------------------------------

class TestProducts:
    def test_criar_produto(self, client):
        resp = client.post("/products/", json={
            "name": "Produto X",
            "barcode": "000111222",
            "expected_weight": 0.5,
        })
        assert resp.status_code == 201
        assert resp.json()["barcode"] == "000111222"
        assert resp.json()["tolerance"] == 0.05

    def test_barcode_duplicado_retorna_409(self, client, produto_a):
        resp = client.post("/products/", json={
            "name": "Duplicado",
            "barcode": "789123456",
            "expected_weight": 2.0,
        })
        assert resp.status_code == 409

    def test_listar_produtos(self, client, produto_a):
        resp = client.get("/products/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# Inspeção
# ---------------------------------------------------------------------------

class TestInspectionCheck:
    def test_inspecao_valida(self, client, produto_a):
        """Cenário da spec: barcode 789123456, peso 1.02 → válido"""
        resp = client.post("/inspection/check", json={
            "barcode": "789123456",
            "weight": 1.02,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["barcode_ok"] is True
        assert data["weight_ok"] is True
        assert data["valid"] is True
        assert data["product_name"] == "Produto Teste A"
        assert data["reason"] is None

    def test_barcode_nao_encontrado(self, client):
        resp = client.post("/inspection/check", json={
            "barcode": "INEXISTENTE",
            "weight": 1.0,
        })
        data = resp.json()
        assert data["barcode_ok"] is False
        assert data["valid"] is False

    def test_peso_abaixo(self, client, produto_a):
        resp = client.post("/inspection/check", json={
            "barcode": "789123456",
            "weight": 0.80,
        })
        data = resp.json()
        assert data["barcode_ok"] is True
        assert data["weight_ok"] is False
        assert data["valid"] is False

    def test_peso_acima(self, client, produto_a):
        resp = client.post("/inspection/check", json={
            "barcode": "789123456",
            "weight": 1.20,
        })
        assert resp.json()["weight_ok"] is False

    def test_inspecao_persistida(self, client, produto_a):
        client.post("/inspection/check", json={"barcode": "789123456", "weight": 1.0})
        client.post("/inspection/check", json={"barcode": "789123456", "weight": 0.5})
        resp = client.get("/inspection/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
