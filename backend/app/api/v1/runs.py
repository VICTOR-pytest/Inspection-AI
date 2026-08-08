from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_admin
from app.database.session import get_db
from app.models.user import User
from app.repositories.inspection_run_repository import InspectionRunRepository
from app.repositories.production_line_repository import ProductionLineRepository
from app.schemas.inspection_run import InspectionRunCreate, InspectionRunRead

router = APIRouter(prefix="/runs", tags=["inspection-runs"])


@router.post(
    "/",
    response_model=InspectionRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar uma execução de produção (InspectionRun) em uma linha",
    description=(
        "Requer role ADMIN. Não permite dois InspectionRun ativos "
        "simultaneamente para a mesma linha de produção."
    ),
    responses={
        401: {"description": "Token ausente ou inválido"},
        403: {"description": "Requer role ADMIN"},
        404: {"description": "Linha de produção não encontrada"},
        409: {"description": "Já existe um InspectionRun ativo para essa linha"},
    },
)
def create_run(
    payload: InspectionRunCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> InspectionRunRead:
    repo = InspectionRunRepository(db)

    if ProductionLineRepository(db).get_by_id(payload.production_line_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Linha de produção {payload.production_line_id} não encontrada.",
        )

    # Checagem "otimista" a nível de aplicação: evita ida desnecessária ao
    # banco na maioria dos casos e devolve uma mensagem de erro amigável.
    active = repo.get_active_by_line(payload.production_line_id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Já existe um InspectionRun ativo (id={active.id}) para a "
                f"linha {payload.production_line_id}. Encerre-o antes de "
                "iniciar um novo."
            ),
        )

    try:
        return repo.create(payload)
    except IntegrityError:
        # Garantia definitiva contra condição de corrida: o índice único
        # parcial ix_inspection_runs_active_line_unique rejeita o INSERT
        # se, entre a checagem acima e o commit, outra requisição já tiver
        # criado um run ativo para a mesma linha.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Já existe um InspectionRun ativo para a linha "
                f"{payload.production_line_id}."
            ),
        )


@router.get(
    "/",
    response_model=list[InspectionRunRead],
    summary="Listar todas as execuções de produção",
)
def list_runs(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[InspectionRunRead]:
    return InspectionRunRepository(db).list_all()


@router.get(
    "/{run_id}",
    response_model=InspectionRunRead,
    summary="Buscar execução de produção por ID",
    responses={404: {"description": "InspectionRun não encontrado"}},
)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> InspectionRunRead:
    run = InspectionRunRepository(db).get_by_id(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"InspectionRun {run_id} não encontrado.",
        )
    return run


@router.patch(
    "/{run_id}/end",
    response_model=InspectionRunRead,
    summary="Encerrar uma execução de produção ativa",
    description="Requer role ADMIN.",
    responses={
        401: {"description": "Token ausente ou inválido"},
        403: {"description": "Requer role ADMIN"},
        404: {"description": "InspectionRun não encontrado"},
        409: {"description": "InspectionRun já está encerrado"},
    },
)
def end_run(
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> InspectionRunRead:
    repo = InspectionRunRepository(db)
    run = repo.get_by_id(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"InspectionRun {run_id} não encontrado.",
        )
    if run.finished_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"InspectionRun {run_id} já está encerrado.",
        )
    return repo.end(run)
