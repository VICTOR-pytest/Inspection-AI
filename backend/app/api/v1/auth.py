"""
app/api/v1/auth.py
-------------------
Sprint 9B.1 — Endpoints de autenticação.

POST /auth/login    → login com email + senha, retorna access + refresh tokens
POST /auth/refresh  → renova access token usando refresh token
GET  /auth/me       → retorna dados do usuário autenticado atual
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserRead,
)
from app.services.auth_service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_access_token_expire_seconds,
    verify_password,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login — obter tokens JWT",
    description=(
        "Autentica com e-mail e senha. "
        "Retorna access_token (1h) e refresh_token (7d). "
        "Use o access_token no header Authorization: Bearer <token> em todas as demais requisições."
    ),
    responses={
        200: {"description": "Login bem-sucedido"},
        401: {"description": "Credenciais inválidas"},
        403: {"description": "Conta desativada"},
    },
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    repo = UserRepository(db)
    user = repo.get_by_email(payload.email)

    # Mensagem genérica intencional — não revelar se o email existe ou não
    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="E-mail ou senha inválidos.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if user is None:
        # Executa verify_password com hash fake para evitar timing attack
        # (mesmo custo de CPU que um hash real — o atacante não consegue
        #  distinguir "email não existe" de "senha errada" por tempo de resposta)
        verify_password(payload.password, "$2b$12$GcZkfxR3fV0G1LmT9K8nUeQw8JvX2sY7")
        raise _invalid

    if not verify_password(payload.password, user.password_hash):
        raise _invalid

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conta desativada. Entre em contato com o administrador.",
        )

    access_token  = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id, user.role)

    log.info("Login bem-sucedido: user_id=%d email=%s role=%s", user.id, user.email, user.role)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=get_access_token_expire_seconds(),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Renovar access token",
    description=(
        "Usa o refresh_token para obter um novo access_token sem precisar de login. "
        "O refresh_token deve ser do tipo 'refresh' — access tokens são rejeitados."
    ),
    responses={
        200: {"description": "Token renovado com sucesso"},
        401: {"description": "Refresh token inválido ou expirado"},
    },
)
def refresh_token(
    payload: RefreshRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token inválido ou expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        from jose import JWTError
        token_data = decode_token(payload.refresh_token)
    except Exception:
        raise _invalid

    # Rejeita se não for especificamente um refresh token
    if token_data.get("type") != "refresh":
        raise _invalid

    user_id_str = token_data.get("sub")
    if not user_id_str:
        raise _invalid

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise _invalid

    user = UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise _invalid

    access_token  = create_access_token(user.id, user.role)
    refresh_token_new = create_refresh_token(user.id, user.role)

    log.info("Token renovado: user_id=%d", user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_new,
        expires_in=get_access_token_expire_seconds(),
    )


@router.get(
    "/me",
    response_model=UserRead,
    summary="Dados do usuário autenticado",
    description="Retorna os dados públicos do usuário atual (sem password_hash).",
    responses={
        200: {"description": "Dados do usuário atual"},
        401: {"description": "Token ausente ou inválido"},
    },
)
def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)
