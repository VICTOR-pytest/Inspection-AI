"""
tests/test_cameras_api.py
---------------------------
Sprint 10C.1 — Testes de API para Camera (POST/GET /cameras).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base, get_db
import app.models  # noqa: F401 — deve vir antes do import abaixo
from app.main import app

SQLITE_URL = "sqlite:///./test_cameras_api.db"

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


def _payload(line_id, **overrides):
    base = {
        "production_line_id": line_id,
        "name": "Câmera Entrada",
        "source": "rtsp://192.168.0.10/stream1",
        "resolution": "1280x720",
        "fps": 30.0,
        "enabled": True,
    }
    base.update(overrides)
    return base


class TestCreateCamera:

    def test_criar_camera_retorna_201(self, client, line):
        resp = client.post("/cameras/", json=_payload(line["id"]))
        assert resp.status_code == 201

    def test_criar_camera_retorna_campos_corretos(self, client, line):
        resp = client.post("/cameras/", json=_payload(line["id"]))
        body = resp.json()
        assert body["name"] == "Câmera Entrada"
        assert body["production_line_id"] == line["id"]
        assert body["resolution"] == "1280x720"
        assert body["fps"] == 30.0
        assert body["enabled"] is True
        assert "id" in body
        assert "created_at" in body

    def test_criar_camera_sem_resolution_e_fps_e_valido(self, client, line):
        payload = _payload(line["id"])
        payload.pop("resolution")
        payload.pop("fps")
        resp = client.post("/cameras/", json=payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["resolution"] is None
        assert body["fps"] is None

    def test_criar_camera_enabled_default_true(self, client, line):
        payload = _payload(line["id"])
        payload.pop("enabled")
        resp = client.post("/cameras/", json=payload)
        assert resp.status_code == 201
        assert resp.json()["enabled"] is True

    def test_criar_camera_linha_inexistente_retorna_404(self, client):
        resp = client.post("/cameras/", json=_payload(99999))
        assert resp.status_code == 404

    def test_criar_camera_sem_source_retorna_422(self, client, line):
        payload = _payload(line["id"])
        payload.pop("source")
        resp = client.post("/cameras/", json=payload)
        assert resp.status_code == 422

    def test_criar_camera_fps_negativo_retorna_422(self, client, line):
        resp = client.post("/cameras/", json=_payload(line["id"], fps=-5))
        assert resp.status_code == 422

    def test_criar_duas_cameras_na_mesma_linha_e_permitido(self, client, line):
        r1 = client.post("/cameras/", json=_payload(line["id"], name="Cam 1"))
        r2 = client.post("/cameras/", json=_payload(line["id"], name="Cam 2"))
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]


class TestListCameras:

    def test_listar_cameras_vazio(self, client):
        resp = client.get("/cameras/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_listar_cameras_retorna_criadas(self, client, line):
        client.post("/cameras/", json=_payload(line["id"], name="Cam 1"))
        client.post("/cameras/", json=_payload(line["id"], name="Cam 2"))
        resp = client.get("/cameras/")
        assert resp.status_code == 200
        names = {c["name"] for c in resp.json()}
        assert names == {"Cam 1", "Cam 2"}


class TestGetCamera:

    def test_buscar_camera_por_id_existente(self, client, line):
        created = client.post("/cameras/", json=_payload(line["id"])).json()
        resp = client.get(f"/cameras/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_buscar_camera_inexistente_retorna_404(self, client):
        resp = client.get("/cameras/99999")
        assert resp.status_code == 404
