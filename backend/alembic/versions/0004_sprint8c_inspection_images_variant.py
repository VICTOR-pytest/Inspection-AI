"""sprint 8c — inspection_images: adiciona variant, corrige unique constraint

Problema resolvido:
  Sprint 7B criou inspection_images com UNIQUE(inspection_id), permitindo apenas
  1 imagem por inspeção. Sprint 8B introduziu imagens anotadas (annotated), gerando
  IntegrityError silencioso ao tentar salvar a segunda imagem.

Alterações:
  1. Remove índice unique simples em inspection_id
  2. Adiciona coluna variant VARCHAR(20) NOT NULL DEFAULT 'original'
  3. Atualiza registros existentes para variant='original'
  4. Cria índice não-único em inspection_id (para FK lookups)
  5. Cria índice não-único em variant (para queries por tipo)
  6. Cria UNIQUE(inspection_id, variant) — 1 original + 1 annotated por inspeção

Compatibilidade:
  - Registros existentes recebem variant='original' automaticamente
  - Nenhum dado é perdido
  - downgrade() reverte exatamente ao estado Sprint 7B

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-22 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Remove o índice único antigo (UNIQUE em inspection_id isolado)
    #    Este índice foi criado pelo Sprint 7B e é o responsável pelo bug.
    op.drop_index(
        "ix_inspection_images_inspection_id",
        table_name="inspection_images",
    )

    # 2. Adiciona coluna variant com default 'original'
    #    NOT NULL + server_default garante que todos os registros existentes
    #    recebam o valor 'original' automaticamente — sem UPDATE explícito
    #    (PostgreSQL aplica o DEFAULT para linhas existentes ao adicionar
    #    coluna NOT NULL com server_default).
    op.add_column(
        "inspection_images",
        sa.Column(
            "variant",
            sa.String(20),
            nullable=False,
            server_default="original",
            comment="Tipo da imagem: 'original' (frame capturado) ou 'annotated' (com overlay YOLO)",
        ),
    )

    # 3. Após popular todos os registros, remove o server_default
    #    (boas práticas: server_default só é necessário durante a migration)
    op.alter_column(
        "inspection_images",
        "variant",
        server_default=None,
    )

    # 4. Índice não-único em inspection_id (para FK lookups e joins)
    op.create_index(
        "ix_inspection_images_inspection_id",
        "inspection_images",
        ["inspection_id"],
        unique=False,
    )

    # 5. Índice não-único em variant (para queries tipo "todas as anotadas")
    op.create_index(
        "ix_inspection_images_variant",
        "inspection_images",
        ["variant"],
        unique=False,
    )

    # 6. UNIQUE composto (inspection_id, variant)
    #    Garante: no máximo 1 'original' e 1 'annotated' por inspeção
    op.create_index(
        "uq_inspection_images_inspection_id_variant",
        "inspection_images",
        ["inspection_id", "variant"],
        unique=True,
    )


def downgrade() -> None:
    # Reverte para o estado exato do Sprint 7B:
    # UNIQUE simples em inspection_id, sem coluna variant

    # Remove índices criados nesta migration
    op.drop_index(
        "uq_inspection_images_inspection_id_variant",
        table_name="inspection_images",
    )
    op.drop_index(
        "ix_inspection_images_variant",
        table_name="inspection_images",
    )
    op.drop_index(
        "ix_inspection_images_inspection_id",
        table_name="inspection_images",
    )

    # Remove a coluna variant
    op.drop_column("inspection_images", "variant")

    # Recria o índice unique original do Sprint 7B
    op.create_index(
        "ix_inspection_images_inspection_id",
        "inspection_images",
        ["inspection_id"],
        unique=True,
    )
