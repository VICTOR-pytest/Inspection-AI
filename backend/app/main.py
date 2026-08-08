"""
app/main.py
-----------
Entry point FastAPI.

Sprint 9B.1: CORS por ambiente, /docs restrito em produção, JWT middleware.
Sprint 9B.2:
  - debug=settings.debug propagado ao FastAPI (evita stack traces em prod)
  - Handler global de Exception: log interno completo + resposta genérica em prod
  - Structured logging com request_id, método, endpoint, status, duração, user_id
  - Pool de conexão DB configurável via Settings
  - WebSocket heartbeat com timeout configurável
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import settings
from app.core.events import event_bus

log = logging.getLogger(__name__)

# ── Structured Logging (Sprint 9B.2 — EH-004) ────────────────────────────────
# Configura logging JSON-friendly para ambientes de produção.
# Em dev: formato legível; em prod: formato JSON parseable por ELK/Grafana.

def _configure_logging() -> None:
    """
    Configura o sistema de logging da aplicação.

    Dev:  nível DEBUG, formato legível para terminal
    Prod: nível INFO, formato estruturado (timestamp | level | logger | msg)

    Sprint 9B.4: em produção, adiciona RotatingFileHandler se LOG_FILE estiver
    configurado em Settings. Logs rotativos evitam crescimento infinito em disco.
    O stdout handler permanece ativo em todos os ambientes (necessário para
    Docker `docker logs` e coleta por Loki/Fluentd).
    """
    log_level = logging.DEBUG if settings.debug else logging.INFO

    fmt_dev  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    fmt_prod = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    fmt = fmt_dev if settings.environment == "dev" else fmt_prod

    logging.basicConfig(
        level=log_level,
        format=fmt,
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # Reduz verbosidade de libs externas em produção
    if settings.environment == "prod":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


_configure_logging()


# ── VisionWorker factory ──────────────────────────────────────────────────────

def _resolution_to_wh(resolution: str | None) -> tuple[int, int] | None:
    """'1280x720' -> (1280, 720). Retorna None se malformado/ausente."""
    if not resolution:
        return None
    try:
        w_str, h_str = resolution.lower().split("x")
        return int(w_str), int(h_str)
    except (ValueError, AttributeError):
        return None


def _build_source_from_camera(camera) -> Any:
    """
    Sprint 10C.2 (PR-003, ajuste do usuário) — a tabela `Camera` (Sprint
    10C.1) é a fonte PRINCIPAL de configuração de câmera; env vars
    (CAMERA_MODE/CAMERA_INDEX/CAMERA_FPS) são usadas apenas como fallback
    quando `camera` é None ou quando a fonte não pode ser aberta.

    Convenção do campo Camera.source:
      ""/"simulated"      → SimulatedSource
      dígitos (ex: "0")   → WebcamSource(index=int(...))  — webcam local
      qualquer outro texto (RTSP/URL/path) → WebcamSource(index=<string>)
                                              (cv2.VideoCapture aceita string)

    Retorna None se não for possível abrir a fonte descrita pela câmera —
    o chamador deve então cair no fallback de env vars, exatamente como o
    comportamento pré-10C.2.
    """
    try:
        from vision.source import SimulatedSource, WebcamSource
    except ImportError:
        return None

    src = (camera.source or "").strip().lower()
    fps = camera.fps if camera.fps else None
    wh = _resolution_to_wh(camera.resolution)

    if src in ("", "simulated"):
        return SimulatedSource(fps=fps or 2.0)

    try:
        index: int | str = int(src) if src.isdigit() else camera.source
        kwargs: dict[str, Any] = {"index": index, "fps": fps or 5.0}
        if wh:
            kwargs["width"], kwargs["height"] = wh
        source = WebcamSource(**kwargs)
        source.open()
        source.close()
        return source
    except Exception as exc:
        log.warning(
            "Camera id=%s source=%r indisponível (%s) — fallback para env vars",
            getattr(camera, "id", "?"), camera.source, exc,
        )
        return None


def _make_worker(
    loop: asyncio.AbstractEventLoop,
    line_id: int | None = None,
    camera: Any = None,
    bus: Any = None,
):
    """
    Instancia VisionWorker com a fonte de frames correta.

    Assinatura pré-10C.2 preservada: `_make_worker(loop)` continua
    funcionando EXATAMENTE como antes (fallback total em env vars,
    worker sem line_id/camera_id, usando o `event_bus` singleton) —
    nenhum caller/teste existente precisa mudar.

    Sprint 10C.2 (PR-003) — parâmetros novos, todos opcionais:
      line_id : associa o worker resultante a uma linha (propagado a
                VisionWorker e, por consequência, a cada evento gerado).
      camera  : instância de app.models.camera.Camera — quando fornecida,
                é a fonte PRINCIPAL de configuração (ajuste do usuário);
                env vars viram fallback se a câmera não puder ser aberta.
      bus     : EventBus a injetar no worker; None usa o `event_bus`
                singleton (comportamento antigo idêntico).

    Fluxo (sem `camera`, comportamento idêntico ao pré-10C.2):
      CAMERA_MODE=simulated  →  SimulatedSource (sempre funciona)
      CAMERA_MODE=webcam     →  WebcamSource → fallback para Simulated se falhar

    Retorna None se o módulo vision não puder ser importado.
    """
    try:
        monorepo_root = Path(__file__).resolve().parents[2]
        if str(monorepo_root) not in sys.path:
            sys.path.insert(0, str(monorepo_root))
    except IndexError:
        pass

    try:
        from vision.source import SimulatedSource, make_source
        from vision.worker import VisionWorker
    except ImportError as exc:
        log.warning("Módulo vision indisponível — worker desativado: %s", exc)
        return None

    detector = None
    try:
        from vision.yolo_detector import make_detector
        detector = make_detector(
            yolo_enabled=settings.yolo_enabled,
            model_path=settings.yolo_model_path,
            confidence_min=settings.yolo_confidence_min,
        )
        log.info(
            "Detector inicializado: %s (yolo_enabled=%s)",
            type(detector).__name__,
            settings.yolo_enabled,
        )
    except Exception as exc:
        log.warning("Falha ao criar detector — worker sem detector: %s", exc)

    # Sprint 10C.2 — tenta a Camera do banco PRIMEIRO (fonte principal).
    source = None
    if camera is not None:
        source = _build_source_from_camera(camera)

    if source is None:
        # Fallback: comportamento idêntico ao pré-10C.2 (env vars).
        mode = settings.camera_mode.strip().lower()

        if mode == "webcam":
            log.info("CAMERA_MODE=webcam — tentando câmera index=%d", settings.camera_index)
            try:
                source = make_source("webcam", index=settings.camera_index, fps=settings.camera_fps)
                source.open()
                source.close()
                log.info("Câmera index=%d OK — modo webcam ativado", settings.camera_index)
            except Exception as exc:
                log.warning(
                    "Webcam index=%d indisponível (%s) — fallback para SimulatedSource",
                    settings.camera_index, exc,
                )
                source = None

        if source is None:
            if mode not in ("simulated", "webcam"):
                log.warning("CAMERA_MODE=%r inválido — usando 'simulated'", mode)
            source = SimulatedSource(fps=2.0)
            log.info("VisionWorker usando SimulatedSource (fps=2.0)")

    effective_bus = bus if bus is not None else event_bus
    camera_id = getattr(camera, "id", None) if camera is not None else None

    return VisionWorker(
        source=source, event_bus=effective_bus, loop=loop, detector=detector,
        line_id=line_id, camera_id=camera_id,
    )


# ── Multi-linha (Sprint 10C.2) ─────────────────────────────────────────────────

def _bootstrap_line_registry(loop: asyncio.AbstractEventLoop) -> bool:
    """
    Popula o LineRegistry a partir de ProductionLineRepository e cria um
    VisionWorker + EventBus por linha ativa.

    Retorna True se o modo multi-linha foi inicializado com sucesso, False
    se qualquer coisa falhar — nesse caso o chamador (lifespan) cai no
    caminho de fallback pré-10C.2 (1 worker global via `event_bus`
    singleton), garantindo que o sistema NUNCA fique sem funcionar por
    causa de uma falha nesta inicialização adicional.

    A linha cujo `code` == settings.default_line_code (default "L01")
    reutiliza o `event_bus` MÓDULO-LEVEL já existente como seu EventBus —
    não cria uma instância nova para ela. Isso preserva 100% de
    retrocompatibilidade: todo código que importa `event_bus` diretamente
    (dashboard.py, metrics_prometheus.py, health_service.py, ws.py legado)
    continua funcionando sem qualquer alteração enquanto só existir a
    linha padrão.
    """
    from app.core.line_registry import line_registry, LineContext
    from app.core.events import EventBus
    from app.database.session import SessionLocal
    from app.repositories.production_line_repository import ProductionLineRepository
    from app.repositories.camera_repository import CameraRepository

    db = SessionLocal()
    try:
        lines = [l for l in ProductionLineRepository(db).list_all() if l.is_active]
        if not lines:
            log.info("LineRegistry: nenhuma linha ativa encontrada — modo fallback single-worker")
            return False

        cam_repo = CameraRepository(db)
        line_registry.clear()

        for line in lines:
            is_default = (line.code == settings.default_line_code)
            enabled_cameras = [c for c in cam_repo.list_by_line(line.id) if c.enabled]
            camera = enabled_cameras[0] if enabled_cameras else None

            bus = event_bus if is_default else EventBus(maxsize=100, line_id=line.id)
            worker = _make_worker(loop, line_id=line.id, camera=camera, bus=bus)

            ctx = LineContext(
                line_id=line.id,
                code=line.code,
                name=line.name,
                worker=worker,
                event_bus=bus,
                camera_id=(camera.id if camera is not None else None),
                is_default=is_default,
            )
            line_registry.register(ctx)
            log.info(
                "LineRegistry: linha registrada — id=%d code=%s camera_id=%s default=%s",
                line.id, line.code, ctx.camera_id, is_default,
            )

        if line_registry.default() is None and lines:
            # Nenhuma linha com code == default_line_code (ex: L01 foi
            # renomeada) — usa a primeira linha ativa como default, para
            # que o alias /ws/inspection sempre resolva para algo.
            line_registry.set_default(lines[0].id)
            log.warning(
                "LineRegistry: nenhuma linha com code=%r — usando %r (id=%d) como default",
                settings.default_line_code, lines[0].code, lines[0].id,
            )

        return True
    except Exception as exc:
        log.warning(
            "LineRegistry: falha ao inicializar modo multi-linha (%s) — "
            "fallback para single-worker legado",
            exc,
        )
        return False
    finally:
        db.close()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()

    # Sprint 10C.2 (PR-001/002/003/004) — tenta o modo multi-linha primeiro.
    # Qualquer falha cai automaticamente no caminho legado abaixo — zero
    # risco de regressão para ambientes com o schema pré-10C.1 ou com
    # falhas transitórias de banco no startup.
    from app.core.line_registry import line_registry
    from app.core.worker_supervisor import WorkerSupervisor

    multi_line_active = _bootstrap_line_registry(loop)

    bus_task: asyncio.Task | None = None
    worker = None
    supervisor: WorkerSupervisor | None = None

    if multi_line_active:
        supervisor = WorkerSupervisor(registry=line_registry, loop=loop)
        app.state.supervisor = supervisor
        supervisor.start_all()
        supervisor.start_monitor()

        default_ctx = line_registry.default()
        worker = default_ctx.worker if default_ctx is not None else None
        app.state.worker = worker  # compat: health.py lê app.state.worker
        log.info(
            "WorkerSupervisor: %d linha(s) ativa(s) iniciadas — default=%s",
            len(line_registry.all()),
            default_ctx.code if default_ctx is not None else "?",
        )
    else:
        # ── Caminho legado (pré-10C.2) — inalterado ─────────────────────
        app.state.supervisor = None
        bus_task = asyncio.create_task(event_bus.run(), name="event-bus")
        worker = _make_worker(loop)
        app.state.worker = worker
        if worker:
            worker.start()
            log.info("VisionWorker iniciado")

    # Sprint 9B.4 — inicializa métricas estáticas da aplicação
    try:
        from app.core.metrics import METRICS
        METRICS.app_info.info({
            "version":     settings.app_version,
            "environment": settings.environment,
            "camera_mode": settings.camera_mode,
            "yolo_enabled": str(settings.yolo_enabled).lower(),
        })
        METRICS.db_pool_size.set(settings.db_pool_size)
        log.info("Métricas Prometheus inicializadas")
    except Exception as exc:
        log.warning("Falha ao inicializar métricas: %s", exc)

    # Sprint 10B — scheduler de manutenção de storage
    # Continua único e global — não pertence a nenhuma linha específica
    # (storage/limpeza de imagens é transversal a todas as linhas).
    from app.core.scheduler import cleanup_scheduler_loop
    scheduler_task = asyncio.create_task(
        cleanup_scheduler_loop(), name="cleanup-scheduler"
    )
    log.info(
        "Scheduler de manutenção iniciado (cleanup às %02d:00 UTC)",
        settings.image_cleanup_hour,
    )

    yield

    # Shutdown: cancela todas as tasks em ordem inversa
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass

    if multi_line_active and supervisor is not None:
        await supervisor.shutdown()
    else:
        # ── Caminho legado (pré-10C.2) — inalterado ─────────────────────
        if worker:
            worker.stop()
        await event_bus.stop()
        if bus_task is not None:
            bus_task.cancel()
            try:
                await bus_task
            except asyncio.CancelledError:
                pass


# ── FastAPI app ───────────────────────────────────────────────────────────────

# Sprint 9B.2: CORS por ambiente
_cors_origins: list[str] = (
    ["*"] if settings.environment == "dev"
    else settings.allowed_origins
)

# Sprint 9B.1: /docs desabilitado em produção
_docs_url    = "/docs"         if settings.environment == "dev" else None
_redoc_url   = "/redoc"        if settings.environment == "dev" else None
_openapi_url = "/openapi.json" if settings.environment == "dev" else None

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Inspection AI — Sistema de inspeção visual industrial",
    lifespan=lifespan,
    # Sprint 9B.2: debug propagado ao FastAPI.
    # debug=True ativa o ServerErrorMiddleware do Starlette que expõe
    # stack traces completos no body da resposta HTTP — NUNCA usar em prod.
    debug=settings.debug,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Structured Logging Middleware (Sprint 9B.2 — EH-004) ─────────────────────

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """
    Middleware de logging estruturado por requisição HTTP.

    Campos logados em cada request:
      request_id  — UUID único por requisição (para correlação em logs)
      method      — GET / POST / etc.
      path        — endpoint chamado (ex: /api/v1/inspections)
      status_code — código HTTP da resposta
      duration_ms — duração total em milissegundos
      user_id     — ID do usuário autenticado (quando disponível via request.state)
      client_ip   — IP do cliente

    O request_id é injetado no request.state para uso em outros middlewares
    e handlers (ex: para incluir no corpo de respostas de erro).
    """
    request_id = str(uuid.uuid4())[:8]  # 8 chars suficientes para correlação em logs
    request.state.request_id = request_id

    start_time = time.perf_counter()

    response = await call_next(request)

    duration_s  = time.perf_counter() - start_time
    duration_ms = round(duration_s * 1000, 1)

    # user_id é preenchido pelos endpoints que chamam get_current_user
    user_id = getattr(request.state, "user_id", None)

    log.info(
        "HTTP | request_id=%s method=%s path=%s status=%d duration_ms=%.1f user_id=%s client=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        user_id or "anon",
        request.client.host if request.client else "unknown",
    )

    response.headers["X-Request-ID"] = request_id

    # Sprint 9B.4 — atualiza métricas Prometheus de HTTP
    try:
        from app.core.metrics import METRICS
        # Normaliza path para evitar cardinalidade infinita (ex: /api/v1/inspections/42 → /api/v1/inspections/{id})
        path_label = _normalize_path(request.url.path)
        METRICS.http_requests_total.labels(
            method=request.method,
            path=path_label,
            status_code=str(response.status_code),
        ).inc()
        METRICS.http_request_duration_seconds.labels(
            method=request.method,
            path=path_label,
        ).observe(duration_s)
    except Exception:
        pass  # métricas nunca devem derrubar o request

    return response


def _normalize_path(path: str) -> str:
    """
    Normaliza paths com IDs numéricos para reduzir cardinalidade das métricas.

    Exemplos:
      /api/v1/inspections/42   → /api/v1/inspections/{id}
      /api/v1/inspections/999  → /api/v1/inspections/{id}
      /api/v1/inspections      → /api/v1/inspections
      /health                  → /health
    """
    import re
    return re.sub(r"/\d+", "/{id}", path)


# ── Global Exception Handler (Sprint 9B.2 — EH-001, EH-002) ─────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handler global para exceções não tratadas.

    Em PRODUÇÃO (environment != "dev"):
      - Loga o traceback completo internamente (nível ERROR)
      - Retorna resposta genérica sem detalhes internos
      - Inclui request_id para correlação com o log interno

    Em DESENVOLVIMENTO (environment == "dev"):
      - Loga o traceback completo
      - Inclui a mensagem de erro na resposta para facilitar debugging
      - NÃO expõe traceback no body (o Starlette debug middleware faz isso
        separadamente quando debug=True)

    Garante que NUNCA vaze: connection strings, stack traces, nomes de
    tabelas, caminhos de arquivo ou qualquer informação interna em produção.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    log.error(
        "Exceção não tratada: request_id=%s method=%s path=%s error=%s",
        request_id,
        request.method,
        request.url.path,
        exc,
        exc_info=True,  # inclui traceback completo no log interno
    )

    if settings.environment == "dev":
        # Dev: mostra a mensagem (não o traceback) para debugging rápido
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": f"Erro interno: {type(exc).__name__}: {exc}",
                "request_id": request_id,
            },
        )

    # Produção: mensagem completamente genérica
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Erro interno do servidor. Contate o suporte.",
            "request_id": request_id,
        },
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "name":    settings.app_name,
        "status":  "running",
        "ws":      "/ws/inspection",
        "clients": event_bus.client_count,
    }
