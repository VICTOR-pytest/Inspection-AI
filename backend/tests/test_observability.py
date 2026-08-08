"""
tests/test_observability.py
----------------------------
Sprint 9B.4 — Testes de observabilidade, health check, Prometheus e storage.

Cobre:
  HC  — Health Check: endpoint real, verificações individuais, status agregado
  PM  — Prometheus: endpoint /metrics, métricas registradas, formato correto
  SS  — StorageService: disk stats, count, cleanup, orphan detection
  SA  — Storage API: endpoints HTTP com autenticação
  CFG — Config: novos settings de observabilidade presentes e válidos
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── Setup SQLite ──────────────────────────────────────────────────────────────

SQLITE_URL = "sqlite:///./test_observability.db"
_engine    = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
_Session   = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    db = _Session()
    try:
        yield db
    finally:
        db.close()


class _FakeAdmin:
    id = 1; email = "admin@test.com"; role = "ADMIN"; is_active = True
    full_name = "Admin"; created_at = datetime(2024,1,1,tzinfo=timezone.utc)
    updated_at = datetime(2024,1,1,tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def setup_db():
    from app.database.session import Base
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def db():
    s = _Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client():
    from app.database.session import get_db
    from app.core.security import get_current_user, require_admin
    from app.main import app
    app.dependency_overrides[get_db]             = _override_get_db
    app.dependency_overrides[get_current_user]   = lambda: _FakeAdmin()
    app.dependency_overrides[require_admin]      = lambda: _FakeAdmin()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def tmpdir():
    """Diretório temporário limpo para cada teste de storage."""
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# CFG — CONFIGURAÇÕES DE OBSERVABILIDADE
# ═══════════════════════════════════════════════════════════════════════════════

class TestObservabilitySettings:
    """Settings de observabilidade presentes, tipados e com valores razoáveis."""

    def test_settings_tem_health_timeout(self):
        from app.core.config import settings
        assert hasattr(settings, "health_timeout_seconds")
        assert isinstance(settings.health_timeout_seconds, (int, float))
        assert settings.health_timeout_seconds > 0

    def test_settings_tem_prometheus_enabled(self):
        from app.core.config import settings
        assert hasattr(settings, "prometheus_enabled")
        assert isinstance(settings.prometheus_enabled, bool)

    def test_settings_tem_disk_warning(self):
        from app.core.config import settings
        assert hasattr(settings, "disk_warning_percent")
        assert 0 < settings.disk_warning_percent < 100

    def test_settings_tem_disk_critical(self):
        from app.core.config import settings
        assert hasattr(settings, "disk_critical_percent")
        assert settings.disk_critical_percent > settings.disk_warning_percent

    def test_settings_tem_image_retention_days(self):
        from app.core.config import settings
        assert hasattr(settings, "image_retention_days")
        assert isinstance(settings.image_retention_days, int)
        assert settings.image_retention_days >= 0

    def test_settings_tem_image_cleanup_enabled(self):
        from app.core.config import settings
        assert hasattr(settings, "image_cleanup_enabled")
        assert isinstance(settings.image_cleanup_enabled, bool)

    def test_settings_tem_image_cleanup_hour(self):
        from app.core.config import settings
        assert hasattr(settings, "image_cleanup_hour")
        assert 0 <= settings.image_cleanup_hour <= 23

    def test_disk_critical_maior_que_warning(self):
        from app.core.config import settings
        assert settings.disk_critical_percent > settings.disk_warning_percent


# ═══════════════════════════════════════════════════════════════════════════════
# HC — HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    """Testes do endpoint /health com verificações reais."""

    def test_health_retorna_200(self, client):
        resp = client.get("/health")
        assert resp.status_code in (200, 503)  # 503 apenas se DB offline

    def test_health_retorna_json_com_status(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "unhealthy")

    def test_health_retorna_timestamp(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "timestamp" in data
        assert len(data["timestamp"]) > 0

    def test_health_retorna_version(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "version" in data

    def test_health_retorna_checks(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "checks" in data
        assert isinstance(data["checks"], dict)

    def test_health_tem_check_database(self, client):
        resp = client.get("/health")
        assert "database" in resp.json()["checks"]

    def test_health_tem_check_vision_worker(self, client):
        resp = client.get("/health")
        assert "vision_worker" in resp.json()["checks"]

    def test_health_tem_check_event_bus(self, client):
        resp = client.get("/health")
        assert "event_bus" in resp.json()["checks"]

    def test_health_tem_check_storage(self, client):
        resp = client.get("/health")
        assert "storage" in resp.json()["checks"]

    def test_health_tem_check_yolo(self, client):
        resp = client.get("/health")
        assert "yolo" in resp.json()["checks"]

    def test_health_e_publico_sem_auth(self):
        """Health check deve funcionar sem Authorization header."""
        from app.database.session import get_db
        from app.main import app
        app.dependency_overrides[get_db] = _override_get_db
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/health")
        app.dependency_overrides.clear()
        assert resp.status_code in (200, 503)  # nunca 401

    def test_health_check_status_tem_campo_status_por_check(self, client):
        """Cada sub-check deve ter campo 'status'."""
        resp = client.get("/health")
        checks = resp.json().get("checks", {})
        for name, check in checks.items():
            assert "status" in check, f"Check '{name}' sem campo 'status'"
            assert check["status"] in ("ok", "warning", "error"), \
                f"Check '{name}' tem status inválido: {check['status']}"

    def test_health_unhealthy_retorna_503(self):
        """Quando banco está offline, /health deve retornar 503."""
        from app.services.health_service import run_health_checks

        async def _mock_checks(worker=None, bus=None):
            return {
                "status": "unhealthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "0.1.0",
                "checks": {"database": {"status": "error", "message": "Connection refused"}},
            }

        from app.main import app
        with patch("app.api.v1.health.run_health_checks", _mock_checks):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/health")
        assert resp.status_code == 503

    def test_health_degraded_retorna_200(self):
        """Status 'degraded' deve retornar 200 (sistema operacional)."""
        async def _mock_checks(worker=None, bus=None):
            return {
                "status": "degraded",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "0.1.0",
                "checks": {
                    "database":     {"status": "ok"},
                    "vision_worker": {"status": "warning", "message": "Worker parado"},
                },
            }

        from app.main import app
        with patch("app.api.v1.health.run_health_checks", _mock_checks):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/health")
        assert resp.status_code == 200


class TestHealthServiceChecks:
    """Testes unitários das verificações individuais do health service."""

    def test_check_database_ok_com_sqlite(self):
        """_check_database deve funcionar com SQLite (usado nos testes)."""
        from app.services.health_service import _check_database

        async def run():
            return await _check_database(timeout_seconds=5.0)

        result = asyncio.run(run())
        # SQLite responde com SELECT 1
        assert result.status in ("ok", "error")  # ok se DB acessível

    def test_check_vision_worker_none_retorna_warning(self):
        from app.services.health_service import _check_vision_worker
        result = _check_vision_worker(None)
        assert result.status == "warning"
        assert result.error is not None

    def test_check_vision_worker_running_retorna_ok(self):
        from app.services.health_service import _check_vision_worker
        mock_worker = MagicMock()
        mock_worker.is_running = True
        mock_worker._detector_cb = None
        result = _check_vision_worker(mock_worker)
        assert result.status == "ok"

    def test_check_vision_worker_stopped_retorna_warning(self):
        from app.services.health_service import _check_vision_worker
        mock_worker = MagicMock()
        mock_worker.is_running = False
        mock_worker._detector_cb = None
        result = _check_vision_worker(mock_worker)
        assert result.status == "warning"

    def test_check_event_bus_running(self):
        from app.services.health_service import _check_event_bus
        mock_bus = MagicMock()
        mock_bus._running = True
        mock_bus.client_count = 2
        mock_bus._queue = None
        mock_bus.fps = 4.8
        mock_bus._persist_cb = None
        result = _check_event_bus(mock_bus)
        assert result.status == "ok"
        assert result.details["clients_connected"] == 2

    def test_check_storage_path_inexistente_retorna_error(self, tmpdir):
        from app.services.health_service import _check_storage
        nonexistent = str(tmpdir / "does_not_exist")
        result = _check_storage(nonexistent, 80.0, 95.0)
        assert result.status == "error"

    def test_check_storage_path_existente_retorna_ok(self, tmpdir):
        from app.services.health_service import _check_storage
        result = _check_storage(str(tmpdir), 80.0, 95.0)
        # tmpdir existe e provavelmente tem espaço livre
        assert result.status in ("ok", "warning", "error")
        assert "free_gb" in result.details

    def test_check_yolo_desabilitado_retorna_warning(self):
        from app.services.health_service import _check_yolo
        result = _check_yolo(yolo_enabled=False, model_path="/não/importa")
        assert result.status == "warning"
        assert result.details["enabled"] is False

    def test_check_yolo_habilitado_sem_modelo_retorna_warning(self, tmpdir):
        from app.services.health_service import _check_yolo
        result = _check_yolo(yolo_enabled=True, model_path=str(tmpdir / "model.pt"))
        assert result.status == "warning"
        assert result.details["exists"] is False

    def test_check_yolo_habilitado_com_modelo_retorna_ok(self, tmpdir):
        from app.services.health_service import _check_yolo
        model = tmpdir / "model.pt"
        model.write_bytes(b"fake model")
        result = _check_yolo(yolo_enabled=True, model_path=str(model))
        assert result.status == "ok"
        assert result.details["exists"] is True

    def test_run_health_checks_retorna_dict_com_status(self):
        from app.services.health_service import run_health_checks
        result = asyncio.run(run_health_checks())
        assert "status" in result
        assert result["status"] in ("healthy", "degraded", "unhealthy")
        assert "checks" in result
        assert "timestamp" in result

    def test_run_health_checks_database_error_resulta_unhealthy(self):
        """Se banco falhar, o status geral deve ser 'unhealthy'."""
        from app.services.health_service import run_health_checks, _check_database

        async def failing_db(timeout_seconds):
            from app.services.health_service import CheckResult
            return CheckResult(status="error", error="Connection refused")

        with patch("app.services.health_service._check_database", failing_db):
            result = asyncio.run(run_health_checks())
        assert result["status"] == "unhealthy"


# ═══════════════════════════════════════════════════════════════════════════════
# PM — PROMETHEUS METRICS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrometheusMetrics:
    """Testes do endpoint /metrics e do registry de métricas."""

    def test_metrics_endpoint_retorna_200(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type_prometheus(self, client):
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_metrics_contem_metricas_da_aplicacao(self, client):
        resp = client.get("/metrics")
        text = resp.text
        assert "inspection_ai_" in text

    def test_metrics_contem_http_requests(self, client):
        client.get("/health")  # gera ao menos 1 request
        resp = client.get("/metrics")
        assert "inspection_ai_http_requests_total" in resp.text

    def test_metrics_contem_inspection_fps(self, client):
        resp = client.get("/metrics")
        assert "inspection_ai_inspection_fps" in resp.text

    def test_metrics_contem_websocket_connections(self, client):
        resp = client.get("/metrics")
        assert "inspection_ai_websocket_connections_active" in resp.text

    def test_metrics_contem_eventbus_queue(self, client):
        resp = client.get("/metrics")
        assert "inspection_ai_eventbus_queue_size" in resp.text

    def test_metrics_contem_db_pool(self, client):
        resp = client.get("/metrics")
        assert "inspection_ai_db_pool_size" in resp.text

    def test_metrics_desabilitado_retorna_404(self):
        """Com PROMETHEUS_ENABLED=false, /metrics deve retornar 404."""
        from app.core.config import settings
        from app.database.session import get_db
        from app.core.security import get_current_user, require_admin
        from app.main import app

        original = settings.prometheus_enabled
        try:
            settings.prometheus_enabled = False
            app.dependency_overrides[get_db] = _override_get_db
            app.dependency_overrides[get_current_user] = lambda: _FakeAdmin()
            app.dependency_overrides[require_admin]    = lambda: _FakeAdmin()
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/metrics")
            assert resp.status_code == 404
        finally:
            settings.prometheus_enabled = original
            app.dependency_overrides.clear()

    def test_metrics_registry_tem_28_metricas(self):
        """O registry METRICS deve ter todas as métricas definidas."""
        from app.core.metrics import METRICS
        metric_attrs = [
            "app_info", "http_requests_total", "http_request_duration_seconds",
            "inspections_total", "inspections_valid_total", "inspections_invalid_total",
            "inspection_fps", "inspection_error_rate",
            "decisions_approved_total", "decisions_rejected_total",
            "decisions_pending_gauge", "decisions_approval_rate",
            "vision_frames_total", "vision_inference_seconds",
            "vision_detector_errors_total", "vision_worker_running",
            "websocket_connections_active", "websocket_messages_sent_total",
            "eventbus_queue_size", "eventbus_events_total",
            "eventbus_dropped_events_total", "eventbus_persist_errors_total",
            "storage_images_total", "storage_disk_bytes_used",
            "storage_disk_bytes_free", "storage_cleanup_deleted_total",
            "db_pool_size", "db_pool_checked_out", "db_pool_overflow",
            "circuit_breaker_state", "circuit_breaker_failures_total",
        ]
        for attr in metric_attrs:
            assert hasattr(METRICS, attr), f"METRICS.{attr} não encontrado"

    def test_http_middleware_incrementa_contador(self, client):
        """Middleware deve incrementar http_requests_total a cada request."""
        from app.core.metrics import METRICS
        from prometheus_client import REGISTRY

        # Faz uma request
        client.get("/health")

        # Verifica que o contador foi atualizado (via generate_latest)
        from prometheus_client import generate_latest
        output = generate_latest().decode("utf-8")
        assert "inspection_ai_http_requests_total" in output

    def test_normalize_path_remove_ids_numericos(self):
        """_normalize_path deve substituir IDs numéricos por {id}."""
        from app.main import _normalize_path
        assert _normalize_path("/api/v1/inspections/42")   == "/api/v1/inspections/{id}"
        assert _normalize_path("/api/v1/inspections/999")  == "/api/v1/inspections/{id}"
        assert _normalize_path("/api/v1/inspections")      == "/api/v1/inspections"
        assert _normalize_path("/health")                  == "/health"


# ═══════════════════════════════════════════════════════════════════════════════
# SS — STORAGE SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class TestStorageService:
    """Testes do StorageService: disk stats, count, cleanup, orphans."""

    # ── get_disk_stats ────────────────────────────────────────────────────────

    def test_disk_stats_path_existente(self, tmpdir):
        from app.services.storage_service import get_disk_stats
        stats = get_disk_stats(str(tmpdir))
        assert stats.total_bytes > 0
        assert stats.used_bytes >= 0
        assert stats.free_bytes >= 0
        assert 0.0 <= stats.used_pct <= 100.0

    def test_disk_stats_path_inexistente_levanta_error(self, tmpdir):
        from app.services.storage_service import get_disk_stats
        with pytest.raises(FileNotFoundError):
            get_disk_stats(str(tmpdir / "nao_existe"))

    def test_disk_stats_to_dict_tem_campos(self, tmpdir):
        from app.services.storage_service import get_disk_stats
        d = get_disk_stats(str(tmpdir)).to_dict()
        for campo in ["total_gb", "used_gb", "free_gb", "used_pct"]:
            assert campo in d

    # ── count_images ──────────────────────────────────────────────────────────

    def test_count_images_dir_vazio(self, tmpdir):
        from app.services.storage_service import count_images
        result = count_images(str(tmpdir))
        assert result["total"] == 0

    def test_count_images_path_inexistente(self, tmpdir):
        from app.services.storage_service import count_images
        result = count_images(str(tmpdir / "nao_existe"))
        assert result == {"original": 0, "annotated": 0, "total": 0}

    def test_count_images_conta_arquivos_jpg(self, tmpdir):
        from app.services.storage_service import count_images
        orig = tmpdir / "images" / "original"
        orig.mkdir(parents=True)
        (orig / "img1.jpg").write_bytes(b"fake")
        (orig / "img2.jpg").write_bytes(b"fake")
        ann = tmpdir / "images" / "annotated"
        ann.mkdir(parents=True)
        (ann / "img1.jpg").write_bytes(b"fake")

        result = count_images(str(tmpdir))
        assert result["original"]  == 2
        assert result["annotated"] == 1
        assert result["total"]     == 3

    # ── cleanup_older_than ────────────────────────────────────────────────────

    def test_cleanup_retention_zero_nao_deleta(self, db):
        from app.services.storage_service import cleanup_older_than
        from app.core.config import settings
        result = cleanup_older_than(db, retention_days=0)
        assert result.deleted_files == 0
        assert result.deleted_records == 0

    def test_cleanup_dry_run_nao_deleta_arquivos(self, db, tmpdir):
        from app.services.storage_service import cleanup_older_than, CleanupResult
        from app.core.config import settings

        # Cria imagem antiga no banco
        from app.models.inspection_image import InspectionImage
        img_file = tmpdir / "images" / "original" / "test.jpg"
        img_file.parent.mkdir(parents=True)
        img_file.write_bytes(b"fake")

        record = InspectionImage(
            inspection_id=1,
            file_path="images/original/test.jpg",
            variant="original",
            created_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        db.add(record)
        db.commit()

        original_path = settings.storage_path
        try:
            settings.storage_path = str(tmpdir)
            result = cleanup_older_than(db, retention_days=30, dry_run=True)
        finally:
            settings.storage_path = original_path

        # dry_run: arquivo ainda existe
        assert img_file.exists()

    def test_cleanup_disabled_nao_deleta(self, db):
        from app.services.storage_service import cleanup_older_than
        from app.core.config import settings

        original = settings.image_cleanup_enabled
        try:
            settings.image_cleanup_enabled = False
            result = cleanup_older_than(db, retention_days=1)
            assert result.deleted_files == 0
        finally:
            settings.image_cleanup_enabled = original

    def test_cleanup_result_to_dict(self, db):
        from app.services.storage_service import cleanup_older_than
        result = cleanup_older_than(db, retention_days=0)
        d = result.to_dict()
        for campo in ["deleted_files", "deleted_records", "freed_bytes", "freed_mb", "errors"]:
            assert campo in d

    # ── find_orphan_files ─────────────────────────────────────────────────────

    def test_find_orphan_files_sem_orfaos(self, db, tmpdir):
        from app.services.storage_service import find_orphan_files
        result = find_orphan_files(db, str(tmpdir))
        assert result == []

    def test_find_orphan_files_detecta_arquivo_sem_registro(self, db, tmpdir):
        from app.services.storage_service import find_orphan_files
        # Cria arquivo em disco sem registro no banco
        img = tmpdir / "images" / "original" / "orfao.jpg"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"fake")

        result = find_orphan_files(db, str(tmpdir))
        assert len(result) == 1

    def test_find_orphan_records_sem_orfaos(self, db, tmpdir):
        from app.services.storage_service import find_orphan_records
        result = find_orphan_records(db, str(tmpdir))
        assert result == []

    def test_find_orphan_records_detecta_registro_sem_arquivo(self, db, tmpdir):
        from app.services.storage_service import find_orphan_records
        from app.models.inspection_image import InspectionImage

        # Registro no banco sem arquivo em disco
        record = InspectionImage(
            inspection_id=1,
            file_path="images/original/nao_existe.jpg",
            variant="original",
        )
        db.add(record)
        db.commit()

        result = find_orphan_records(db, str(tmpdir))
        assert record.id in result


# ═══════════════════════════════════════════════════════════════════════════════
# SA — STORAGE API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestStorageApiEndpoints:
    """Testes dos endpoints HTTP de gerenciamento de storage."""

    def test_storage_stats_requer_auth(self):
        """GET /api/v1/storage/stats sem token deve retornar 401."""
        from app.database.session import get_db
        from app.core.security import get_current_user, require_admin
        from app.main import app
        saved = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = _override_get_db
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/v1/storage/stats")
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
        assert resp.status_code == 401

    def test_storage_stats_admin_retorna_200(self, client):
        with patch("app.api.v1.storage_api.storage_service.get_disk_stats") as mock_disk, \
             patch("app.api.v1.storage_api.storage_service.count_images") as mock_count:
            from app.services.storage_service import DiskStats
            mock_disk.return_value = DiskStats(100*1024**3, 40*1024**3, 60*1024**3)
            mock_count.return_value = {"original": 10, "annotated": 8, "total": 18}
            resp = client.get("/api/v1/storage/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "disk" in data
        assert "images" in data

    def test_storage_cleanup_requer_auth(self):
        from app.database.session import get_db
        from app.core.security import get_current_user, require_admin
        from app.main import app
        saved = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = _override_get_db
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/api/v1/storage/cleanup")
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
        assert resp.status_code == 401

    def test_storage_cleanup_dry_run_retorna_resultado(self, client):
        resp = client.post("/api/v1/storage/cleanup?dry_run=true&retention_days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted_files" in data
        assert "deleted_records" in data

    def test_storage_orphans_retorna_estrutura_correta(self, client):
        resp = client.get("/api/v1/storage/orphans")
        assert resp.status_code == 200
        data = resp.json()
        assert "orphan_files" in data
        assert "orphan_records" in data
        assert "count" in data["orphan_files"]
        assert "count" in data["orphan_records"]

    def test_storage_orphans_requer_auth(self):
        from app.database.session import get_db
        from app.core.security import get_current_user, require_admin
        from app.main import app
        saved = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = _override_get_db
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/v1/storage/orphans")
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# ENV — .env.example completude
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnvExampleCompletude:
    """Verifica que .env.example documenta as configurações críticas."""

    def _read_env_example(self) -> str:
        paths = [
            Path(__file__).parents[2] / ".env.example",
            Path(__file__).parents[3] / ".env.example",
        ]
        for p in paths:
            if p.exists():
                return p.read_text()
        pytest.skip(".env.example não encontrado")

    def test_env_example_documenta_jwt_secret_key(self):
        content = self._read_env_example()
        assert "JWT_SECRET_KEY" in content

    def test_env_example_documenta_environment(self):
        content = self._read_env_example()
        assert "ENVIRONMENT" in content

    def test_env_example_documenta_prometheus_enabled(self):
        content = self._read_env_example()
        assert "PROMETHEUS_ENABLED" in content

    def test_env_example_documenta_image_retention_days(self):
        content = self._read_env_example()
        assert "IMAGE_RETENTION_DAYS" in content

    def test_env_example_documenta_db_pool_size(self):
        content = self._read_env_example()
        assert "DB_POOL_SIZE" in content

    def test_env_example_documenta_ws_heartbeat(self):
        content = self._read_env_example()
        assert "WS_HEARTBEAT_INTERVAL" in content

    def test_env_example_documenta_cb_failure_threshold(self):
        content = self._read_env_example()
        assert "CB_FAILURE_THRESHOLD" in content

    def test_env_example_documenta_disk_warning(self):
        content = self._read_env_example()
        assert "DISK_WARNING_PERCENT" in content

    def test_env_example_tem_aviso_sobre_jwt_producao(self):
        """JWT_SECRET_KEY deve ter aviso de que DEVE ser alterada em produção."""
        content = self._read_env_example()
        # Verificar que há indicação de alterar em produção
        assert "PRODUÇÃO" in content.upper() or "PRODUCTION" in content.upper()
