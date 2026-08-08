"""
tests/conftest.py
------------------
Sprint 9B.1 — Configuração central de testes.

Provê bypass de autenticação para testes legados (criados antes da Sprint 9B.1).
Os testes legados testam lógica de negócio — não autenticação.
Os testes de autenticação ficam em test_auth.py com seus próprios overrides.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.security import get_current_user, require_admin
from app.models.user import UserRole
from app.main import app


class _FakeUser:
    """
    Objeto leve que imita os atributos de User acessados pelos endpoints.
    Não instancia SQLAlchemy — sem sessão de banco necessária.
    """
    id         = 1
    email      = "test-admin@inspection.ai"
    password_hash = "nao-usado-em-testes"
    full_name  = "Admin de Testes"
    role       = UserRole.ADMIN.value
    is_active  = True
    created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)


_FAKE_ADMIN = _FakeUser()


def _fake_get_current_user():
    return _FAKE_ADMIN


def _fake_require_admin():
    return _FAKE_ADMIN


@pytest.fixture(autouse=True)
def inject_auth_bypass():
    """
    Injeta bypass de autenticação antes de cada teste.

    - Aplica get_current_user e require_admin → retornam admin fake
    - NÃO sobrescreve overrides já definidos (test_auth.py gerencia os seus)
    - Limpa após o teste para isolamento
    """
    already_has_current_user = get_current_user in app.dependency_overrides
    already_has_require_admin = require_admin in app.dependency_overrides

    if not already_has_current_user:
        app.dependency_overrides[get_current_user] = _fake_get_current_user
    if not already_has_require_admin:
        app.dependency_overrides[require_admin] = _fake_require_admin

    yield

    if not already_has_current_user:
        app.dependency_overrides.pop(get_current_user, None)
    if not already_has_require_admin:
        app.dependency_overrides.pop(require_admin, None)
