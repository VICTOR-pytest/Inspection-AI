"""
Testes do hook de persistência automática no EventBus.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.events import EventBus
from app.database.session import Base
from app.models import Inspection, Product  # noqa: F401

SQLITE_URL = "sqlite:///./test_eventbus_persist.db"
engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db(monkeypatch):
    Base.metadata.create_all(bind=engine)

    import app.database.session as session_module
    monkeypatch.setattr(session_module, "SessionLocal", TestingSessionLocal)

    yield
    Base.metadata.drop_all(bind=engine)


@pytest.mark.asyncio
async def test_eventbus_persiste_evento_automaticamente():
    bus = EventBus(maxsize=10)

    event = {
        "type": "inspection", "barcode": "789123456",
        "valid": True, "confidence": 0.91, "weight": 1.02,
        "product_name": "Produto Teste A", "reason": None,
    }
    bus.put_nowait(event)

    task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.3)
    await bus.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    db = TestingSessionLocal()
    try:
        rows = db.query(Inspection).all()
        assert len(rows) == 1
        assert rows[0].barcode == "789123456"
        assert rows[0].confidence == 0.91
    finally:
        db.close()


@pytest.mark.asyncio
async def test_eventbus_atualiza_metricas_internas():
    bus = EventBus(maxsize=10)
    bus.put_nowait({
        "type": "inspection", "barcode": "X", "valid": True,
        "confidence": 0.9, "weight": 1.0, "product_name": None, "reason": None,
    })
    bus.put_nowait({
        "type": "inspection", "barcode": "Y", "valid": False,
        "confidence": 0.5, "weight": 1.0, "product_name": None, "reason": "fail",
    })

    task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.3)
    await bus.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    snapshot = bus.status_snapshot()
    assert snapshot["total"] == 2
    assert snapshot["approved"] == 1
    assert snapshot["rejected"] == 1
    assert snapshot["error_rate"] == 0.5


@pytest.mark.asyncio
async def test_eventbus_nao_persiste_line_status():
    bus = EventBus(maxsize=10)
    bus.put_nowait({"type": "line_status", "status": "online"})

    task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.3)
    await bus.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    db = TestingSessionLocal()
    try:
        assert db.query(Inspection).count() == 0
    finally:
        db.close()
