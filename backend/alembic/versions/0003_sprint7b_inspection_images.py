"""sprint 7b — create inspection_images table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inspection_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inspection_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            ["inspections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inspection_images_id", "inspection_images", ["id"])
    op.create_index(
        "ix_inspection_images_inspection_id",
        "inspection_images",
        ["inspection_id"],
        unique=True,  # 1 inspeção → 1 imagem
    )


def downgrade() -> None:
    op.drop_index("ix_inspection_images_inspection_id", table_name="inspection_images")
    op.drop_index("ix_inspection_images_id", table_name="inspection_images")
    op.drop_table("inspection_images")
