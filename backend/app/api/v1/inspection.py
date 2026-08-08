"""
api/v1/inspection.py
--------------------
Router de inspeções.

Endpoints:
  POST /inspection/check        — Sprint 2: validação manual (barcode + peso)
  POST /inspection/realtime     — Sprint 3: validação via imagem base64
  GET  /inspection/             — Lista últimas 50 inspeções
  GET  /inspection/{id}         — Detalhe de inspeção
"""
import logging
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.repositories.inspection_repository import InspectionRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.inspection import (
    InspectionRead,
    InspectionRequest,
    InspectionResult,
    RealtimeInspectionRequest,
    RealtimeInspectionResult,
)
from app.services.inspection_service import validate_product

log = logging.getLogger(__name__)

router = APIRouter(prefix="/inspection", tags=["inspection"])

# ---------------------------------------------------------------------------
# Utilitário: importar módulo vision do monorepo
# ---------------------------------------------------------------------------

def _get_vision_pipeline():
    """
    Importa o pipeline de visão dinamicamente.

    O módulo ``vision/`` está na raiz do monorepo, fora do ``backend/``.
    Em Docker, o PYTHONPATH aponta para a raiz. Em desenvolvimento local,
    adicionamos o caminho manualmente.
    """
    try:
        from vision.pipeline import decode_base64_image, process_frame
        return decode_base64_image, process_frame
    except ModuleNotFoundError:
        # Tenta resolver o caminho relativo ao backend (desenvolvimento local)
        root = Path(__file__).resolve().parents[4]  # inspection-ai/
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from vision.pipeline import decode_base64_image, process_frame
        return decode_base64_image, process_frame


# ---------------------------------------------------------------------------
# Sprint 2 — validação manual
# ---------------------------------------------------------------------------

@router.post(
    "/check",
    response_model=InspectionResult,
    status_code=status.HTTP_200_OK,
    summary="Validar produto na esteira (manual)",
    description=(
        "Recebe barcode e peso do scanner da linha de produção, "
        "valida contra o catálogo de produtos, persiste o resultado "
        "e retorna o diagnóstico da inspeção."
    ),
)
def check_inspection(
    payload: InspectionRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> InspectionResult:
    product_repo = ProductRepository(db)
    inspection_repo = InspectionRepository(db)

    product = product_repo.get_by_barcode(payload.barcode)
    result = validate_product(product, payload.weight)

    inspection_repo.create(
        barcode=payload.barcode,
        weight=payload.weight,
        is_valid=result.valid,
        reason=result.reason,
        product_id=product.id if product else None,
        confidence=1.0,               # inspeção manual: sem inferência de câmera
        product_name=result.product_name,
    )

    return InspectionResult(
        barcode_ok=result.barcode_ok,
        weight_ok=result.weight_ok,
        valid=result.valid,
        product_name=result.product_name,
        reason=result.reason,
    )


# ---------------------------------------------------------------------------
# Sprint 3 — validação via imagem (pipeline de visão computacional)
# ---------------------------------------------------------------------------

@router.post(
    "/realtime",
    response_model=RealtimeInspectionResult,
    status_code=status.HTTP_200_OK,
    summary="Validar produto via imagem (visão computacional)",
    description=(
        "Recebe imagem base64 capturada pela câmera da esteira e o peso "
        "medido pelo sensor. Extrai barcode automaticamente via OpenCV + pyzbar, "
        "valida contra o catálogo e persiste o resultado."
    ),
)
def realtime_inspection(
    payload: RealtimeInspectionRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> RealtimeInspectionResult:
    # 1. Importar pipeline de visão
    try:
        decode_base64_image, process_frame = _get_vision_pipeline()
    except Exception as exc:
        log.error("Módulo vision não disponível: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Módulo de visão computacional indisponível. "
                "Verifique se as dependências OpenCV/pyzbar estão instaladas."
            ),
        ) from exc

    # 2. Decodificar imagem base64 → frame numpy
    try:
        frame = decode_base64_image(payload.image)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Imagem inválida: {exc}",
        ) from exc

    # 3. Processar frame pelo pipeline de visão
    analysis = process_frame(frame)
    barcode_value: str | None = analysis["barcode"]

    # 4. Validar produto no banco de dados
    product_repo = ProductRepository(db)
    inspection_repo = InspectionRepository(db)

    product = product_repo.get_by_barcode(barcode_value) if barcode_value else None
    validation = validate_product(product, payload.weight)

    # 5. Compor motivo final (inclui ausência de barcode na imagem)
    reason = validation.reason
    if not barcode_value:
        reason = "Nenhum código de barras detectado na imagem."

    # 6. Persistir inspeção
    inspection_repo.create(
        barcode=barcode_value or "UNDETECTED",
        weight=payload.weight,
        is_valid=validation.valid and bool(barcode_value),
        reason=reason,
        product_id=product.id if product else None,
    )

    is_valid = validation.valid and bool(barcode_value)

    log.info(
        "Realtime inspection: barcode=%s valid=%s detected=%s",
        barcode_value or "N/A",
        is_valid,
        analysis["detected"],
    )

    return RealtimeInspectionResult(
        barcode=barcode_value,
        product_name=validation.product_name,
        valid=is_valid,
        barcode_ok=validation.barcode_ok and bool(barcode_value),
        weight_ok=validation.weight_ok,
        reason=reason,
        detected=analysis["detected"],
        detection_confidence=analysis["detection_confidence"],
    )


# ---------------------------------------------------------------------------
# Listagem e detalhe
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[InspectionRead],
    summary="Listar inspeções recentes",
    description="Retorna as 50 inspeções mais recentes.",
)
def list_inspections(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[InspectionRead]:
    return InspectionRepository(db).list_recent(limit=50)


@router.get(
    "/{inspection_id}",
    response_model=InspectionRead,
    summary="Buscar inspeção por ID",
)
def get_inspection(
    inspection_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> InspectionRead:
    inspection = InspectionRepository(db).get_by_id(inspection_id)
    if inspection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inspeção {inspection_id} não encontrada.",
        )
    return inspection
