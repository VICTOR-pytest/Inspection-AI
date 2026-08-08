"""
app/repositories/user_repository.py
-------------------------------------
Sprint 9B.1 — CRUD de usuários no banco de dados.

Métodos:
  get_by_id(user_id)     → busca por PK
  get_by_email(email)    → busca por email único (login)
  create(data)           → cria usuário com hash de senha
  list_all()             → lista todos (apenas ADMIN)
  deactivate(user_id)    → soft-delete: is_active=False
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.services.auth_service import hash_password


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        """Busca usuário por ID primário."""
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, email: str) -> User | None:
        """
        Busca usuário por e-mail.

        Case-sensitive — e-mail deve ser normalizado para lowercase
        antes de chamar este método (responsabilidade do caller).
        """
        return self.db.query(User).filter(User.email == email.lower()).first()

    def create(
        self,
        email: str,
        password: str,
        full_name: str,
        role: str = UserRole.OPERATOR.value,
    ) -> User:
        """
        Cria novo usuário com senha hasheada.

        O e-mail é normalizado para lowercase antes de persistir.
        Levanta IntegrityError se o e-mail já existir (unique constraint).
        """
        user = User(
            email=email.lower(),
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def list_all(self) -> list[User]:
        """Lista todos os usuários ordenados por ID."""
        return self.db.query(User).order_by(User.id).all()

    def deactivate(self, user_id: int) -> User | None:
        """
        Desativa um usuário (soft-delete).

        Retorna o usuário atualizado ou None se não encontrado.
        Usuários desativados não conseguem fazer login.
        """
        user = self.get_by_id(user_id)
        if user is None:
            return None
        user.is_active = False
        user.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        return user

    def email_exists(self, email: str) -> bool:
        """Verifica se um e-mail já está cadastrado."""
        return self.get_by_email(email) is not None
