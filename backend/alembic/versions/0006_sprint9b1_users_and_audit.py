"""sprint 9b1 — autenticação: tabelas users e inspection_decisions + índices compostos

Contexto:
  Sprint 9B.1 introduz autenticação JWT com roles (ADMIN/OPERATOR) e
  audit trail imutável de decisões humanas.

Alterações:
  1. Cria tabela users
       id, email (UNIQUE), password_hash, full_name, role, is_active,
       created_at, updated_at
  2. Cria tabela inspection_decisions (audit trail — APPEND-ONLY)
       id, inspection_id (FK), user_id (FK), decision, reason, created_at
  3. Índice composto de performance em inspections(is_valid, created_at)
       Elimina full table scan nos filtros mais comuns do dashboard
  4. Índice composto em inspections(decision, created_at)
       Acelera queries de métricas de decisão humana

Compatibilidade:
  - Nenhuma tabela existente é alterada
  - Nenhum dado existente é perdido
  - downgrade() reverte completamente ao estado Sprint 9A

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-23 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Tabela users ────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "email",
            sa.String(255),
            nullable=False,
            comment="E-mail único usado como identificador de login",
        ),
        sa.Column(
            "password_hash",
            sa.String(255),
            nullable=False,
            comment="Hash bcrypt da senha",
        ),
        sa.Column(
            "full_name",
            sa.String(255),
            nullable=False,
            comment="Nome completo do operador ou administrador",
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default="OPERATOR",
            comment="Papel: ADMIN | OPERATOR",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="false = conta desativada (soft-delete)",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Índice primário (PK) já é criado automaticamente
    # Índice no email — UNIQUE para garantir unicidade e acelerar lookup no login
    op.create_index("ix_users_id",    "users", ["id"],    unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── 2. Tabela inspection_decisions (audit trail) ───────────────────────────
    op.create_table(
        "inspection_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "inspection_id",
            sa.Integer(),
            nullable=False,
            comment="FK para a inspeção sobre a qual foi tomada a decisão",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            comment="FK para o operador que tomou a decisão",
        ),
        sa.Column(
            "decision",
            sa.String(20),
            nullable=False,
            comment="Decisão: APPROVED | REJECTED | PENDING",
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=True,
            comment="Motivo da decisão — obrigatório quando REJECTED",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            comment="Timestamp UTC imutável",
        ),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            ["inspections.id"],
            ondelete="CASCADE",
            name="fk_inspection_decisions_inspection_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_inspection_decisions_user_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inspection_decisions_id",            "inspection_decisions", ["id"])
    op.create_index("ix_inspection_decisions_inspection_id", "inspection_decisions", ["inspection_id"])
    op.create_index("ix_inspection_decisions_user_id",       "inspection_decisions", ["user_id"])

    # ── 3. Índice composto de performance em inspections ──────────────────────
    # Elimina full table scan nos filtros mais comuns:
    #   GET /api/v1/inspections?valid=false           → (is_valid, created_at)
    #   GET /api/v1/inspections?date_from=...         → (created_at)
    #   GET /api/v1/metrics / dashboard               → (is_valid) isolado
    op.create_index(
        "ix_inspections_is_valid_created_at",
        "inspections",
        ["is_valid", "created_at"],
        unique=False,
    )

    # ── 4. Índice composto para queries de decisão humana ────────────────────
    # Acelera: SELECT COUNT(*) WHERE decision='APPROVED'
    # E queries filtradas por decision + created_at (relatórios por período)
    op.create_index(
        "ix_inspections_decision_created_at",
        "inspections",
        ["decision", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    # Reverte na ordem inversa — constraints antes das tabelas
    op.drop_index("ix_inspections_decision_created_at",  table_name="inspections")
    op.drop_index("ix_inspections_is_valid_created_at",  table_name="inspections")
    op.drop_index("ix_inspection_decisions_user_id",       table_name="inspection_decisions")
    op.drop_index("ix_inspection_decisions_inspection_id", table_name="inspection_decisions")
    op.drop_index("ix_inspection_decisions_id",            table_name="inspection_decisions")
    op.drop_table("inspection_decisions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id",    table_name="users")
    op.drop_table("users")
