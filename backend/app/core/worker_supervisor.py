"""
app/core/worker_supervisor.py
--------------------------------
Sprint 10C.2 (PR-001) — WorkerSupervisor.

Orquestra o ciclo de vida (start / stop / restart / health) de todos os
VisionWorkers e das tasks de EventBus.run() registrados no LineRegistry.

Responsabilidades:
  - iniciar workers (start_line / start_all)
  - parar workers (stop_line / stop_all)
  - reiniciar workers (restart_line)
  - monitorar estado (health_snapshot)
  - health checking automático com restart (_monitor_loop)
  - startup automático (chamado pelo lifespan de main.py)
  - shutdown limpo (shutdown() — cancela monitor, para workers e buses,
    aguarda todas as tasks, sem deixar tasks/threads órfãs)

Ajuste do usuário (aprovação Sprint 10C.2): o LineRegistry é a ÚNICA
fonte de verdade — este supervisor NÃO mantém nenhum dict próprio de
workers. Todo estado (worker, event_bus, bus_task, restart_count,
desired_running) vive nos LineContext do registry; o supervisor apenas
lê e muta esses objetos.

Thread-safety: VisionWorker roda em threading.Thread (fora do event
loop) — por isso a leitura/escrita do dict interno do LineRegistry já é
protegida por threading.Lock (ver line_registry.py). Este supervisor usa
um Lock adicional apenas para serializar decisões de start/stop/restart
entre si (evitar duas chamadas concorrentes decidindo iniciar a mesma
linha duas vezes). As operações potencialmente bloqueantes
(VisionWorker.start()/stop(), que fazem thread.join(timeout=5.0)) NUNCA
são executadas dentro do lock nem diretamente dentro de uma coroutine —
são despachadas via asyncio.to_thread() quando chamadas a partir de
código assíncrono (monitor loop, shutdown), para nunca bloquear o event
loop do FastAPI.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from app.core.line_registry import LineRegistry

log = logging.getLogger(__name__)


class WorkerSupervisor:

    def __init__(
        self,
        registry: LineRegistry,
        loop: asyncio.AbstractEventLoop,
        health_interval: float = 15.0,
    ) -> None:
        self._registry = registry
        self._loop = loop
        self._health_interval = health_interval
        self._decision_lock = threading.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._shutting_down = False

    # ── Start ────────────────────────────────────────────────────────────

    def _create_bus_task_on_loop(self, ctx) -> None:
        """
        Cria a asyncio.Task de ctx.event_bus.run() — DEVE ser executado a
        partir da thread do event loop (nunca chamado diretamente de uma
        thread de worker/executor).

        Corrige um bug real encontrado por teste de concorrência: quando
        start_line() é despachado via asyncio.to_thread() (ex: chamado
        de dentro de uma thread do executor), asyncio.create_task()
        levantaria RuntimeError("no running event loop"), pois essa API
        só funciona na thread que efetivamente roda o loop. Por isso a
        criação da task é sempre agendada via loop.call_soon_threadsafe(),
        que garante execução na thread correta independente de quem
        chamou start_line().
        """
        if ctx.event_bus is not None and (ctx.bus_task is None or ctx.bus_task.done()):
            ctx.bus_task = asyncio.create_task(
                ctx.event_bus.run(), name=f"event-bus-line-{ctx.line_id}"
            )

    def start_line(self, line_id: int) -> bool:
        """
        Inicia o worker e a task do EventBus da linha, se ainda não
        estiverem rodando. Idempotente — chamar em uma linha já rodando
        não faz nada.
        """
        with self._decision_lock:
            ctx = self._registry.get(line_id)
            if ctx is None:
                log.warning("WorkerSupervisor: linha %d não encontrada no registry", line_id)
                return False
            ctx.desired_running = True
            worker_needs_start = ctx.worker is not None and not ctx.worker.is_running
            bus_needs_task = ctx.event_bus is not None and (ctx.bus_task is None or ctx.bus_task.done())

        # Fora do lock: start() de thread é rápido (só dispara a thread),
        # mas evitamos qualquer chamada bloqueante dentro da seção crítica.
        if worker_needs_start:
            ctx.worker.start()
            log.info("WorkerSupervisor: worker da linha %d (%s) iniciado", line_id, ctx.code)
        if bus_needs_task:
            # Sempre via call_soon_threadsafe — seguro tanto se start_line()
            # roda na própria thread do loop quanto se foi despachado via
            # asyncio.to_thread() a partir de outra thread (ver docstring
            # de _create_bus_task_on_loop).
            self._loop.call_soon_threadsafe(self._create_bus_task_on_loop, ctx)
            log.info("WorkerSupervisor: EventBus da linha %d (%s) agendado para iniciar", line_id, ctx.code)
        return True

    def start_all(self) -> None:
        for ctx in self._registry.all():
            self.start_line(ctx.line_id)

    # ── Stop ─────────────────────────────────────────────────────────────

    def stop_line(self, line_id: int) -> None:
        """
        Para o worker (bloqueante — thread.join(timeout=5.0)) e sinaliza
        parada do EventBus. Uso síncrono direto (ex: chamada administrativa
        pontual); para shutdown do processo inteiro, ver shutdown(), que
        paraleliza via asyncio.to_thread para não bloquear o event loop.
        """
        ctx = self._registry.get(line_id)
        if ctx is None:
            return
        ctx.desired_running = False
        if ctx.worker is not None:
            ctx.worker.stop()
        if ctx.event_bus is not None:
            try:
                asyncio.run_coroutine_threadsafe(ctx.event_bus.stop(), self._loop)
            except RuntimeError:
                # loop não está rodando (ex: em teste síncrono isolado) — ignora
                pass

    def stop_all(self) -> None:
        for ctx in self._registry.all():
            self.stop_line(ctx.line_id)

    # ── Restart ──────────────────────────────────────────────────────────

    def restart_line(self, line_id: int) -> bool:
        """
        Reinicia o worker de uma linha (stop bloqueante + start).
        Síncrono e bloqueante por design — chamadores em contexto
        assíncrono (ex: _monitor_loop) devem despachar via
        asyncio.to_thread(supervisor.restart_line, line_id).
        """
        with self._decision_lock:
            ctx = self._registry.get(line_id)
            if ctx is None:
                return False
            ctx.restart_count += 1
            worker = ctx.worker
            code = ctx.code
            count = ctx.restart_count

        log.warning(
            "WorkerSupervisor: reiniciando worker da linha %d (%s) — tentativa #%d",
            line_id, code, count,
        )
        if worker is not None:
            worker.stop()
            worker.start()
        return True

    # ── Health / monitor ────────────────────────────────────────────────

    def health_snapshot(self) -> list[dict]:
        """Estado atual de todas as linhas registradas — usado por /health."""
        return [
            {
                "line_id": ctx.line_id,
                "code": ctx.code,
                "name": ctx.name,
                "running": bool(ctx.worker and ctx.worker.is_running),
                "desired_running": ctx.desired_running,
                "restart_count": ctx.restart_count,
                "clients": getattr(ctx.event_bus, "client_count", 0) if ctx.event_bus else 0,
                "is_default": ctx.is_default,
            }
            for ctx in self._registry.all()
        ]

    async def _monitor_loop(self) -> None:
        log.info(
            "WorkerSupervisor: monitor de saúde iniciado (intervalo=%.0fs)",
            self._health_interval,
        )
        while not self._shutting_down:
            await asyncio.sleep(self._health_interval)
            if self._shutting_down:
                break
            for ctx in self._registry.all():
                if ctx.desired_running and ctx.worker is not None and not ctx.worker.is_running:
                    log.warning(
                        "WorkerSupervisor: worker da linha %d (%s) morto — "
                        "reiniciando automaticamente",
                        ctx.line_id, ctx.code,
                    )
                    # Despachado em thread — restart_line() é bloqueante
                    # (join + start síncronos); nunca bloquear o event loop.
                    await asyncio.to_thread(self.restart_line, ctx.line_id)

    def start_monitor(self) -> asyncio.Task:
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(), name="worker-supervisor-monitor"
        )
        return self._monitor_task

    # ── Shutdown ─────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """
        Shutdown limpo e paralelo:
          1. cancela o monitor de saúde
          2. para todos os workers em paralelo (asyncio.to_thread — cada
             stop() bloqueia até 5s via thread.join; serializar N linhas
             multiplicaria essa espera desnecessariamente)
          3. sinaliza parada de todos os EventBus
          4. cancela e aguarda todas as tasks de EventBus.run()

        Idempotente e resiliente: nenhuma exceção individual interrompe
        o restante do shutdown (return_exceptions=True nos gathers).
        """
        self._shutting_down = True

        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        contexts = self._registry.all()
        for ctx in contexts:
            ctx.desired_running = False

        # Passo 2 — para workers em paralelo (offload de I/O bloqueante)
        stop_calls = [
            asyncio.to_thread(ctx.worker.stop)
            for ctx in contexts
            if ctx.worker is not None
        ]
        if stop_calls:
            await asyncio.gather(*stop_calls, return_exceptions=True)

        # Passo 3 — sinaliza parada de todos os buses
        bus_stops = [
            ctx.event_bus.stop() for ctx in contexts if ctx.event_bus is not None
        ]
        if bus_stops:
            await asyncio.gather(*bus_stops, return_exceptions=True)

        # Passo 4 — cancela e aguarda as tasks de consumo de cada bus
        bus_tasks = [ctx.bus_task for ctx in contexts if ctx.bus_task is not None]
        for t in bus_tasks:
            t.cancel()
        if bus_tasks:
            await asyncio.gather(*bus_tasks, return_exceptions=True)

        log.info("WorkerSupervisor: shutdown completo (%d linha(s))", len(contexts))
