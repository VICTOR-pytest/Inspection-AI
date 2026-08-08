"""
tests/test_worker_supervisor.py
----------------------------------
Sprint 10C.2 (PR-001) — Testes do WorkerSupervisor.

Usa MagicMock para VisionWorker/EventBus — foca na lógica de orquestração
(start/stop/restart/health/shutdown), não no comportamento real de
captura de frames (isso é testado em test_vision_worker_multiline.py).
"""
from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.line_registry import LineContext, LineRegistry
from app.core.worker_supervisor import WorkerSupervisor


def _mock_worker(running: bool = False) -> MagicMock:
    w = MagicMock()
    w.is_running = running

    def _start():
        w.is_running = True

    def _stop():
        w.is_running = False

    w.start.side_effect = _start
    w.stop.side_effect = _stop
    return w


async def _bus_run_forever() -> None:
    """Simula EventBus.run() rodando indefinidamente até ser cancelado."""
    await asyncio.Event().wait()


def _mock_bus() -> MagicMock:
    bus = MagicMock()
    bus.client_count = 0
    bus.run = MagicMock(side_effect=_bus_run_forever)
    bus.stop = AsyncMock()
    return bus


@pytest.fixture()
def registry():
    return LineRegistry()


@pytest.fixture()
def event_loop_for_supervisor():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
class TestStartLine:

    async def test_start_line_inicia_worker_parado(self, registry):
        loop = asyncio.get_running_loop()
        worker = _mock_worker(running=False)
        bus = _mock_bus()
        registry.register(LineContext(line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus))
        sup = WorkerSupervisor(registry, loop)

        ok = sup.start_line(1)
        assert ok is True
        worker.start.assert_called_once()

    async def test_start_line_idempotente_se_ja_rodando(self, registry):
        loop = asyncio.get_running_loop()
        worker = _mock_worker(running=True)
        bus = _mock_bus()
        registry.register(LineContext(line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus))
        sup = WorkerSupervisor(registry, loop)

        sup.start_line(1)
        worker.start.assert_not_called()  # já estava rodando

    async def test_start_line_cria_task_do_bus(self, registry):
        loop = asyncio.get_running_loop()
        worker = _mock_worker()
        bus = _mock_bus()
        registry.register(LineContext(line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus))
        sup = WorkerSupervisor(registry, loop)

        sup.start_line(1)
        await asyncio.sleep(0)  # deixa call_soon_threadsafe processar
        ctx = registry.get(1)
        assert ctx.bus_task is not None
        assert isinstance(ctx.bus_task, asyncio.Task)
        ctx.bus_task.cancel()

    async def test_start_line_linha_inexistente_retorna_false(self, registry):
        loop = asyncio.get_running_loop()
        sup = WorkerSupervisor(registry, loop)
        assert sup.start_line(999) is False

    async def test_start_line_marca_desired_running(self, registry):
        loop = asyncio.get_running_loop()
        worker = _mock_worker()
        bus = _mock_bus()
        registry.register(LineContext(line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus))
        sup = WorkerSupervisor(registry, loop)

        sup.start_line(1)
        assert registry.get(1).desired_running is True

    async def test_start_all_inicia_todas_as_linhas(self, registry):
        loop = asyncio.get_running_loop()
        for i in (1, 2, 3):
            registry.register(LineContext(
                line_id=i, code=f"L{i:02d}", name=f"Linha {i}",
                worker=_mock_worker(), event_bus=_mock_bus(),
            ))
        sup = WorkerSupervisor(registry, loop)
        sup.start_all()
        await asyncio.sleep(0)  # deixa call_soon_threadsafe processar

        for ctx in registry.all():
            ctx.worker.start.assert_called_once()
            ctx.bus_task.cancel()


@pytest.mark.asyncio
class TestStopLine:

    async def test_stop_line_para_o_worker(self, registry):
        loop = asyncio.get_running_loop()
        worker = _mock_worker(running=True)
        bus = _mock_bus()
        registry.register(LineContext(line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus))
        sup = WorkerSupervisor(registry, loop)

        sup.stop_line(1)
        worker.stop.assert_called_once()

    async def test_stop_line_marca_desired_running_false(self, registry):
        loop = asyncio.get_running_loop()
        worker = _mock_worker(running=True)
        bus = _mock_bus()
        registry.register(LineContext(
            line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus,
            desired_running=True,
        ))
        sup = WorkerSupervisor(registry, loop)

        sup.stop_line(1)
        assert registry.get(1).desired_running is False

    async def test_stop_line_inexistente_nao_lanca_excecao(self, registry):
        loop = asyncio.get_running_loop()
        sup = WorkerSupervisor(registry, loop)
        sup.stop_line(999)  # não deve lançar


@pytest.mark.asyncio
class TestRestartLine:

    async def test_restart_line_para_e_inicia_worker(self, registry):
        loop = asyncio.get_running_loop()
        worker = _mock_worker(running=True)
        bus = _mock_bus()
        registry.register(LineContext(line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus))
        sup = WorkerSupervisor(registry, loop)

        sup.restart_line(1)
        worker.stop.assert_called_once()
        worker.start.assert_called_once()

    async def test_restart_line_incrementa_restart_count(self, registry):
        loop = asyncio.get_running_loop()
        worker = _mock_worker()
        bus = _mock_bus()
        registry.register(LineContext(line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus))
        sup = WorkerSupervisor(registry, loop)

        sup.restart_line(1)
        sup.restart_line(1)
        assert registry.get(1).restart_count == 2

    async def test_restart_line_inexistente_retorna_false(self, registry):
        loop = asyncio.get_running_loop()
        sup = WorkerSupervisor(registry, loop)
        assert sup.restart_line(999) is False


class TestHealthSnapshot:

    def test_health_snapshot_reflete_estado_de_cada_linha(self, registry):
        loop = asyncio.new_event_loop()
        try:
            worker1 = _mock_worker(running=True)
            worker2 = _mock_worker(running=False)
            registry.register(LineContext(
                line_id=1, code="L01", name="Linha 01", worker=worker1,
                event_bus=_mock_bus(), is_default=True,
            ))
            registry.register(LineContext(
                line_id=2, code="L02", name="Linha 02", worker=worker2,
                event_bus=_mock_bus(),
            ))
            sup = WorkerSupervisor(registry, loop)

            snap = sup.health_snapshot()
            by_id = {s["line_id"]: s for s in snap}
            assert by_id[1]["running"] is True
            assert by_id[1]["is_default"] is True
            assert by_id[2]["running"] is False
            assert by_id[2]["is_default"] is False
        finally:
            loop.close()

    def test_health_snapshot_vazio_quando_sem_linhas(self, registry):
        loop = asyncio.new_event_loop()
        try:
            sup = WorkerSupervisor(registry, loop)
            assert sup.health_snapshot() == []
        finally:
            loop.close()


@pytest.mark.asyncio
class TestMonitorLoopRestartAutomatico:

    async def test_monitor_reinicia_worker_morto(self, registry):
        """
        Um worker com desired_running=True mas is_running=False (morreu)
        deve ser reiniciado automaticamente pelo monitor loop.
        """
        loop = asyncio.get_running_loop()
        worker = _mock_worker(running=False)
        bus = _mock_bus()
        registry.register(LineContext(
            line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus,
            desired_running=True,  # deveria estar rodando, mas caiu
        ))
        sup = WorkerSupervisor(registry, loop, health_interval=0.05)

        task = sup.start_monitor()
        await asyncio.sleep(0.2)  # dá tempo para pelo menos 1 ciclo
        sup._shutting_down = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        worker.start.assert_called()  # foi reiniciado
        assert registry.get(1).restart_count >= 1

    async def test_monitor_nao_mexe_em_worker_saudavel(self, registry):
        loop = asyncio.get_running_loop()
        worker = _mock_worker(running=True)
        bus = _mock_bus()
        registry.register(LineContext(
            line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus,
            desired_running=True,
        ))
        sup = WorkerSupervisor(registry, loop, health_interval=0.05)

        task = sup.start_monitor()
        await asyncio.sleep(0.2)
        sup._shutting_down = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert registry.get(1).restart_count == 0

    async def test_monitor_ignora_worker_parado_intencionalmente(self, registry):
        """desired_running=False (parado via stop_line) não deve ser reiniciado."""
        loop = asyncio.get_running_loop()
        worker = _mock_worker(running=False)
        bus = _mock_bus()
        registry.register(LineContext(
            line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus,
            desired_running=False,
        ))
        sup = WorkerSupervisor(registry, loop, health_interval=0.05)

        task = sup.start_monitor()
        await asyncio.sleep(0.2)
        sup._shutting_down = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert registry.get(1).restart_count == 0


@pytest.mark.asyncio
class TestShutdown:

    async def test_shutdown_para_todos_os_workers(self, registry):
        loop = asyncio.get_running_loop()
        for i in (1, 2):
            registry.register(LineContext(
                line_id=i, code=f"L{i:02d}", name=f"Linha {i}",
                worker=_mock_worker(running=True), event_bus=_mock_bus(),
            ))
        sup = WorkerSupervisor(registry, loop)
        sup.start_all()

        await sup.shutdown()

        for ctx in registry.all():
            ctx.worker.stop.assert_called_once()

    async def test_shutdown_cancela_bus_tasks(self, registry):
        loop = asyncio.get_running_loop()
        registry.register(LineContext(
            line_id=1, code="L01", name="Linha 01",
            worker=_mock_worker(), event_bus=_mock_bus(),
        ))
        sup = WorkerSupervisor(registry, loop)
        sup.start_line(1)
        await asyncio.sleep(0)  # deixa call_soon_threadsafe processar
        bus_task = registry.get(1).bus_task

        await sup.shutdown()

        assert bus_task.cancelled() or bus_task.done()

    async def test_shutdown_cancela_monitor_task(self, registry):
        loop = asyncio.get_running_loop()
        registry.register(LineContext(
            line_id=1, code="L01", name="Linha 01",
            worker=_mock_worker(), event_bus=_mock_bus(),
        ))
        sup = WorkerSupervisor(registry, loop, health_interval=60.0)
        sup.start_monitor()

        await sup.shutdown()

        assert sup._monitor_task is None

    async def test_shutdown_e_paralelo_nao_serial(self, registry):
        """
        2 workers cujo stop() simula I/O bloqueante (0.3s cada, via
        threading.Event.wait) — se o shutdown fosse serial levaria >= 0.6s;
        paralelo (asyncio.to_thread) deve levar bem menos que isso.
        """
        import time

        def _slow_stop():
            threading.Event().wait(timeout=0.3)

        workers = []
        for i in (1, 2):
            w = _mock_worker(running=True)
            w.stop.side_effect = _slow_stop
            workers.append(w)
            registry.register(LineContext(
                line_id=i, code=f"L{i:02d}", name=f"Linha {i}",
                worker=w, event_bus=_mock_bus(),
            ))

        loop = asyncio.get_running_loop()
        sup = WorkerSupervisor(registry, loop)

        t0 = time.perf_counter()
        await sup.shutdown()
        elapsed = time.perf_counter() - t0

        assert elapsed < 0.55, f"shutdown levou {elapsed:.2f}s — parece serial, não paralelo"

    async def test_shutdown_e_idempotente_sem_excecao(self, registry):
        loop = asyncio.get_running_loop()
        registry.register(LineContext(
            line_id=1, code="L01", name="Linha 01",
            worker=_mock_worker(), event_bus=_mock_bus(),
        ))
        sup = WorkerSupervisor(registry, loop)
        sup.start_all()
        await sup.shutdown()
        await sup.shutdown()  # segunda chamada não deve lançar
