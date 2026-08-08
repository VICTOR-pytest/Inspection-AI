"""
app/core/security.py
---------------------
Sprint 9B.1 — Dependencies FastAPI de autenticação e autorização.

get_current_user  → extrai e valida JWT do header Authorization: Bearer <token>
                    Retorna o User ativo ou levanta 401/403
require_admin     → exige role=ADMIN, levanta 403 caso contrário
require_operator  → exige role=ADMIN ou OPERATOR (qualquer usuário ativo)

Uso nos endpoints:
  @router.get("/rota-protegida")
  def minha_rota(current_user: User = Depends(get_current_user)):
      ...

  @router.post("/rota-admin")
  def rota_admin(current_user: User = Depends(require_admin)):
      ...

WebSocket:
  Para WebSocket, o token vem via query param ?token=<jwt>
  porque browsers não permitem enviar Authorization header em WebSocket.
  Ver api/v1/ws.py para a implementação.
"""
from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.services.auth_service import decode_token

log = logging.getLogger(__name__)

# Extrator do header Authorization: Bearer <token>
# auto_error=False: retorna None em vez de 401 automático (controlamos o erro)
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency: extrai e valida o JWT do header Authorization.

    Fluxo:
      1. Extrai o token do header Authorization: Bearer <token>
      2. Decodifica e valida a assinatura + expiração
      3. Verifica que é um access token (não refresh)
      4. Busca o usuário no banco pelo sub (user_id)
      5. Verifica que o usuário está ativo

    Levanta HTTPException:
      401 → token ausente, inválido, expirado ou assinatura incorreta
      401 → usuário não encontrado no banco
      403 → usuário existe mas is_active=False (conta desativada)
    """
    _unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token de autenticação inválido ou ausente.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise _unauthorized

    token = credentials.credentials
    try:
        payload = decode_token(token)
    except JWTError as exc:
        log.warning("JWT inválido: %s", exc)
        raise _unauthorized from exc

    # Garante que é access token — refresh token não pode autenticar requests
    if payload.get("type") != "access":
        raise _unauthorized

    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        raise _unauthorized

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise _unauthorized

    user = UserRepository(db).get_by_id(user_id)
    if user is None:
        raise _unauthorized

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conta de usuário desativada.",
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency: exige role=ADMIN.

    Levanta 403 se o usuário autenticado for OPERATOR.
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores.",
        )
    return current_user


def require_operator(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency: exige role=ADMIN ou OPERATOR.

    Na prática: qualquer usuário ativo autenticado.
    Usado para documentar explicitamente a intenção de acesso operacional.
    """
    if current_user.role not in (UserRole.ADMIN.value, UserRole.OPERATOR.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado.",
        )
    return current_user


def decode_websocket_token(token: str, db: Session) -> User:
    """
    Valida token JWT para conexões WebSocket.

    Idêntico ao get_current_user mas aceita o token como string direta
    (não via header HTTP — WebSocket recebe via query param ?token=<jwt>).

    Levanta HTTPException 401/403 nos mesmos cenários que get_current_user.
    O caller (ws.py) deve fechar o WebSocket com código 4001 nesses casos.
    """
    _unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token WebSocket inválido ou ausente.",
    )

    if not token:
        raise _unauthorized

    try:
        payload = decode_token(token)
    except JWTError as exc:
        log.warning("JWT WebSocket inválido: %s", exc)
        raise _unauthorized from exc

    if payload.get("type") != "access":
        raise _unauthorized

    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        raise _unauthorized

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise _unauthorized

    user = UserRepository(db).get_by_id(user_id)
    if user is None:
        raise _unauthorized

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conta de usuário desativada.",
        )

    return user
