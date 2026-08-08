from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_admin
from app.database.session import get_db
from app.models.user import User
from app.repositories.camera_repository import CameraRepository
from app.repositories.production_line_repository import ProductionLineRepository
from app.schemas.camera import CameraCreate, CameraRead

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.post(
    "/",
    response_model=CameraRead,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar câmera",
    description="Requer role ADMIN.",
    responses={
        401: {"description": "Token ausente ou inválido"},
        403: {"description": "Requer role ADMIN"},
        404: {"description": "Linha de produção não encontrada"},
    },
)
def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> CameraRead:
    if ProductionLineRepository(db).get_by_id(payload.production_line_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Linha de produção {payload.production_line_id} não encontrada.",
        )
    return CameraRepository(db).create(payload)


@router.get(
    "/",
    response_model=list[CameraRead],
    summary="Listar todas as câmeras",
)
def list_cameras(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[CameraRead]:
    return CameraRepository(db).list_all()


@router.get(
    "/{camera_id}",
    response_model=CameraRead,
    summary="Buscar câmera por ID",
    responses={404: {"description": "Câmera não encontrada"}},
)
def get_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CameraRead:
    camera = CameraRepository(db).get_by_id(camera_id)
    if camera is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Câmera {camera_id} não encontrada.",
        )
    return camera
