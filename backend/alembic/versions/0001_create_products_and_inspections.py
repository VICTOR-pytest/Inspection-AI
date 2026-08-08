"""create products and inspections tables

Revision ID: 0001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("barcode", sa.String(length=100), nullable=False),
        sa.Column("expected_weight", sa.Float(), nullable=False),
        sa.Column("tolerance", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_id", "products", ["id"])
    op.create_index("ix_products_barcode", "products", ["barcode"], unique=True)

    op.create_table(
        "inspections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barcode", sa.String(length=100), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inspections_id", "inspections", ["id"])
    op.create_index("ix_inspections_barcode", "inspections", ["barcode"])


def downgrade() -> None:
    op.drop_index("ix_inspections_barcode", table_name="inspections")
    op.drop_index("ix_inspections_id", table_name="inspections")
    op.drop_table("inspections")
    op.drop_index("ix_products_barcode", table_name="products")
    op.drop_index("ix_products_id", table_name="products")
    op.drop_table("products")
