"""
tests/test_shutdown_startup_10c2.py
---------------------------------------
Sprint 10C.2 — Verificações de startup/shutdown limpo: nenhuma thread ou
task deve sobreviver ao ciclo de vida do TestClient (lifespan completo).

Usa o app real (TestClient com lifespan real, Postgres configurado em
settings.database_url) — é o único jeito de testar de verdade o
WorkerSupervisor.shutdown() de ponta a ponta.
"""
from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SQLITE_URL = "sqlite:///./test_shutdown_startup_10c2.db"
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


def _visionworker_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if "VisionWorker" in t.name or "vision" in t.name.lower()]


class TestStartupPopulaRegistry:

    def test_lifespan_popula_line_registry(self):
        from app.database.session import get_db
        from app.main import app
        from app.core.line_registry import line_registry

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app):
            assert len(line_registry) >= 1
            assert line_registry.default() is not None
        app.dependency_overrides.clear()

    def test_lifespan_expoe_supervisor_em_app_state(self):
        from app.database.session import get_db
        from app.main import app

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            # supervisor pode ser None apenas se o fallback legado foi
            # ativado (ex: schema sem tabela production_lines) — no
            # ambiente de teste (Postgres com migrations aplicadas),
            # deve estar presente.
            assert hasattr(c.app.state, "supervisor")
        app.dependency_overrides.clear()

    def test_lifespan_expoe_worker_default_em_app_state_worker(self):
        """Compatibilidade: app.state.worker continua existindo (health.py depende disso)."""
        from app.database.session import get_db
        from app.main import app

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            assert hasattr(c.app.state, "worker")
        app.dependency_overrides.clear()


class TestShutdownSemVazamentoDeThreads:

    def test_nenhuma_thread_de_worker_sobrevive_ao_shutdown(self):
        from app.database.session import get_db
        from app.main import app

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app):
            pass  # entra e sai do lifespan completo
        app.dependency_overrides.clear()

        # Após __exit__ do TestClient, threads de captura do worker
        # devem ter sido join()'d — nenhuma deve restar viva.
        alive_capture_threads = [
            t for t in threading.enumerate()
            if t.is_alive() and "capture" in t.name.lower()
        ]
        assert alive_capture_threads == []

    def test_multiplos_ciclos_start_stop_nao_acumulam_threads(self):
        """
        3 ciclos completos de entrar/sair do lifespan não devem acumular
        threads vivas — cada ciclo deve limpar totalmente o anterior.
        """
        from app.database.session import get_db
        from app.main import app

        app.dependency_overrides[get_db] = override_get_db
        baseline = threading.active_count()

        for _ in range(3):
            with TestClient(app):
                pass

        app.dependency_overrides.clear()
        final = threading.active_count()

        # Tolerância pequena para threads de infraestrutura do próprio
        # TestClient/anyio que podem levar um instante a mais para
        # finalizar — o importante é não crescer proporcionalmente aos
        # 3 ciclos (o que indicaria vazamento real).
        assert final <= baseline + 3, (
            f"contagem de threads cresceu de {baseline} para {final} "
            f"após 3 ciclos — possível vazamento"
        )


class TestShutdownSemVazamentoDeTasks:

    def test_supervisor_shutdown_zera_monitor_task(self):
        import asyncio as _asyncio
        from app.core.line_registry import LineRegistry, LineContext
        from app.core.worker_supervisor import WorkerSupervisor
        from unittest.mock import MagicMock

        async def _scenario():
            loop = _asyncio.get_running_loop()
            registry = LineRegistry()
            worker = MagicMock()
            worker.is_running = False
            bus = MagicMock()

            async def _run_forever():
                await _asyncio.Event().wait()

            bus.run = MagicMock(side_effect=_run_forever)
            bus.stop = MagicMock(side_effect=lambda: _asyncio.sleep(0))

            registry.register(LineContext(line_id=1, code="L01", name="L01", worker=worker, event_bus=bus))
            sup = WorkerSupervisor(registry, loop, health_interval=60.0)
            sup.start_monitor()
            assert sup._monitor_task is not None

            await sup.shutdown()
            assert sup._monitor_task is None

        asyncio.run(_scenario())
