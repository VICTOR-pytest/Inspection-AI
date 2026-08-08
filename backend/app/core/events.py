"""
app/core/events.py
------------------
Sistema de eventos central do Sprint 5.

- asyncio.Queue(maxsize=100)  → backpressure, sem crescimento infinito
- Set de WebSockets           → broadcast O(n) clientes
- Métricas acumuladas         → status da linha (ONLINE / DEGRADED / OFFLINE)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


class LineStatus(str, Enum):
    ONLINE   = "online"
    OFFLINE  = "offline"
    DEGRADED = "degraded"   # taxa de rejeição > 30 %


@dataclass
class InspectionEvent:
    barcode:      str | None
    valid:        bool
    confidence:   float
    weight:       float
    product_name: str | None = None
    reason:       str | None = None
    timestamp:    str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # NOTE (Sprint 8C): to_dict() foi removido — era código morto.
    # O worker emite dicts diretamente via _build_event(); InspectionEvent
    # é usado apenas como anotação de tipo em alguns testes legados.


class EventBus:
    """Barramento de eventos assíncrono — coração do Sprint 5."""

    _DEGRADED_THRESHOLD = 0.30

    def __init__(self, maxsize: int = 100, line_id: int | None = None) -> None:
        self._maxsize = maxsize
        # Sprint 10C.2 (PR-004) — identifica a qual linha esta instância
        # pertence. None = instância legada/singleton (comportamento
        # anterior à 10C.2, ex: o `event_bus` de módulo abaixo enquanto
        # não houver mais de uma linha registrada).
        self.line_id = line_id
        # A Queue é criada lazy em run() para evitar o erro
        # "Queue is bound to a different event loop" em ambientes de teste
        # onde cada TestClient cria um novo event loop.
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._clients: set[WebSocket] = set()
        self._running = False

        # Métricas
        self._total    = 0
        self._approved = 0
        self._rejected = 0
        self._frame_times: list[float] = []

        # Sprint 9B.3 — Circuit Breaker para persistência no banco
        # Sem CB: se banco offline → log.error() a cada evento (~5/segundo)
        # Com CB: 5 falhas → OPEN (silencia por 30s) → HALF_OPEN → testa → CLOSED
        try:
            from app.core.circuit_breaker import CircuitBreaker
            from app.core.config import settings
            self._persist_cb = CircuitBreaker(
                name="persistence",
                failure_threshold=settings.cb_failure_threshold,
                reset_timeout=settings.cb_reset_timeout,
            )
        except Exception:
            self._persist_cb = None

    # ── Client management ──────────────────────────────────────────────────

    def register(self, ws: WebSocket) -> None:
        self._clients.add(ws)
        log.info("WS client connected  total=%d", len(self._clients))

    def unregister(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        log.info("WS client disconnected  total=%d", len(self._clients))

    # ── Producer API ───────────────────────────────────────────────────────

    def put_nowait(self, event: dict[str, Any]) -> None:
        """Thread-safe, non-blocking. Descarta se fila cheia (backpressure)."""
        if self._queue is None:
            # Queue ainda não iniciada — cria temporária ligada ao loop atual.
            # Isso permite uso em testes onde put_nowait ocorre antes de run().
            try:
                self._queue = asyncio.Queue(maxsize=self._maxsize)
            except RuntimeError:
                log.warning("EventBus: sem event loop ativo — evento descartado")
                return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("EventBus: queue full — dropping event (backpressure)")

    # ── Consumer loop ──────────────────────────────────────────────────────

    async def run(self) -> None:
        """Consome fila, persiste no banco e faz broadcast. Roda durante o lifespan."""
        # Cria uma Queue nova no event loop atual, drenando itens da queue
        # anterior (caso exista de um run() anterior em outro loop — comum em testes).
        pending: list = []
        if self._queue is not None:
            try:
                while True:
                    pending.append(self._queue.get_nowait())
            except (asyncio.QueueEmpty, RuntimeError):
                pass
        self._queue = asyncio.Queue(maxsize=self._maxsize)
        for item in pending:
            self._queue.put_nowait(item)
        self._running = True
        log.info("EventBus: processor started")
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if event.get("type") == "inspection":
                self._total += 1
                self._frame_times.append(time.monotonic())
                # janela deslizante de 10 s para FPS
                cutoff = time.monotonic() - 10.0
                self._frame_times = [t for t in self._frame_times if t > cutoff]
                if event.get("valid"):
                    self._approved += 1
                else:
                    self._rejected += 1

                # Sprint 6 — persiste no PostgreSQL sem bloquear o event loop.
                await self._persist_safe(event)

            await self._broadcast(event)
            self._queue.task_done()

    async def _persist_safe(self, event: dict[str, Any]) -> None:
        """
        Persiste evento no banco de dados de forma não-bloqueante.

        Usa asyncio.to_thread() para mover a operação síncrona (_persist_sync,
        que inclui cv2.imwrite e INSERT no banco) para um thread worker —
        mantendo o event loop completamente livre.

        Sprint 9B.3 — Circuit Breaker:
        Se o banco estiver offline ou com falhas repetidas, o CB abre após
        cb_failure_threshold falhas consecutivas, silenciando tentativas por
        cb_reset_timeout segundos antes de testar novamente.
        Isso evita log spam de ~fps/segundo quando o banco está indisponível.
        """
        cb = self._persist_cb

        # Circuito OPEN → pula silenciosamente (banco offline, aguardando recovery)
        if cb is not None and not cb.can_attempt():
            return

        try:
            await asyncio.to_thread(self._persist_sync, event)
            if cb is not None:
                cb.record_success()
        except Exception as exc:
            if cb is not None:
                cb.record_failure(exc)
            else:
                log.error("EventBus: falha ao persistir evento — %s", exc)

    @staticmethod
    def _persist_sync(event: dict[str, Any]) -> None:
        """
        Executa em threadpool — abre sua própria Session síncrona.

        Sprint 7B: se o evento contém 'frame_jpeg' (bytes), salva em disco
        e registra o caminho em inspection_images. O campo é removido do dict
        antes do broadcast para não quebrar JSON serialization.
        """
        from app.database.session import SessionLocal
        from app.services.dashboard_service import persist_event

        # Extrai frames (bytes) antes de persistir — não devem ir ao broadcast JSON
        # (bytes não são serializáveis em JSON; EventBus remove antes do _broadcast)
        jpeg_bytes: bytes | None = event.pop("frame_jpeg", None)
        # Sprint 8B — frame anotado com overlay de detecção YOLO
        annotated_jpeg_bytes: bytes | None = event.pop("annotated_frame_jpeg", None)

        db = SessionLocal()
        try:
            inspection = persist_event(
                db,
                event,
                jpeg_bytes=jpeg_bytes,
                annotated_jpeg_bytes=annotated_jpeg_bytes,  # Sprint 8B
            )
            # Sprint 9A.1 — propagar inspection_id ao evento para o broadcast WS.
            # O frontend precisa do ID para chamar POST /api/v1/inspections/{id}/decision.
            # Adicionado APÓS persist_event pois o id só existe depois do INSERT.
            if inspection is not None:
                event["inspection_id"] = inspection.id
        finally:
            db.close()

    async def stop(self) -> None:
        self._running = False
        log.info("EventBus: processor stopped")

    # ── Broadcast ──────────────────────────────────────────────────────────

    async def _broadcast(self, event: dict[str, Any]) -> None:
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(event)
            except Exception as exc:
                log.warning("WS send failed (%s) — dropping client", type(exc).__name__)
                dead.add(ws)
        for ws in dead:
            self.unregister(ws)

    # ── Status ─────────────────────────────────────────────────────────────

    @property
    def fps(self) -> float:
        n = len(self._frame_times)
        if n < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        return round((n - 1) / span, 2) if span > 0 else 0.0

    @property
    def line_status(self) -> LineStatus:
        if not self._running:
            return LineStatus.OFFLINE
        if self._total == 0:
            return LineStatus.OFFLINE  # ainda aquecendo — nenhum frame processado
        error_rate = self._rejected / self._total
        return LineStatus.DEGRADED if error_rate > self._DEGRADED_THRESHOLD else LineStatus.ONLINE

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "type":       "line_status",
            "status":     self.line_status.value,
            "total":      self._total,
            "approved":   self._approved,
            "rejected":   self._rejected,
            "error_rate": round((self._rejected / self._total) if self._total else 0.0, 4),
            "fps":        self.fps,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Singleton global — Sprint 10C.2: este é, por convenção, o EventBus da
# linha PADRÃO (L01). Não foi removido nem renomeado — todo código
# existente que importa `event_bus` diretamente continua funcionando
# exatamente como antes. O LineRegistry, ao inicializar, registra esta
# MESMA instância como o event_bus da linha default (em vez de criar uma
# nova), preservando 100% de retrocompatibilidade em ambientes com uma
# única linha.
event_bus = EventBus(maxsize=100)
