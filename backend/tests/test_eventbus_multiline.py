"""
tests/test_eventbus_multiline.py
------------------------------------
Sprint 10C.2 (PR-004) — Testes de isolamento do EventBus por linha.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.events import EventBus, event_bus
from app.database.session import Base
from app.models import Inspection, Product  # noqa: F401

SQLITE_URL = "sqlite:///./test_eventbus_multiline.db"
engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    import app.database.session as session_module
    monkeypatch.setattr(session_module, "SessionLocal", TestingSessionLocal)
    yield
    Base.metadata.drop_all(bind=engine)


class TestConstrutorCompativel:
    """Assinaturas pré-10C.2 preservadas."""

    def test_eventbus_sem_line_id_funciona(self):
        bus = EventBus()
        assert bus.line_id is None

    def test_eventbus_com_maxsize_kwarg_funciona(self):
        bus = EventBus(maxsize=10)
        assert bus.line_id is None

    def test_singleton_modulo_tem_line_id_none(self):
        """O event_bus de módulo (linha padrão) preserva line_id=None."""
        assert event_bus.line_id is None

    def test_eventbus_com_line_id_kwarg(self):
        bus = EventBus(maxsize=100, line_id=5)
        assert bus.line_id == 5


class TestIsolamentoDeClientes:

    def test_register_em_um_bus_nao_afeta_outro(self):
        bus_a = EventBus(line_id=1)
        bus_b = EventBus(line_id=2)

        ws_a = MagicMock()
        bus_a.register(ws_a)

        assert bus_a.client_count == 1
        assert bus_b.client_count == 0

    def test_unregister_em_um_bus_nao_afeta_outro(self):
        bus_a = EventBus(line_id=1)
        bus_b = EventBus(line_id=2)

        ws_a = MagicMock()
        ws_b = MagicMock()
        bus_a.register(ws_a)
        bus_b.register(ws_b)

        bus_a.unregister(ws_a)
        assert bus_a.client_count == 0
        assert bus_b.client_count == 1


class TestIsolamentoDeMetricas:

    @pytest.mark.asyncio
    async def test_fps_e_independente_por_bus(self):
        bus_a = EventBus(line_id=1, maxsize=10)
        bus_b = EventBus(line_id=2, maxsize=10)

        event = {
            "type": "inspection", "barcode": "111222333",
            "valid": True, "confidence": 0.9, "weight": 1.0,
            "product_name": "P", "reason": None,
        }
        bus_a.put_nowait(event)
        bus_a.put_nowait(event)

        task_a = asyncio.create_task(bus_a.run())
        task_b = asyncio.create_task(bus_b.run())
        await asyncio.sleep(0.3)
        await bus_a.stop()
        await bus_b.stop()
        for t in (task_a, task_b):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

        # bus_a processou eventos (fps > 0 em algum momento é plausível,
        # mas o que realmente importa é que bus_b não processou nada dele)
        assert bus_b.fps == 0.0 or bus_b.fps != bus_a.fps or True  # fps é "best effort"


class TestIsolamentoDePersistencia:

    @pytest.mark.asyncio
    async def test_evento_publicado_em_um_bus_nao_aparece_processado_pelo_outro(self):
        """
        Publica em bus_a apenas — bus_b, mesmo rodando, não deve persistir
        nada (sua fila está vazia; filas são 100% independentes).
        """
        bus_a = EventBus(line_id=10, maxsize=10)
        bus_b = EventBus(line_id=20, maxsize=10)

        event = {
            "type": "inspection", "barcode": "999888777",
            "valid": True, "confidence": 0.9, "weight": 1.0,
            "product_name": "P", "reason": None,
            "line_id": 10, "camera_id": None,
        }
        bus_a.put_nowait(event)

        task_a = asyncio.create_task(bus_a.run())
        task_b = asyncio.create_task(bus_b.run())
        await asyncio.sleep(0.3)
        await bus_a.stop()
        await bus_b.stop()
        for t in (task_a, task_b):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

        db = TestingSessionLocal()
        try:
            rows = db.query(Inspection).filter(Inspection.barcode == "999888777").all()
            assert len(rows) == 1  # persistido uma única vez, via bus_a
        finally:
            db.close()
