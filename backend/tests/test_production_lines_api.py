"""
tests/test_production_lines_api.py
------------------------------------
Sprint 10C.1 — Testes de API para ProductionLine (POST/GET /lines).

Usa SQLite em memória — não requer PostgreSQL, seguindo o mesmo padrão
dos demais arquivos de teste do projeto (test_inspection_api.py etc).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base, get_db
import app.models  # noqa: F401 — registra todas as tabelas, incluindo as novas (deve vir antes do import abaixo)
from app.main import app

SQLITE_URL = "sqlite:///./test_production_lines_api.db"

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


def _payload(**overrides):
    base = {
        "code": "L01",
        "name": "Linha 01",
        "description": "Linha principal de envase",
        "is_active": True,
    }
    base.update(overrides)
    return base


class TestCreateProductionLine:

    def test_criar_linha_retorna_201(self, client):
        resp = client.post("/lines/", json=_payload())
        assert resp.status_code == 201

    def test_criar_linha_retorna_campos_corretos(self, client):
        resp = client.post("/lines/", json=_payload())
        body = resp.json()
        assert body["code"] == "L01"
        assert body["name"] == "Linha 01"
        assert body["is_active"] is True
        assert "id" in body
        assert "created_at" in body
        assert "updated_at" in body

    def test_criar_linha_sem_description_e_valido(self, client):
        payload = _payload()
        payload.pop("description")
        resp = client.post("/lines/", json=payload)
        assert resp.status_code == 201
        assert resp.json()["description"] is None

    def test_criar_linha_is_active_default_true(self, client):
        payload = _payload()
        payload.pop("is_active")
        resp = client.post("/lines/", json=payload)
        assert resp.status_code == 201
        assert resp.json()["is_active"] is True

    def test_criar_linha_com_code_duplicado_retorna_409(self, client):
        client.post("/lines/", json=_payload(code="L02"))
        resp = client.post("/lines/", json=_payload(code="L02", name="Outra Linha"))
        assert resp.status_code == 409

    def test_criar_linha_sem_code_retorna_422(self, client):
        payload = _payload()
        payload.pop("code")
        resp = client.post("/lines/", json=payload)
        assert resp.status_code == 422

    def test_criar_linha_sem_name_retorna_422(self, client):
        payload = _payload()
        payload.pop("name")
        resp = client.post("/lines/", json=payload)
        assert resp.status_code == 422

    def test_criar_linha_code_vazio_retorna_422(self, client):
        resp = client.post("/lines/", json=_payload(code=""))
        assert resp.status_code == 422


class TestListProductionLines:

    def test_listar_linhas_vazio(self, client):
        resp = client.get("/lines/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_listar_linhas_retorna_criadas(self, client):
        client.post("/lines/", json=_payload(code="L01"))
        client.post("/lines/", json=_payload(code="L02", name="Linha 02"))
        resp = client.get("/lines/")
        assert resp.status_code == 200
        codes = {line["code"] for line in resp.json()}
        assert codes == {"L01", "L02"}


class TestGetProductionLine:

    def test_buscar_linha_por_id_existente(self, client):
        created = client.post("/lines/", json=_payload()).json()
        resp = client.get(f"/lines/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["code"] == "L01"

    def test_buscar_linha_inexistente_retorna_404(self, client):
        resp = client.get("/lines/99999")
        assert resp.status_code == 404


class TestProductionLineRBAC:
    """
    Confirma que os endpoints de escrita exigem ADMIN e os de leitura
    exigem apenas autenticação — reutilizando o mecanismo real de
    autenticação (não o bypass do conftest), igual test_auth.py faz.
    """

    @pytest.fixture()
    def db(self):
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    @pytest.fixture()
    def real_auth_client(self):
        from app.core.security import get_current_user, require_admin
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_admin, None)
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        app.dependency_overrides.clear()

    @pytest.fixture()
    def operator_token(self, db):
        from app.repositories.user_repository import UserRepository
        from app.services.auth_service import create_access_token
        user = UserRepository(db).create(
            email="operator-lines@test.com",
            password="operatorpass123",
            full_name="Operador Teste",
            role="OPERATOR",
        )
        return create_access_token(user.id, user.role)

    def test_operator_nao_pode_criar_linha_retorna_403(self, real_auth_client, operator_token):
        resp = real_auth_client.post(
            "/lines/",
            json=_payload(),
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert resp.status_code == 403

    def test_sem_token_criar_linha_retorna_401(self, real_auth_client):
        resp = real_auth_client.post("/lines/", json=_payload())
        assert resp.status_code == 401

    def test_sem_token_listar_linhas_retorna_401(self, real_auth_client):
        resp = real_auth_client.get("/lines/")
        assert resp.status_code == 401
