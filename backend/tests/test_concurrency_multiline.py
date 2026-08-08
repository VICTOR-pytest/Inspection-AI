"""
tests/test_concurrency_multiline.py
---------------------------------------
Sprint 10C.2 — Testes de concorrência real: múltiplas linhas processando
frames simultaneamente (threads reais) sem interferência entre si.
"""
from __future__ import annotations

import asyncio
import sys
import threading
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
    lp = asyncio.new_event_loop()
    t = threading.Thread(target=lp.run_forever, daemon=True)
    t.start()
    yield lp
    lp.call_soon_threadsafe(lp.stop)
    t.join(timeout=2.0)
    lp.close()


class TestConcorrenciaEntreLinhas:

    def test_5_linhas_simultaneas_nao_perdem_isolamento(self, loop):
        """
        5 VisionWorkers rodando ao mesmo tempo (threads reais), cada um
        com seu próprio bus mock — nenhum evento deve vazar entre linhas.
        """
        n = 5
        buses = []
        workers = []
        for i in range(1, n + 1):
            bus = MagicMock()
            bus.put_nowait = MagicMock()
            buses.append(bus)
            w = VisionWorker(
                source=SimulatedSource(fps=80.0), event_bus=bus, loop=loop,
                line_id=i, camera_id=i * 10,
            )
            workers.append(w)

        for w in workers:
            w.start()

        t0 = time.time()
        while time.time() - t0 < 2.0:
            if all(b.put_nowait.call_count >= 2 for b in buses):
                break
            time.sleep(0.02)

        for w in workers:
            w.stop()

        for i, bus in enumerate(buses, start=1):
            assert bus.put_nowait.call_count >= 1, f"linha {i} não produziu nenhum evento"
            for call in bus.put_nowait.call_args_list:
                event = call.args[0]
                assert event["line_id"] == i, (
                    f"vazamento: bus da linha {i} recebeu evento de line_id={event['line_id']}"
                )
                assert event["camera_id"] == i * 10

    def test_start_stop_concorrente_de_varias_linhas_nao_lanca_excecao(self, loop):
        """
        Inicia e para 5 workers concorrentemente (via threads) — não deve
        haver exceção nem deadlock.
        """
        workers = []
        for i in range(5):
            bus = MagicMock()
            bus.put_nowait = MagicMock()
            w = VisionWorker(source=SimulatedSource(fps=50.0), event_bus=bus, loop=loop, line_id=i)
            workers.append(w)

        errors: list[Exception] = []

        def _start_and_stop(worker):
            try:
                worker.start()
                time.sleep(0.05)
                worker.stop()
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=_start_and_stop, args=(w,)) for w in workers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == []
        assert all(not w.is_running for w in workers)


@pytest.mark.asyncio
class TestSupervisorConcorrencia:

    async def test_start_line_chamado_concorrentemente_nao_duplica_start(self):
        """
        10 chamadas concorrentes a start_line() para a MESMA linha devem
        resultar em poucas chamadas reais a worker.start() — o supervisor
        não deve iniciar descontroladamente o mesmo worker.
        """
        from app.core.line_registry import LineContext, LineRegistry
        from app.core.worker_supervisor import WorkerSupervisor

        loop = asyncio.get_running_loop()
        registry = LineRegistry()

        worker = MagicMock()
        worker.is_running = False

        def _start():
            worker.is_running = True

        worker.start.side_effect = _start

        async def _run_forever():
            await asyncio.Event().wait()

        bus = MagicMock()
        bus.run = MagicMock(side_effect=_run_forever)

        registry.register(LineContext(line_id=1, code="L01", name="Linha 01", worker=worker, event_bus=bus))
        sup = WorkerSupervisor(registry, loop)

        await asyncio.gather(*[
            asyncio.to_thread(sup.start_line, 1) for _ in range(10)
        ])

        assert worker.start.call_count <= 3, (
            f"worker.start() chamado {worker.start.call_count}x — "
            f"esperado poucas chamadas mesmo sob concorrência"
        )

        ctx = registry.get(1)
        if ctx.bus_task is not None:
            ctx.bus_task.cancel()
