from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Inspection AI"
    assert data["status"] == "running"


def test_health():
    """
    Sprint 9B.4 — Health check retorna status rico com verificações reais.
    Aceita 200 (healthy/degraded) ou 503 (unhealthy se banco offline nos testes).
    """
    response = client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded", "unhealthy")
    assert "checks" in data
    assert "timestamp" in data
    assert "version" in data


def test_health_tem_checks_esperados():
    """Health check deve incluir verificações de todas as dependências."""
    response = client.get("/health")
    checks = response.json().get("checks", {})
    for check_name in ["database", "vision_worker", "event_bus", "storage", "yolo"]:
        assert check_name in checks, f"Check '{check_name}' ausente no health response"
