from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_admin
from app.database.session import get_db
from app.models.user import User
from app.repositories.production_line_repository import ProductionLineRepository
from app.schemas.production_line import ProductionLineCreate, ProductionLineRead

router = APIRouter(prefix="/lines", tags=["production-lines"])


@router.post(
    "/",
    response_model=ProductionLineRead,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar linha de produção",
    description="Requer role ADMIN.",
    responses={
        401: {"description": "Token ausente ou inválido"},
        403: {"description": "Requer role ADMIN"},
        409: {"description": "Já existe uma linha com esse code"},
    },
)
def create_line(
    payload: ProductionLineCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ProductionLineRead:
    repo = ProductionLineRepository(db)
    if repo.get_by_code(payload.code):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Linha de produção com code '{payload.code}' já existe.",
        )
    return repo.create(payload)


@router.get(
    "/",
    response_model=list[ProductionLineRead],
    summary="Listar todas as linhas de produção",
)
def list_lines(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ProductionLineRead]:
    return ProductionLineRepository(db).list_all()


@router.get(
    "/{line_id}",
    response_model=ProductionLineRead,
    summary="Buscar linha de produção por ID",
    responses={404: {"description": "Linha não encontrada"}},
)
def get_line(
    line_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ProductionLineRead:
    line = ProductionLineRepository(db).get_by_id(line_id)
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Linha de produção {line_id} não encontrada.",
        )
    return line
