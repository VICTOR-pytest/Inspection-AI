"""
app/core/line_registry.py
----------------------------
Sprint 10C.2 (PR-002) — LineRegistry.

Registro central em memória de processo, mapeando cada linha de produção
ativa ao seu contexto de runtime: VisionWorker, EventBus e câmera.

Chave interna: SEMPRE `ProductionLine.id` (inteiro), NUNCA `code`.
`code` é apenas um atributo de exibição/lookup auxiliar — a fonte de
verdade estrutural é o id, igual ao resto do domínio (Sprint 10C.1).

Este é o ÚNICO lugar do processo com autoridade para responder "qual é o
worker/bus/câmera da linha X". Nenhum outro módulo deve fazer lookup
manual (ex: dict próprio, variável global paralela) — WorkerSupervisor,
ws.py, health_service.py, metrics_prometheus.py e dashboard.py consultam
exclusivamente este registry.

Thread-safety: os LineContext são escritos a partir do lifespan (asyncio)
e potencialmente lidos/atualizados a partir de threads de worker via o
WorkerSupervisor — por isso todo acesso ao dict interno é protegido por
threading.Lock (não asyncio.Lock, pois há acesso de threads não-async).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LineContext:
    """
    Contexto de runtime de uma linha de produção.

    Campos geridos pelo WorkerSupervisor (não escrever diretamente fora
    dele, exceto durante o registro inicial no lifespan):
      bus_task, restart_count, desired_running
    """
    line_id: int
    code: str
    name: str
    worker: Any = None            # vision.worker.VisionWorker | None
    event_bus: Any = None         # app.core.events.EventBus | None
    camera_id: int | None = None
    is_default: bool = False

    # Geridos pelo WorkerSupervisor:
    bus_task: Any = None          # asyncio.Task | None
    restart_count: int = 0
    desired_running: bool = False


class LineRegistry:
    """
    Fonte única de verdade em runtime para localizar o contexto de cada
    linha de produção ativa. Populado no lifespan de main.py a partir de
    ProductionLineRepository; consultado por todo o resto do sistema.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lines: dict[int, LineContext] = {}
        self._default_line_id: int | None = None

    # ── Escrita ──────────────────────────────────────────────────────────

    def register(self, ctx: LineContext) -> None:
        with self._lock:
            self._lines[ctx.line_id] = ctx
            if ctx.is_default:
                self._default_line_id = ctx.line_id

    def unregister(self, line_id: int) -> LineContext | None:
        with self._lock:
            ctx = self._lines.pop(line_id, None)
            if self._default_line_id == line_id:
                self._default_line_id = None
            return ctx

    def set_default(self, line_id: int) -> None:
        with self._lock:
            if line_id in self._lines:
                self._default_line_id = line_id
                self._lines[line_id].is_default = True

    def clear(self) -> None:
        """Reseta o registry por completo. Uso principal: testes."""
        with self._lock:
            self._lines.clear()
            self._default_line_id = None

    # ── Leitura ──────────────────────────────────────────────────────────

    def get(self, line_id: int) -> LineContext | None:
        with self._lock:
            return self._lines.get(line_id)

    def get_by_code(self, code: str) -> LineContext | None:
        with self._lock:
            for ctx in self._lines.values():
                if ctx.code == code:
                    return ctx
        return None

    def all(self) -> list[LineContext]:
        with self._lock:
            return list(self._lines.values())

    def default(self) -> LineContext | None:
        with self._lock:
            if self._default_line_id is None:
                return None
            return self._lines.get(self._default_line_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._lines)

    def __contains__(self, line_id: int) -> bool:
        with self._lock:
            return line_id in self._lines


# Singleton do processo — populado pelo lifespan de app/main.py.
# Vazio (len() == 0) até o primeiro startup completar; consumidores devem
# tratar "linha não encontrada" com fallback gracioso, nunca com crash.
line_registry = LineRegistry()
