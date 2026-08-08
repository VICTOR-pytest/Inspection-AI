from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_admin
from app.database.session import get_db
from app.models.user import User
from app.repositories.product_repository import ProductRepository
from app.schemas.product import ProductCreate, ProductRead

router = APIRouter(prefix="/products", tags=["products"])


@router.post(
    "/",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar produto no catálogo",
    description="Requer role ADMIN.",
    responses={
        401: {"description": "Token ausente ou inválido"},
        403: {"description": "Requer role ADMIN"},
    },
)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ProductRead:
    repo = ProductRepository(db)
    if repo.get_by_barcode(payload.barcode):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Produto com barcode '{payload.barcode}' já existe.",
        )
    return repo.create(payload)


@router.get(
    "/",
    response_model=list[ProductRead],
    summary="Listar todos os produtos",
)
def list_products(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ProductRead]:
    return ProductRepository(db).list_all()


@router.get(
    "/{product_id}",
    response_model=ProductRead,
    summary="Buscar produto por ID",
)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ProductRead:
    product = ProductRepository(db).get_by_id(product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Produto {product_id} não encontrado.",
        )
    return product
