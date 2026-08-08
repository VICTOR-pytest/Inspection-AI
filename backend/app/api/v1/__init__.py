from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.cameras import router as cameras_router                # Sprint 10C.1
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.decision import router as decision_router
from app.api.v1.health import router as health_router
from app.api.v1.images import router as images_router
from app.api.v1.inspection import router as inspection_router
from app.api.v1.metrics_prometheus import router as prometheus_router  # Sprint 9B.4
from app.api.v1.products import router as products_router
from app.api.v1.production_lines import router as production_lines_router  # Sprint 10C.1
from app.api.v1.runs import router as runs_router                      # Sprint 10C.1
from app.api.v1.storage_api import router as storage_router            # Sprint 9B.4
from app.api.v1.ws import router as ws_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router)                       # Sprint 9B.1 — autenticação
api_router.include_router(prometheus_router)                 # Sprint 9B.4 — /metrics Prometheus
api_router.include_router(products_router)
api_router.include_router(inspection_router)
api_router.include_router(ws_router)                         # Sprint 5 — WebSocket
api_router.include_router(dashboard_router)                  # Sprint 6 — /api/v1/*
api_router.include_router(images_router, prefix="/api/v1")   # Sprint 7B — imagens
api_router.include_router(decision_router, prefix="/api/v1") # Sprint 9A — decisão humana
api_router.include_router(storage_router)                    # Sprint 9B.4 — storage/LGPD
api_router.include_router(production_lines_router)            # Sprint 10C.1 — /lines
api_router.include_router(cameras_router)                     # Sprint 10C.1 — /cameras
api_router.include_router(runs_router)                        # Sprint 10C.1 — /runs
