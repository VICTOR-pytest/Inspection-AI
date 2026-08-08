"""
app/api/v1/decision.py
-----------------------
Sprint 9A — Endpoint de decisão humana sobre inspeções.
Sprint 9B.1 — Autenticação obrigatória + audit trail imutável.

POST /api/v1/inspections/{inspection_id}/decision
  Registra a decisão do operador (APPROVED ou REJECTED) sobre uma inspeção.

Mudanças Sprint 9B.1:
  - Requer autenticação (Bearer token JWT)
  - Qualquer usuário autenticado (ADMIN ou OPERATOR) pode decidir
  - Grava registro imutável em inspection_decisions (audit trail)
  - Resposta inclui user_id de quem tomou a decisão

Regras de negócio:
  - Inspeção inexistente → 404
  - Payload inválido     → 422 (Pydantic)
  - REJECTED sem reason  → 422 (validação de negócio no schema)
  - Sucesso              → 200 com DecisionResponse
  - Decisão pode ser sobrescrita em inspection.decision (operador pode corrigir)
  - Mas CADA decisão gera um registro imutável em inspection_decisions
  - reviewed_at preenchido automaticamente pelo servidor (UTC)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.repositories.decision_repository import DecisionRepository
from app.repositories.inspection_repository import InspectionRepository
from app.schemas.decision import DecisionRequest, DecisionResponse

log = logging.getLogger(__name__)

router = APIRouter(tags=["decision"])


@router.post(
    "/inspections/{inspection_id}/decision",
    response_model=DecisionResponse,
    summary="Registrar decisão do operador",
    description=(
        "Permite que um operador autenticado aprove ou reprove uma inspeção. "
        "O campo 'reason' é obrigatório quando decision='REJECTED'. "
        "A decisão pode ser sobrescrita — mas cada decisão gera um registro imutável "
        "no audit trail (tabela inspection_decisions) para fins de rastreabilidade."
    ),
    responses={
        200: {"description": "Decisão registrada com sucesso"},
        401: {"description": "Token de autenticação ausente ou inválido"},
        404: {"description": "Inspeção não encontrada"},
        422: {"description": "Payload inválido ou reason ausente para REJECTED"},
    },
)
def register_decision(
    inspection_id: int,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionResponse:
    repo = InspectionRepository(db)

    # 1. Atualiza o campo decision na inspeção (estado atual — sobrescrevível)
    inspection = repo.update_decision(
        inspection_id=inspection_id,
        decision=payload.decision.value,
        decision_reason=payload.reason,
    )

    if inspection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inspeção {inspection_id} não encontrada.",
        )

    # 2. Grava no audit trail imutável (Sprint 9B.1)
    # Este INSERT é sempre feito, mesmo que a decisão seja a mesma da anterior.
    # Rastreabilidade > eficiência de storage.
    decision_repo = DecisionRepository(db)
    decision_repo.create(
        inspection_id=inspection_id,
        user_id=current_user.id,
        decision=payload.decision.value,
        reason=payload.reason,
    )

    log.info(
        "Decisão registrada: inspection_id=%d decision=%s user_id=%d (%s)",
        inspection_id,
        payload.decision.value,
        current_user.id,
        current_user.email,
    )

    return DecisionResponse.model_validate(inspection)
