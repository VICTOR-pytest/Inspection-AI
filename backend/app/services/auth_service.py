"""
app/services/auth_service.py
-----------------------------
Sprint 9B.1 — Serviço de autenticação JWT e hash de senhas.

Responsabilidades:
  - Hash e verificação de senhas via bcrypt (passlib)
  - Criação de access tokens (curta duração: 1h)
  - Criação de refresh tokens (longa duração: 7d)
  - Decodificação e validação de tokens JWT
  - Separação de tipo access/refresh para evitar uso cruzado

Nunca importar FastAPI aqui — este módulo é puro Python, sem dependências HTTP.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# Contexto bcrypt — rounds automáticos, upgrade transparente
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Tipo de token para type hints
TokenType = Literal["access", "refresh"]


# ── Senhas ────────────────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """
    Gera hash bcrypt de uma senha plain text.

    O salt é gerado automaticamente pelo bcrypt a cada chamada —
    duas chamadas com a mesma senha produzem hashes diferentes.
    """
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica se a senha plain text corresponde ao hash armazenado.

    Usa comparação em tempo constante para evitar timing attacks.
    Retorna False (não levanta exceção) se o hash for inválido.
    """
    try:
        return _pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


# ── Tokens JWT ────────────────────────────────────────────────────────────────

def _create_token(
    user_id: int,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    """
    Cria um token JWT assinado com HS256.

    Campos do payload:
      sub  → user_id como string (Subject — padrão JWT RFC 7519)
      role → papel do usuário no momento da emissão
      type → "access" | "refresh" — evita uso cruzado de tokens
      exp  → timestamp de expiração UTC
      iat  → timestamp de emissão UTC
    """
    now = datetime.now(timezone.utc)
    expire = now + expires_delta

    payload = {
        "sub":  str(user_id),
        "role": role,
        "type": token_type,
        "exp":  expire,
        "iat":  now,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, role: str) -> str:
    """
    Cria access token de curta duração.

    Validade: jwt_access_token_expire_minutes (padrão: 60 minutos).
    Usado em: Authorization: Bearer <token> em requests HTTP e WS.
    """
    return _create_token(
        user_id=user_id,
        role=role,
        token_type="access",
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )


def create_refresh_token(user_id: int, role: str) -> str:
    """
    Cria refresh token de longa duração.

    Validade: jwt_refresh_token_expire_minutes (padrão: 7 dias).
    Usado em: POST /auth/refresh para obter novo access token.
    NUNCA deve ser enviado em Authorization: Bearer.
    """
    return _create_token(
        user_id=user_id,
        role=role,
        token_type="refresh",
        expires_delta=timedelta(minutes=settings.jwt_refresh_token_expire_minutes),
    )


def decode_token(token: str) -> dict:
    """
    Decodifica e valida um token JWT.

    Verifica:
      - Assinatura (chave secreta)
      - Expiração (exp claim)
      - Algoritmo (HS256)

    Levanta:
      JWTError (subclasse de Exception) se o token for inválido,
      expirado, com assinatura incorreta ou algoritmo diferente.

    Retorna o payload como dict em caso de sucesso.
    """
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def get_access_token_expire_seconds() -> int:
    """Retorna o tempo de expiração do access token em segundos (para o campo expires_in)."""
    return settings.jwt_access_token_expire_minutes * 60
