"""sprint 9a — inspections: adiciona campos de decisão humana

Contexto:
  Até a Sprint 8C, o sistema tomava decisões automáticas (is_valid = regra de
  peso + barcode). A Sprint 9A introduz o fluxo de decisão do operador humano:
  aprovar ou reprovar uma inspeção com motivo e timestamp de revisão.

Alterações:
  1. Adiciona coluna decision VARCHAR(20) NOT NULL DEFAULT 'PENDING'
     Valores válidos: 'PENDING' | 'APPROVED' | 'REJECTED'
  2. Adiciona coluna decision_reason TEXT NULLABLE
     Preenchida pelo operador ao reprovar (ou opcionalmente ao aprovar)
  3. Adiciona coluna reviewed_at TIMESTAMP NULLABLE
     Preenchida automaticamente pelo servidor no momento da decisão
  4. Cria índice ix_inspections_decision para queries por status

Compatibilidade:
  - Registros existentes recebem decision='PENDING' via server_default
  - Nenhum dado existente é alterado ou perdido
  - downgrade() reverte completamente ao estado Sprint 8C

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-22 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Coluna decision: estado de revisão humana da inspeção
    #    NOT NULL + server_default garante que todos os registros existentes
    #    recebam 'PENDING' automaticamente, sem UPDATE explícito.
    op.add_column(
        "inspections",
        sa.Column(
            "decision",
            sa.String(20),
            nullable=False,
            server_default="PENDING",
            comment="Decisão do operador: PENDING | APPROVED | REJECTED",
        ),
    )

    # Remove server_default após população (boas práticas de migration)
    op.alter_column("inspections", "decision", server_default=None)

    # 2. Coluna decision_reason: motivo textual (obrigatório para REJECTED)
    op.add_column(
        "inspections",
        sa.Column(
            "decision_reason",
            sa.Text,
            nullable=True,
            comment="Motivo da decisão (obrigatório quando REJECTED)",
        ),
    )

    # 3. Coluna reviewed_at: timestamp UTC da revisão
    op.add_column(
        "inspections",
        sa.Column(
            "reviewed_at",
            sa.DateTime,
            nullable=True,
            comment="Timestamp UTC do momento em que o operador registrou a decisão",
        ),
    )

    # 4. Índice em decision para queries de métricas e filtros
    op.create_index(
        "ix_inspections_decision",
        "inspections",
        ["decision"],
        unique=False,
    )


def downgrade() -> None:
    # Reverte ao estado exato da Sprint 8C
    op.drop_index("ix_inspections_decision", table_name="inspections")
    op.drop_column("inspections", "reviewed_at")
    op.drop_column("inspections", "decision_reason")
    op.drop_column("inspections", "decision")
