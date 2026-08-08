"""
tests/test_inspection_runs_api.py
------------------------------------
Sprint 10C.1 — Testes de API para InspectionRun (POST/GET /runs, PATCH /runs/{id}/end).

Cobre especialmente a regra de negócio central da sprint:
  "Não permitir dois InspectionRun ativos para a mesma linha" → HTTP 409.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base, get_db
import app.models  # noqa: F401 — deve vir antes do import abaixo
from app.main import app

SQLITE_URL = "sqlite:///./test_inspection_runs_api.db"

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
def line(client):
    resp = client.post("/lines/", json={"code": "L01", "name": "Linha 01"})
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def line2(client):
    resp = client.post("/lines/", json={"code": "L02", "name": "Linha 02"})
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def product(client):
    resp = client.post("/products/", json={
        "name": "Produto Run",
        "barcode": "RUN001",
        "expected_weight": 1.0,
        "tolerance": 0.05,
        "is_active": True,
    })
    assert resp.status_code == 201
    return resp.json()


def _payload(line_id, **overrides):
    base = {"production_line_id": line_id, "operator": "Operador Teste"}
    base.update(overrides)
    return base


class TestCreateInspectionRun:

    def test_criar_run_retorna_201(self, client, line):
        resp = client.post("/runs/", json=_payload(line["id"]))
        assert resp.status_code == 201

    def test_criar_run_retorna_campos_corretos(self, client, line):
        resp = client.post("/runs/", json=_payload(line["id"]))
        body = resp.json()
        assert body["production_line_id"] == line["id"]
        assert body["operator"] == "Operador Teste"
        assert body["status"] == "ACTIVE"
        assert body["finished_at"] is None
        assert "started_at" in body

    def test_criar_run_com_produto(self, client, line, product):
        resp = client.post("/runs/", json=_payload(line["id"], product_id=product["id"]))
        assert resp.status_code == 201
        assert resp.json()["product_id"] == product["id"]

    def test_criar_run_sem_produto_e_valido(self, client, line):
        resp = client.post("/runs/", json=_payload(line["id"]))
        assert resp.status_code == 201
        assert resp.json()["product_id"] is None

    def test_criar_run_linha_inexistente_retorna_404(self, client):
        resp = client.post("/runs/", json=_payload(99999))
        assert resp.status_code == 404


class TestRegraRunUnicoPorLinha:
    """Regra central da sprint: apenas 1 InspectionRun ativo por linha."""

    def test_segundo_run_ativo_na_mesma_linha_retorna_409(self, client, line):
        r1 = client.post("/runs/", json=_payload(line["id"]))
        assert r1.status_code == 201

        r2 = client.post("/runs/", json=_payload(line["id"]))
        assert r2.status_code == 409

    def test_mensagem_409_menciona_run_ativo(self, client, line):
        client.post("/runs/", json=_payload(line["id"]))
        resp = client.post("/runs/", json=_payload(line["id"]))
        assert "ativo" in resp.json()["detail"].lower()

    def test_runs_ativos_em_linhas_diferentes_e_permitido(self, client, line, line2):
        r1 = client.post("/runs/", json=_payload(line["id"]))
        r2 = client.post("/runs/", json=_payload(line2["id"]))
        assert r1.status_code == 201
        assert r2.status_code == 201

    def test_novo_run_apos_encerrar_o_anterior_e_permitido(self, client, line):
        r1 = client.post("/runs/", json=_payload(line["id"])).json()
        client.patch(f"/runs/{r1['id']}/end")

        r2 = client.post("/runs/", json=_payload(line["id"]))
        assert r2.status_code == 201

    def test_duas_linhas_podem_ter_um_run_ativo_cada_apos_ciclo(self, client, line, line2):
        r1 = client.post("/runs/", json=_payload(line["id"])).json()
        r2 = client.post("/runs/", json=_payload(line2["id"])).json()
        client.patch(f"/runs/{r1['id']}/end")

        r3 = client.post("/runs/", json=_payload(line["id"]))
        assert r3.status_code == 201
        # linha 2 continua ativa — nova tentativa deve falhar
        r4 = client.post("/runs/", json=_payload(line2["id"]))
        assert r4.status_code == 409


class TestEndRun:

    def test_encerrar_run_ativo_retorna_200(self, client, line):
        run = client.post("/runs/", json=_payload(line["id"])).json()
        resp = client.patch(f"/runs/{run['id']}/end")
        assert resp.status_code == 200

    def test_encerrar_run_preenche_finished_at_e_status(self, client, line):
        run = client.post("/runs/", json=_payload(line["id"])).json()
        resp = client.patch(f"/runs/{run['id']}/end")
        body = resp.json()
        assert body["finished_at"] is not None
        assert body["status"] == "FINISHED"

    def test_encerrar_run_ja_encerrado_retorna_409(self, client, line):
        run = client.post("/runs/", json=_payload(line["id"])).json()
        client.patch(f"/runs/{run['id']}/end")
        resp = client.patch(f"/runs/{run['id']}/end")
        assert resp.status_code == 409

    def test_encerrar_run_inexistente_retorna_404(self, client):
        resp = client.patch("/runs/99999/end")
        assert resp.status_code == 404


class TestListAndGetRuns:

    def test_listar_runs_vazio(self, client):
        resp = client.get("/runs/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_listar_runs_retorna_criados(self, client, line, line2):
        client.post("/runs/", json=_payload(line["id"]))
        client.post("/runs/", json=_payload(line2["id"]))
        resp = client.get("/runs/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_buscar_run_por_id_existente(self, client, line):
        created = client.post("/runs/", json=_payload(line["id"])).json()
        resp = client.get(f"/runs/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_buscar_run_inexistente_retorna_404(self, client):
        resp = client.get("/runs/99999")
        assert resp.status_code == 404


class TestInspectionRunRBAC:

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
            email="operator-runs@test.com",
            password="operatorpass123",
            full_name="Operador Teste",
            role="OPERATOR",
        )
        return create_access_token(user.id, user.role)

    def test_operator_nao_pode_criar_run_retorna_403(self, real_auth_client, operator_token):
        resp = real_auth_client.post(
            "/runs/",
            json=_payload(1),
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert resp.status_code == 403

    def test_operator_nao_pode_encerrar_run_retorna_403(self, real_auth_client, operator_token):
        resp = real_auth_client.patch(
            "/runs/1/end",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert resp.status_code == 403
