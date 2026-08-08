"""
app/services/dashboard_service.py
-----------------------------------
Sprint 6  — persist_event(), get_metrics(), get_dashboard()
Sprint 7B — persist_event() salva imagem quando jpeg_bytes disponível
Sprint 8B — persist_event() salva versão anotada (annotated_jpeg_bytes)
Sprint 9A — métricas de decisão humana
Sprint 9B.3 — get_metrics() e get_dashboard() consolidados (P0)

Mudanças Sprint 9B.3:
  get_metrics():   6 queries COUNT() → 1 query get_aggregate_stats()
  get_dashboard(): 7 queries (6 COUNT + hourly_breakdown O(N))
                 → 2 queries (1 aggregate + 1 hourly_breakdown_sql GROUP BY)

  Impacto:
    - get_metrics():   83% menos round-trips ao banco
    - get_dashboard(): O(N) memória → O(1) memória (sempre 24 buckets)
    - A 5fps/24h: ~144MB RAM por chamada → ~1KB por chamada
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.repositories.inspection_repository import InspectionRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.dashboard import DashboardResponse, HourlyBucket, MetricsResponse

if TYPE_CHECKING:
    from app.models.inspection import Inspection


def persist_event(
    db: Session,
    event: dict[str, Any],
    jpeg_bytes: bytes | None = None,
    annotated_jpeg_bytes: bytes | None = None,
) -> "Inspection | None":
    """
    Persiste um evento de inspeção emitido pelo EventBus/VisionWorker.

    Sprint 7B: se jpeg_bytes for fornecido, salva a imagem original em disco e
    registra em inspection_images. Falhas de IO são logadas mas não
    propagadas — a inspeção é sempre persistida independente da imagem.

    Sprint 8B: se annotated_jpeg_bytes for fornecido, salva adicionalmente
    a versão anotada com bounding boxes em images/annotated/. Também com
    falha silenciosa — não bloqueia a persistência da inspeção.

    Sprint 10C.2 (PR-006): se o evento carrega `line_id`/`camera_id`
    (preenchidos automaticamente pelo VisionWorker da linha — ver
    vision/worker.py::_build_event), a inspeção é automaticamente associada
    à linha/câmera de origem, e o InspectionRun ATIVO daquela linha (se
    houver) é resolvido e associado via `inspection_run_id`.

    Nenhum preenchimento manual é necessário — e nenhum destes campos é
    obrigatório: um worker sem line_id (modo legado/single-worker) continua
    persistindo normalmente com os 3 campos NULL, exatamente como antes.

    Retorna o objeto Inspection criado (útil para testes e para obter o id).
    """
    if event.get("type") != "inspection":
        return None

    barcode = event.get("barcode") or "UNDETECTED"
    product_repo = ProductRepository(db)
    inspection_repo = InspectionRepository(db)

    product = product_repo.get_by_barcode(barcode) if event.get("barcode") else None

    line_id   = event.get("line_id")
    camera_id = event.get("camera_id")
    inspection_run_id: int | None = None
    if line_id is not None:
        try:
            from app.repositories.inspection_run_repository import InspectionRunRepository
            active_run = InspectionRunRepository(db).get_active_by_line(line_id)
            if active_run is not None:
                inspection_run_id = active_run.id
        except Exception:
            # Nunca falha a persistência da inspeção por causa da resolução
            # do run — na pior hipótese, inspection_run_id fica NULL.
            inspection_run_id = None

    inspection = inspection_repo.create(
        barcode=barcode,
        weight=float(event.get("weight", 0.0)),
        is_valid=bool(event.get("valid", False)),
        reason=event.get("reason"),
        product_id=product.id if product else None,
        confidence=float(event.get("confidence", 1.0)),
        product_name=event.get("product_name"),
        line_id=line_id,
        camera_id=camera_id,
        inspection_run_id=inspection_run_id,
    )

    # Sprint 7B — persistência de imagem original (opcional, falha silenciosa)
    if jpeg_bytes:
        _persist_image(db, inspection, jpeg_bytes, variant="original")

    # Sprint 8B — persistência de imagem anotada (opcional, falha silenciosa)
    if annotated_jpeg_bytes:
        _persist_image(db, inspection, annotated_jpeg_bytes, variant="annotated")

    return inspection


def _persist_image(
    db: Session,
    inspection: "Inspection",
    jpeg_bytes: bytes,
    variant: str = "original",
) -> None:
    """
    Salva imagem em disco e cria registro em inspection_images.

    Sprint 8B: `variant` determina o subdiretório de destino:
      "original"  → images/original/YYYY/MM/DD/
      "annotated" → images/annotated/YYYY/MM/DD/

    Falhas de IO ou DB são capturadas e logadas — não propagadas.
    """
    import logging
    log = logging.getLogger(__name__)

    try:
        from app.core.config import settings
        from app.models.inspection_image import InspectionImage
        from app.services.image_storage import ImageStorageError, save_frame_bytes

        relative_path = save_frame_bytes(
            jpeg_bytes=jpeg_bytes,
            base_path=settings.storage_path,
            inspection_id=inspection.id,
            variant=variant,
        )

        img_record = InspectionImage(
            inspection_id=inspection.id,
            file_path=relative_path,
            variant=variant,
        )
        db.add(img_record)
        db.commit()
        log.debug(
            "Imagem persistida (%s): inspection_id=%d path=%s",
            variant,
            inspection.id,
            relative_path,
        )
    except ImageStorageError as exc:
        log.warning(
            "Falha ao salvar imagem %s da inspeção %d: %s",
            variant,
            inspection.id,
            exc,
        )
    except Exception as exc:
        log.error("Erro inesperado ao persistir imagem (%s): %s", variant, exc)
        db.rollback()


def get_metrics(db: Session, fps: float = 0.0, line_id: int | None = None) -> MetricsResponse:
    """
    Métricas agregadas em UMA única query SQL.

    Sprint 9B.3 — substitui 6 COUNT() separados por get_aggregate_stats().
    Sprint 10C.2 — parâmetro opcional `line_id` permite consultar métricas
    de uma linha específica; None (default) preserva o comportamento
    agregado original — nenhum caller existente precisa ser modificado.

    Antes: 6 round-trips ao banco (count_total + 2×count_by_validity + 3×count_by_decision)
    Depois: 1 round-trip — 83% menos latência de banco.

    Interface pública idêntica — nenhum caller precisa ser modificado.
    """
    repo  = InspectionRepository(db)
    # Chama sem o kwarg `line_id` quando não usado — preserva compatibilidade
    # com código/testes que fazem monkeypatch de get_aggregate_stats()
    # assumindo a assinatura pré-10C.2 (self) apenas.
    stats = repo.get_aggregate_stats(line_id=line_id) if line_id is not None else repo.get_aggregate_stats()   # 1 query — Sprint 9B.3/10C.2

    total    = stats["total"]
    approved = stats["valid_count"]
    rejected = stats["invalid_count"]
    error_rate = (rejected / total) if total else 0.0

    dec_approved = stats["dec_approved"]
    dec_rejected = stats["dec_rejected"]
    dec_pending  = stats["dec_pending"]
    reviewed       = dec_approved + dec_rejected
    approval_rate  = (dec_approved / reviewed) if reviewed else 0.0
    rejection_rate = (dec_rejected / reviewed) if reviewed else 0.0

    return MetricsResponse(
        total=total,
        approved=approved,
        rejected=rejected,
        error_rate=round(error_rate, 4),
        fps=round(fps, 2),
        decision_approved=dec_approved,
        decision_rejected=dec_rejected,
        decision_pending=dec_pending,
        approval_rate=round(approval_rate, 4),
        rejection_rate=round(rejection_rate, 4),
    )


def get_dashboard(db: Session, line_id: int | None = None) -> DashboardResponse:
    """
    Payload agregado para o endpoint /api/v1/dashboard.

    Sprint 9B.3 — substitui 7 queries separadas por 2 queries consolidadas.
    Sprint 10C.2 — parâmetro opcional `line_id` permite consultar o
    dashboard de uma linha específica; None (default) preserva o
    comportamento agregado original — nenhum caller existente precisa ser
    modificado.

    Antes: 7 queries (6 COUNT separados + hourly_breakdown O(N) em Python)
           A 5fps/24h: carregava ~432.000 objetos em RAM (~144MB) por chamada.

    Depois: 2 queries
      1. get_aggregate_stats()    → 1 SELECT com 6 CASE/WHEN  (scalares)
      2. hourly_breakdown_sql()   → 1 SELECT GROUP BY hora    (24 rows)

    O(1) memória independente do volume de inspeções no banco.
    Interface pública idêntica — nenhum caller precisa ser modificado.
    """
    repo  = InspectionRepository(db)
    stats = repo.get_aggregate_stats(line_id=line_id) if line_id is not None else repo.get_aggregate_stats()  # 1 query
    hourly = repo.hourly_breakdown_sql(hours=24, line_id=line_id) if line_id is not None else repo.hourly_breakdown_sql(hours=24)  # 1 query

    total    = stats["total"]
    approved = stats["valid_count"]
    rejected = stats["invalid_count"]
    error_rate = (rejected / total) if total else 0.0

    dec_approved = stats["dec_approved"]
    dec_rejected = stats["dec_rejected"]
    dec_pending  = stats["dec_pending"]
    reviewed       = dec_approved + dec_rejected
    approval_rate  = (dec_approved / reviewed) if reviewed else 0.0
    rejection_rate = (dec_rejected / reviewed) if reviewed else 0.0

    return DashboardResponse(
        total_inspections=total,
        approved=approved,
        rejected=rejected,
        error_rate=round(error_rate, 4),
        last_24h=[HourlyBucket(**bucket) for bucket in hourly],
        decision_approved=dec_approved,
        decision_rejected=dec_rejected,
        decision_pending=dec_pending,
        approval_rate=round(approval_rate, 4),
        rejection_rate=round(rejection_rate, 4),
    )

