"""
app/api/v1/images.py
---------------------
Sprint 7B — Endpoint para recuperar imagem de uma inspeção.
Sprint 8C — Suporte ao parâmetro ?variant=original|annotated

GET /api/v1/inspections/{inspection_id}/image
  → Parâmetro opcional: ?variant=original (default) | annotated
  → FileResponse (JPEG) se a imagem existir para a variante pedida
  → 404 se inspeção não encontrada
  → 404 se a variante solicitada não tiver imagem associada
  → 410 Gone se registro existe mas arquivo foi removido do disco

Compatibilidade retroativa:
  Clientes que não passam ?variant recebem a imagem "original" (comportamento
  idêntico ao Sprint 7B). Nenhuma quebra de contrato.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.database.session import get_db
from app.models.inspection_image import InspectionImage
from app.models.user import User
from app.repositories.inspection_repository import InspectionRepository
from app.services.image_storage import PathTraversalError, resolve_full_path

log = logging.getLogger(__name__)

router = APIRouter(tags=["images"])

# Variantes suportadas como tipo literal para validação automática via FastAPI
ImageVariantParam = Literal["original", "annotated"]


@router.get(
    "/inspections/{inspection_id}/image",
    response_class=FileResponse,
    summary="Recuperar imagem de uma inspeção",
    description=(
        "Retorna o arquivo JPEG da inspeção. "
        "Use ?variant=original (default) para o frame capturado, "
        "ou ?variant=annotated para o frame com overlay de detecção YOLO. "
        "Retorna 404 se a inspeção não existir ou não tiver imagem da variante solicitada. "
        "Retorna 410 se o registro existe mas o arquivo foi removido do disco."
    ),
    responses={
        200: {"content": {"image/jpeg": {}}, "description": "Imagem JPEG da inspeção"},
        404: {"description": "Inspeção não encontrada ou sem imagem da variante solicitada"},
        410: {"description": "Registro de imagem existe mas arquivo foi removido do disco"},
    },
)
def get_inspection_image(
    inspection_id: int,
    variant: ImageVariantParam = Query(
        default="original",
        description="Variante da imagem: 'original' (frame capturado) ou 'annotated' (com overlay YOLO)",
    ),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FileResponse:
    # 1. Verificar que a inspeção existe
    inspection = InspectionRepository(db).get_by_id(inspection_id)
    if inspection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inspeção {inspection_id} não encontrada.",
        )

    # 2. Buscar registro de imagem para a variante solicitada
    stmt = select(InspectionImage).where(
        InspectionImage.inspection_id == inspection_id,
        InspectionImage.variant == variant,
    )
    img_record: InspectionImage | None = db.execute(stmt).scalar_one_or_none()

    if img_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Inspeção {inspection_id} não possui imagem '{variant}' associada. "
                f"Tente ?variant=original ou ?variant=annotated."
            ),
        )

    # 3. Resolver caminho físico com proteção contra path traversal (Sprint 9B.2)
    try:
        full_path: Path = resolve_full_path(img_record.file_path, settings.storage_path)
    except PathTraversalError:
        # Nunca deve ocorrer em operação normal.
        # Se ocorrer: dado malicioso no banco — retornar 400, não 500.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Caminho de imagem inválido.",
        )

    if not full_path.exists():
        log.warning(
            "Arquivo de imagem ausente no disco: inspection_id=%d variant=%s path=%s",
            inspection_id,
            variant,
            full_path,
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                f"Arquivo de imagem '{variant}' da inspeção {inspection_id} não encontrado no disco. "
                "O arquivo pode ter sido removido manualmente."
            ),
        )

    log.debug(
        "Servindo imagem: inspection_id=%d variant=%s path=%s",
        inspection_id,
        variant,
        full_path,
    )
    return FileResponse(
        path=str(full_path),
        media_type="image/jpeg",
        filename=f"inspection_{inspection_id}_{variant}.jpg",
    )
