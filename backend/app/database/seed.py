"""
Script de seed — popula o banco com produtos e usuários de teste.

Sprint 9B.1: adiciona criação de usuários padrão (admin + operator).

Uso (dentro do diretório backend/):
    python -m app.database.seed

Usuários criados:
  admin@inspection.ai    / admin123    → role ADMIN
  operator@inspection.ai / operator123 → role OPERATOR

IMPORTANTE: Alterar as senhas padrão em ambiente de produção!
"""
import logging

from sqlalchemy.exc import IntegrityError

from app.database.session import SessionLocal
from app.models.product import Product  # noqa: F401 — garante que a tabela existe
from app.models.user import User, UserRole  # noqa: F401

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

SEED_PRODUCTS = [
    {
        "name": "Produto Teste A",
        "barcode": "789123456",
        "expected_weight": 1.00,
        "tolerance": 0.05,   # ±5% → [0.950 – 1.050]
        "is_active": True,
    },
    {
        "name": "Produto Teste B",
        "barcode": "111222333",
        "expected_weight": 0.500,
        "tolerance": 0.10,   # ±10% → [0.450 – 0.550]
        "is_active": True,
    },
    {
        "name": "Produto Teste C (inativo)",
        "barcode": "999888777",
        "expected_weight": 2.00,
        "tolerance": 0.05,
        "is_active": False,
    },
]

# Usuários padrão — ALTERAR SENHAS EM PRODUÇÃO
SEED_USERS = [
    {
        "email": "admin@inspection.ai",
        "password": "admin123",
        "full_name": "Administrador do Sistema",
        "role": UserRole.ADMIN.value,
    },
    {
        "email": "operator@inspection.ai",
        "password": "operator123",
        "full_name": "Operador Padrão",
        "role": UserRole.OPERATOR.value,
    },
]


def _seed_products(db) -> None:
    inserted = 0
    for data in SEED_PRODUCTS:
        existing = db.query(Product).filter(Product.barcode == data["barcode"]).first()
        if existing:
            log.info("Produto '%s' já existe — ignorado.", data["name"])
            continue
        product = Product(**data)
        db.add(product)
        try:
            db.commit()
            log.info("Produto inserido: %s (barcode=%s)", data["name"], data["barcode"])
            inserted += 1
        except IntegrityError:
            db.rollback()
            log.warning("Conflito ao inserir produto '%s' — ignorado.", data["name"])
    log.info("Produtos: %d inserido(s).", inserted)


def _seed_users(db) -> None:
    """
    Cria usuários padrão se ainda não existirem.

    Importa hash_password localmente para evitar dependência circular
    em ambientes onde o módulo de auth ainda não foi inicializado.
    """
    from app.services.auth_service import hash_password
    from datetime import datetime, timezone

    inserted = 0
    for data in SEED_USERS:
        existing = db.query(User).filter(User.email == data["email"].lower()).first()
        if existing:
            log.info("Usuário '%s' já existe — ignorado.", data["email"])
            continue
        now = datetime.now(timezone.utc)
        user = User(
            email=data["email"].lower(),
            password_hash=hash_password(data["password"]),
            full_name=data["full_name"],
            role=data["role"],
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        try:
            db.commit()
            log.info(
                "Usuário inserido: %s (role=%s)",
                data["email"],
                data["role"],
            )
            inserted += 1
        except IntegrityError:
            db.rollback()
            log.warning("Conflito ao inserir usuário '%s' — ignorado.", data["email"])
    log.info("Usuários: %d inserido(s).", inserted)


def run_seed() -> None:
    db = SessionLocal()
    try:
        _seed_products(db)
        _seed_users(db)
        log.info("Seed concluído.")
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
