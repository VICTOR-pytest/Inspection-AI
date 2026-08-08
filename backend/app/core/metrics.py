"""
app/core/metrics.py
--------------------
Sprint 9B.4 — Registro centralizado de métricas Prometheus.

Todas as métricas da aplicação são definidas aqui como singletons.
Importar e usar em qualquer módulo sem risco de duplicate registration.

Categorias:
  HTTP       — requests, duração, erros
  Inspeções  — total, válidas, inválidas, fps, error_rate
  Decisões   — aprovadas, rejeitadas, pendentes, taxas
  Vision     — frames, inferência, erros do detector, worker status
  WebSocket  — conexões ativas, mensagens enviadas
  EventBus   — fila, eventos, descartados, erros de persistência
  Storage    — imagens, disco, cleanup
  DB Pool    — pool size, checked out, overflow
  CircuitBreaker — estado por nome, falhas

Uso em outros módulos:
  from app.core.metrics import METRICS
  METRICS.inspections_total.inc()
  METRICS.http_duration.observe(0.042, {"method": "GET", "path": "/health"})
"""
from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
)

# Buckets de latência para histogramas HTTP e de inferência (em segundos)
# Cobre desde operações muito rápidas (1ms) até lentas (10s)
_HTTP_BUCKETS       = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_INFERENCE_BUCKETS  = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)


class _Metrics:
    """
    Contêiner de métricas Prometheus — instanciado como singleton `METRICS`.

    Todas as métricas são criadas uma única vez no import deste módulo.
    Usar `REGISTRY` ao registrar no app Prometheus caso queira isolamento de testes.
    """

    def __init__(self) -> None:
        # ── Informações da aplicação ──────────────────────────────────────
        self.app_info = Info(
            "inspection_ai_app",
            "Informações da aplicação Inspection AI",
        )

        # ── HTTP ──────────────────────────────────────────────────────────
        self.http_requests_total = Counter(
            "inspection_ai_http_requests_total",
            "Total de requisições HTTP recebidas",
            ["method", "path", "status_code"],
        )
        self.http_request_duration_seconds = Histogram(
            "inspection_ai_http_request_duration_seconds",
            "Duração das requisições HTTP em segundos",
            ["method", "path"],
            buckets=_HTTP_BUCKETS,
        )

        # ── Inspeções ─────────────────────────────────────────────────────
        self.inspections_total = Counter(
            "inspection_ai_inspections_total",
            "Total de inspeções processadas desde o início",
        )
        self.inspections_valid_total = Counter(
            "inspection_ai_inspections_valid_total",
            "Total de inspeções aprovadas automaticamente (is_valid=True)",
        )
        self.inspections_invalid_total = Counter(
            "inspection_ai_inspections_invalid_total",
            "Total de inspeções reprovadas automaticamente (is_valid=False)",
        )
        self.inspection_fps = Gauge(
            "inspection_ai_inspection_fps",
            "Taxa de inspeções por segundo (janela deslizante de 10s)",
        )
        self.inspection_error_rate = Gauge(
            "inspection_ai_inspection_error_rate",
            "Proporção de inspeções inválidas sobre o total (0.0 a 1.0)",
        )

        # ── Decisões humanas ──────────────────────────────────────────────
        self.decisions_approved_total = Counter(
            "inspection_ai_decisions_approved_total",
            "Total de decisões APPROVED registradas por operadores",
        )
        self.decisions_rejected_total = Counter(
            "inspection_ai_decisions_rejected_total",
            "Total de decisões REJECTED registradas por operadores",
        )
        self.decisions_pending_gauge = Gauge(
            "inspection_ai_decisions_pending",
            "Inspeções aguardando decisão humana (snapshot atual)",
        )
        self.decisions_approval_rate = Gauge(
            "inspection_ai_decisions_approval_rate",
            "Taxa de aprovação humana sobre as revisadas (0.0 a 1.0)",
        )

        # ── Vision / YOLO ─────────────────────────────────────────────────
        self.vision_frames_total = Counter(
            "inspection_ai_vision_frames_total",
            "Total de frames processados pelo VisionWorker",
        )
        self.vision_inference_seconds = Histogram(
            "inspection_ai_vision_inference_seconds",
            "Tempo de inferência do detector por frame (segundos)",
            buckets=_INFERENCE_BUCKETS,
        )
        self.vision_detector_errors_total = Counter(
            "inspection_ai_vision_detector_errors_total",
            "Total de erros no detector (falhas capturadas pelo CircuitBreaker)",
        )
        self.vision_worker_running = Gauge(
            "inspection_ai_vision_worker_running",
            "1 se o VisionWorker está ativo, 0 se parado ou indisponível",
        )

        # ── Multi-linha (Sprint 10C.2, PR-001/004) ──────────────────────────
        # Métricas por linha de produção — aditivas, com label `line_code`.
        # Os Gauges acima (sem label) continuam representando a linha padrão
        # em ambientes com uma única linha — nenhum dashboard existente quebra.
        self.line_worker_running = Gauge(
            "inspection_ai_line_worker_running",
            "1 se o VisionWorker da linha está ativo, 0 caso contrário",
            ["line_id", "line_code"],
        )
        self.line_inspection_fps = Gauge(
            "inspection_ai_line_inspection_fps",
            "Taxa de inspeções por segundo, por linha de produção",
            ["line_id", "line_code"],
        )
        self.line_websocket_connections_active = Gauge(
            "inspection_ai_line_websocket_connections_active",
            "Clientes WebSocket conectados, por linha de produção",
            ["line_id", "line_code"],
        )
        self.line_restart_count = Gauge(
            "inspection_ai_line_restart_count",
            "Número de reinícios automáticos do worker desde o startup, por linha",
            ["line_id", "line_code"],
        )

        # ── WebSocket ─────────────────────────────────────────────────────
        self.websocket_connections_active = Gauge(
            "inspection_ai_websocket_connections_active",
            "Número de clientes WebSocket atualmente conectados",
        )
        self.websocket_messages_sent_total = Counter(
            "inspection_ai_websocket_messages_sent_total",
            "Total de mensagens JSON enviadas via WebSocket",
        )

        # ── EventBus ──────────────────────────────────────────────────────
        self.eventbus_queue_size = Gauge(
            "inspection_ai_eventbus_queue_size",
            "Número de eventos aguardando processamento na fila do EventBus",
        )
        self.eventbus_events_total = Counter(
            "inspection_ai_eventbus_events_total",
            "Total de eventos publicados no EventBus",
        )
        self.eventbus_dropped_events_total = Counter(
            "inspection_ai_eventbus_dropped_events_total",
            "Total de eventos descartados por backpressure (fila cheia)",
        )
        self.eventbus_persist_errors_total = Counter(
            "inspection_ai_eventbus_persist_errors_total",
            "Total de falhas ao persistir eventos no banco de dados",
        )

        # ── Storage ───────────────────────────────────────────────────────
        self.storage_images_total = Gauge(
            "inspection_ai_storage_images_total",
            "Total de arquivos de imagem presentes no storage",
            ["variant"],  # "original" | "annotated" | "all"
        )
        self.storage_disk_bytes_used = Gauge(
            "inspection_ai_storage_disk_bytes_used",
            "Bytes de disco usados no filesystem do storage",
        )
        self.storage_disk_bytes_free = Gauge(
            "inspection_ai_storage_disk_bytes_free",
            "Bytes de disco livres no filesystem do storage",
        )
        self.storage_cleanup_deleted_total = Counter(
            "inspection_ai_storage_cleanup_deleted_total",
            "Total de arquivos de imagem deletados por política de retenção",
        )

        # ── Database Pool ─────────────────────────────────────────────────
        self.db_pool_size = Gauge(
            "inspection_ai_db_pool_size",
            "Tamanho configurado do pool de conexões SQLAlchemy",
        )
        self.db_pool_checked_out = Gauge(
            "inspection_ai_db_pool_checked_out",
            "Conexões do pool atualmente em uso",
        )
        self.db_pool_overflow = Gauge(
            "inspection_ai_db_pool_overflow",
            "Conexões de overflow atualmente em uso (além do pool_size)",
        )

        # ── Circuit Breaker ───────────────────────────────────────────────
        self.circuit_breaker_state = Gauge(
            "inspection_ai_circuit_breaker_state",
            "Estado do circuit breaker: 0=CLOSED, 1=OPEN, 2=HALF_OPEN",
            ["name"],
        )
        self.circuit_breaker_failures_total = Counter(
            "inspection_ai_circuit_breaker_failures_total",
            "Total de falhas registradas por circuit breaker",
            ["name"],
        )


# Singleton global — importar em qualquer módulo
METRICS = _Metrics()
