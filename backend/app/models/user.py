"""
app/models/user.py
------------------
Sprint 9B.1 — Model SQLAlchemy para a tabela users.

Campos:
  id            → PK auto-incremento
  email         → único, usado como identificador de login
  password_hash → hash bcrypt da senha (nunca a senha em plain text)
  full_name     → nome completo do operador/administrador
  role          → "ADMIN" | "OPERATOR"
  is_active     → soft-delete: false desativa o acesso sem perder histórico
  created_at    → timestamp UTC de criação
  updated_at    → timestamp UTC da última atualização (auto-update)

Roles:
  ADMIN    → acesso completo, incluindo criação de produtos e configurações
  OPERATOR → acesso de operação: visualizar, aprovar e reprovar inspeções
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class UserRole(str, Enum):
    """
    Papéis de usuário no sistema.

    Herda de str para serialização JSON automática pelo Pydantic.
    """
    ADMIN    = "ADMIN"
    OPERATOR = "OPERATOR"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="E-mail único usado como identificador de login",
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Hash bcrypt da senha — nunca armazenar plain text",
    )

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Nome completo do operador ou administrador",
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=UserRole.OPERATOR.value,
        comment="Papel: ADMIN | OPERATOR",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="false = conta desativada (soft-delete)",
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relacionamento com o audit trail de decisões
    decisions: Mapped[list["InspectionDecision"]] = relationship(  # noqa: F821
        "InspectionDecision",
        back_populates="user",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return (
            f"<User id={self.id} email={self.email!r} "
            f"role={self.role} active={self.is_active}>"
        )
