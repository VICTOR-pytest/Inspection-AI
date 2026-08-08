"""
app/schemas/auth.py
--------------------
Sprint 9B.1 — Schemas Pydantic para autenticação e gestão de usuários.

LoginRequest      → payload do POST /auth/login
TokenResponse     → resposta com access_token e refresh_token
RefreshRequest    → payload do POST /auth/refresh
UserRead          → representação pública de um usuário (sem password_hash)
UserCreate        → criação de usuário (somente ADMIN)
TokenPayload      → conteúdo decodificado do JWT (uso interno)
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Payload enviado pelo cliente no POST /auth/login."""
    email:    str = Field(..., description="E-mail do usuário")
    password: str = Field(..., min_length=1, description="Senha em plain text")


# ── Tokens ────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    """
    Resposta do endpoint de login e refresh.

    access_token  → token de curta duração (1h) para autenticar requests HTTP e WS
    refresh_token → token de longa duração (7d) para renovar o access_token
    token_type    → sempre "bearer"
    expires_in    → segundos até o access_token expirar (para o frontend calcular renovação)
    """
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int


class RefreshRequest(BaseModel):
    """Payload enviado pelo cliente no POST /auth/refresh."""
    refresh_token: str


# ── Usuário ───────────────────────────────────────────────────────────────────

class UserRead(BaseModel):
    """Representação pública de um usuário — nunca expõe password_hash."""
    id:         int
    email:      str
    full_name:  str
    role:       str
    is_active:  bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    """
    Payload para criação de usuário.
    Apenas ADMIN pode usar este schema.
    """
    email:     str   = Field(..., description="E-mail único do usuário")
    password:  str   = Field(..., min_length=8, description="Senha (mín. 8 caracteres)")
    full_name: str   = Field(..., min_length=1, description="Nome completo")
    role:      str   = Field(default="OPERATOR", description="ADMIN | OPERATOR")


# ── JWT interno ───────────────────────────────────────────────────────────────

class TokenPayload(BaseModel):
    """
    Conteúdo decodificado do JWT.

    sub   → user.id como string (padrão JWT: "subject")
    role  → role do usuário no momento da emissão do token
    type  → "access" | "refresh" (impede uso de refresh token como access)
    exp   → timestamp de expiração (gerenciado pelo python-jose)
    """
    sub:  str
    role: str
    type: str  # "access" | "refresh"
