"""
tests/test_vision_worker_multiline.py
----------------------------------------
Sprint 10C.2 (PR-003) — Testes do VisionWorker com contexto de linha.

Segue o padrão real (não __new__) já usado em test_camera_mode.py:
SimulatedSource + MagicMock de EventBus + event loop isolado.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from vision.source import SimulatedSource
from vision.worker import VisionWorker


@pytest.fixture()
def loop():
    """
    Event loop rodando em thread de background — necessário para que
    call_soon_threadsafe() (usado por VisionWorker para publicar eventos)
    seja de fato processado. Um loop parado (never run_forever'd) nunca
    executa suas callbacks agendadas.
    """
    import threading as _threading

    lp = asyncio.new_event_loop()
    t = _threading.Thread(target=lp.run_forever, daemon=True)
    t.start()
    yield lp
    lp.call_soon_threadsafe(lp.stop)
    t.join(timeout=2.0)
    lp.close()


@pytest.fixture()
def bus():
    b = MagicMock()
    b.put_nowait = MagicMock()
    return b


def _wait_for_events(bus_mock: MagicMock, min_count: int = 1, timeout: float = 2.0) -> list:
    """Poll simples até o worker publicar pelo menos `min_count` eventos."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if bus_mock.put_nowait.call_count >= min_count:
            break
        time.sleep(0.02)
    return [call.args[0] for call in bus_mock.put_nowait.call_args_list]


class TestConstrutorCompativel:
    """Assinatura pré-10C.2 preservada — testes/callers antigos não quebram."""

    def test_worker_sem_line_id_funciona_como_antes(self, loop, bus):
        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(source=source, event_bus=bus, loop=loop)
        assert worker.line_id is None
        assert worker.camera_id is None
        worker.start()
        assert worker.is_running
        worker.stop()

    def test_worker_posicional_sem_line_id_funciona(self, loop, bus):
        """VisionWorker(source, event_bus, loop) — chamada 100% posicional antiga."""
        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(source, bus, loop)
        assert worker.line_id is None
        worker.start()
        worker.stop()


class TestContextoDeLinha:

    def test_worker_com_line_id_propaga_para_eventos(self, loop, bus):
        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(source=source, event_bus=bus, loop=loop, line_id=7, camera_id=3)
        assert worker.line_id == 7
        assert worker.camera_id == 3

        worker.start()
        events = _wait_for_events(bus, min_count=1)
        worker.stop()

        assert len(events) > 0
        assert events[0]["line_id"] == 7
        assert events[0]["camera_id"] == 3

    def test_worker_sem_line_id_evento_tem_campos_none(self, loop, bus):
        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(source=source, event_bus=bus, loop=loop)
        worker.start()
        events = _wait_for_events(bus, min_count=1)
        worker.stop()

        assert len(events) > 0
        assert events[0]["line_id"] is None
        assert events[0]["camera_id"] is None

    def test_worker_camera_id_sem_line_id_ainda_funciona(self, loop, bus):
        """camera_id pode, em tese, ser passado sem line_id — não deve quebrar."""
        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(source=source, event_bus=bus, loop=loop, camera_id=5)
        worker.start()
        events = _wait_for_events(bus, min_count=1)
        worker.stop()

        assert events[0]["line_id"] is None
        assert events[0]["camera_id"] == 5


class TestIsolamentoEntreDuasLinhas:
    """
    PR-003: 'Não compartilhar estado entre linhas'. Dois VisionWorkers
    rodando simultaneamente, cada um com seu próprio line_id/bus, não
    devem interferir um no outro.
    """

    def test_dois_workers_simultaneos_nao_vazam_line_id(self, loop):
        bus_a = MagicMock()
        bus_a.put_nowait = MagicMock()
        bus_b = MagicMock()
        bus_b.put_nowait = MagicMock()

        worker_a = VisionWorker(
            source=SimulatedSource(fps=50.0), event_bus=bus_a, loop=loop, line_id=1, camera_id=10,
        )
        worker_b = VisionWorker(
            source=SimulatedSource(fps=50.0), event_bus=bus_b, loop=loop, line_id=2, camera_id=20,
        )

        worker_a.start()
        worker_b.start()
        try:
            events_a = _wait_for_events(bus_a, min_count=1)
            events_b = _wait_for_events(bus_b, min_count=1)
        finally:
            worker_a.stop()
            worker_b.stop()

        assert all(e["line_id"] == 1 for e in events_a)
        assert all(e["camera_id"] == 10 for e in events_a)
        assert all(e["line_id"] == 2 for e in events_b)
        assert all(e["camera_id"] == 20 for e in events_b)

    def test_eventos_de_uma_linha_nunca_aparecem_no_bus_da_outra(self, loop):
        """Cada bus é um mock distinto — nenhum evento cruza para o mock errado."""
        bus_a = MagicMock()
        bus_a.put_nowait = MagicMock()
        bus_b = MagicMock()
        bus_b.put_nowait = MagicMock()

        worker_a = VisionWorker(source=SimulatedSource(fps=50.0), event_bus=bus_a, loop=loop, line_id=1)
        worker_b = VisionWorker(source=SimulatedSource(fps=50.0), event_bus=bus_b, loop=loop, line_id=2)

        worker_a.start()
        worker_b.start()
        try:
            _wait_for_events(bus_a, min_count=1)
            _wait_for_events(bus_b, min_count=1)
        finally:
            worker_a.stop()
            worker_b.stop()

        # bus_a nunca deve ter recebido um evento com line_id=2, e vice-versa
        for call in bus_a.put_nowait.call_args_list:
            assert call.args[0]["line_id"] != 2
        for call in bus_b.put_nowait.call_args_list:
            assert call.args[0]["line_id"] != 1
