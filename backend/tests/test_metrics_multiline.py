"""
tests/test_metrics_multiline.py
-----------------------------------
Sprint 10C.2 — Testes das métricas Prometheus por linha (label line_id/line_code).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SQLITE_URL = "sqlite:///./test_metrics_multiline.db"
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
    from app.database.session import Base
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    from app.database.session import get_db
    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestMetricasPorLinha:

    def test_metrics_contem_serie_por_linha(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "inspection_ai_line_worker_running" in resp.text
        assert "inspection_ai_line_inspection_fps" in resp.text

    def test_metrics_globais_continuam_presentes(self, client):
        """Métricas sem label continuam existindo — retrocompatibilidade."""
        resp = client.get("/metrics")
        assert "inspection_ai_inspection_fps" in resp.text
        assert "inspection_ai_websocket_connections_active" in resp.text

    def test_metrics_por_linha_tem_label_line_code(self, client):
        from app.core.line_registry import line_registry
        default_ctx = line_registry.default()
        assert default_ctx is not None

        resp = client.get("/metrics")
        assert f'line_code="{default_ctx.code}"' in resp.text
