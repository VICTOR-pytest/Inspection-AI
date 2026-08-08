"""sprint 6 — add confidence, product_name columns and indexes

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inspections",
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "inspections",
        sa.Column("product_name", sa.String(length=255), nullable=True),
    )

    # is_valid e created_at já existiam como colunas (0001), faltava indexá-las
    op.create_index("ix_inspections_is_valid", "inspections", ["is_valid"])
    op.create_index("ix_inspections_created_at", "inspections", ["created_at"])

    # Índice composto para a query mais comum do dashboard:
    # WHERE created_at >= X ORDER BY created_at DESC
    op.create_index(
        "ix_inspections_created_at_valid",
        "inspections",
        ["created_at", "is_valid"],
    )


def downgrade() -> None:
    op.drop_index("ix_inspections_created_at_valid", table_name="inspections")
    op.drop_index("ix_inspections_created_at", table_name="inspections")
    op.drop_index("ix_inspections_is_valid", table_name="inspections")
    op.drop_column("inspections", "product_name")
    op.drop_column("inspections", "confidence")
