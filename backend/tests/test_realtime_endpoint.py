"""
Testes de integração do endpoint POST /inspection/realtime.
Usa SQLite em memória e mocka o pipeline de visão.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.database.session import Base, get_db
from app.main import app
from app.models import Inspection, Product  # noqa: F401

SQLITE_URL = "sqlite:///./test_realtime.db"
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


def _blank_b64() -> str:
    """Gera imagem branca 100x100 em base64 para testes."""
    frame = np.ones((100, 100, 3), dtype=np.uint8) * 255
    _, buf = cv2.imencode(".jpg", frame)
    return base64.b64encode(buf.tobytes()).decode()


def _blank_frame() -> np.ndarray:
    return np.ones((100, 100, 3), dtype=np.uint8) * 255


# ---------------------------------------------------------------------------
# Cenários
# ---------------------------------------------------------------------------

class TestRealtimeEndpoint:
    def test_barcode_detectado_peso_valido(self, client, produto_a):
        """Pipeline detecta barcode válido e peso OK → approved."""
        # Fix #1: patch as funções individualmente em vez de _get_vision_pipeline,
        # evitando dependência do contrato interno de retorno da função.
        with patch("vision.pipeline.decode_base64_image", return_value=_blank_frame()), \
             patch("vision.pipeline.process_frame", return_value={
                 "barcode": "789123456",
                 "detected": True,
                 "detection_confidence": 0.95,
                 "symbology": "EAN13",
             }):
            resp = client.post("/inspection/realtime", json={
                "image": _blank_b64(),
                "weight": 1.02,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["barcode"] == "789123456"
        assert data["valid"] is True
        assert data["barcode_ok"] is True
        assert data["weight_ok"] is True
        assert data["product_name"] == "Produto Teste A"
        assert data["detected"] is True

    def test_barcode_nao_detectado(self, client):
        """Pipeline não lê barcode → rejected."""
        with patch("vision.pipeline.decode_base64_image", return_value=_blank_frame()), \
             patch("vision.pipeline.process_frame", return_value={
                 "barcode": None,
                 "detected": False,
                 "detection_confidence": 0.0,
                 "symbology": None,
             }):
            resp = client.post("/inspection/realtime", json={
                "image": _blank_b64(),
                "weight": 1.0,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["barcode"] is None
        assert data["valid"] is False
        # A mensagem está em português e não contém "barcode" literalmente
        assert data["reason"] is not None and len(data["reason"]) > 0

    def test_peso_fora_da_tolerancia(self, client, produto_a):
        """Barcode OK mas peso rejeitado."""
        with patch("vision.pipeline.decode_base64_image", return_value=_blank_frame()), \
             patch("vision.pipeline.process_frame", return_value={
                 "barcode": "789123456",
                 "detected": True,
                 "detection_confidence": 0.90,
                 "symbology": "EAN13",
             }):
            resp = client.post("/inspection/realtime", json={
                "image": _blank_b64(),
                "weight": 0.50,  # muito abaixo de 1.0 ± 5%
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["barcode_ok"] is True
        assert data["weight_ok"] is False
        assert data["valid"] is False

    def test_imagem_invalida_retorna_422(self, client):
        """Base64 inválido deve retornar 422."""
        resp = client.post("/inspection/realtime", json={
            "image": "ISSO_NAO_E_BASE64_VALIDO!!!",
            "weight": 1.0,
        })
        assert resp.status_code == 422

    def test_inspecao_realtime_persistida(self, client, produto_a):
        """Garante que a inspeção é salva no banco."""
        with patch("vision.pipeline.decode_base64_image", return_value=_blank_frame()), \
             patch("vision.pipeline.process_frame", return_value={
                 "barcode": "789123456",
                 "detected": True,
                 "detection_confidence": 0.88,
                 "symbology": "CODE128",
             }):
            client.post("/inspection/realtime", json={
                "image": _blank_b64(),
                "weight": 1.0,
            })

        resp = client.get("/inspection/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
