"""sprint 10c.1 — fundação multi-linha: production_lines, cameras, inspection_runs

Contexto:
  Sprint 10C.1 prepara o banco de dados para suportar múltiplas linhas de
  produção. Esta migration NÃO altera Workers nem EventBus — apenas cria
  a fundação de dados (models, FKs, constraints).

Alterações:
  1. Cria tabela production_lines
       id, code (UNIQUE), name, description, is_active, created_at, updated_at
  2. Cria tabela cameras
       id, production_line_id (FK), name, source, resolution, fps, enabled,
       created_at
  3. Cria tabela inspection_runs
       id, production_line_id (FK), product_id (FK), started_at, finished_at,
       operator, status
     + índice único PARCIAL garantindo no máximo um run ATIVO
       (finished_at IS NULL) por linha:
         ix_inspection_runs_active_line_unique
         ON inspection_runs (production_line_id) WHERE finished_at IS NULL
  4. Adiciona em inspections (todas NULLABLE — compatibilidade retroativa):
       line_id            → FK production_lines.id (ON DELETE SET NULL)
       camera_id          → FK cameras.id (ON DELETE SET NULL)
       inspection_run_id  → FK inspection_runs.id (ON DELETE SET NULL)
  5. Seed: cria a linha padrão "L01" / "Linha 01"
  6. Backfill: todas as inspeções existentes (line_id IS NULL) são migradas
     para a linha padrão L01. camera_id e inspection_run_id permanecem NULL
     para dados históricos, pois não é possível inferir retroativamente
     qual câmera/run gerou cada registro antigo.

Compatibilidade:
  - Nenhuma tabela ou coluna existente é removida ou tem seu tipo alterado.
  - Todas as novas colunas em `inspections` são NULLABLE.
  - O backfill é idempotente: usa INSERT ... ON CONFLICT DO NOTHING para a
    linha padrão e só atualiza inspections cujo line_id ainda é NULL.
  - downgrade() reverte completamente ao estado da Sprint 9B.1 (0006),
    incluindo a remoção das colunas adicionadas em `inspections`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_LINE_CODE = "L01"
DEFAULT_LINE_NAME = "Linha 01"


def upgrade() -> None:
    # ── 1. Tabela production_lines ─────────────────────────────────────────
    op.create_table(
        "production_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "code",
            sa.String(50),
            nullable=False,
            comment="Identificador curto e único da linha (ex: 'L01')",
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="false = linha desativada (soft-delete)",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_production_lines_id",   "production_lines", ["id"],   unique=False)
    op.create_index("ix_production_lines_code", "production_lines", ["code"], unique=True)

    # ── 2. Tabela cameras ───────────────────────────────────────────────────
    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("production_line_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "source",
            sa.String(255),
            nullable=False,
            comment="Índice de webcam, URL RTSP, path de vídeo etc.",
        ),
        sa.Column("resolution", sa.String(20), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["production_line_id"],
            ["production_lines.id"],
            ondelete="CASCADE",
            name="fk_cameras_production_line_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cameras_id",                  "cameras", ["id"])
    op.create_index("ix_cameras_production_line_id",  "cameras", ["production_line_id"])

    # ── 3. Tabela inspection_runs ───────────────────────────────────────────
    op.create_table(
        "inspection_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("production_line_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column(
            "finished_at",
            sa.DateTime(),
            nullable=True,
            comment="NULL = run ainda ativo",
        ),
        sa.Column("operator", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="ACTIVE",
            comment="ACTIVE | FINISHED",
        ),
        sa.ForeignKeyConstraint(
            ["production_line_id"],
            ["production_lines.id"],
            ondelete="CASCADE",
            name="fk_inspection_runs_production_line_id",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="SET NULL",
            name="fk_inspection_runs_product_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inspection_runs_id",                 "inspection_runs", ["id"])
    op.create_index("ix_inspection_runs_production_line_id", "inspection_runs", ["production_line_id"])
    op.create_index("ix_inspection_runs_status",             "inspection_runs", ["status"])

    # Regra de negócio no banco: no máximo UM run ativo (finished_at IS NULL)
    # por linha de produção. Índice único PARCIAL — só se aplica a linhas
    # onde finished_at é NULL, então runs finalizados não conflitam entre si.
    op.create_index(
        "ix_inspection_runs_active_line_unique",
        "inspection_runs",
        ["production_line_id"],
        unique=True,
        postgresql_where=sa.text("finished_at IS NULL"),
    )

    # ── 4. Novas colunas em inspections (todas NULLABLE) ───────────────────
    op.add_column("inspections", sa.Column("line_id", sa.Integer(), nullable=True))
    op.add_column("inspections", sa.Column("camera_id", sa.Integer(), nullable=True))
    op.add_column("inspections", sa.Column("inspection_run_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_inspections_line_id",
        "inspections",
        "production_lines",
        ["line_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inspections_camera_id",
        "inspections",
        "cameras",
        ["camera_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inspections_inspection_run_id",
        "inspections",
        "inspection_runs",
        ["inspection_run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_inspections_line_id",           "inspections", ["line_id"])
    op.create_index("ix_inspections_inspection_run_id", "inspections", ["inspection_run_id"])

    # ── 5. Seed: linha padrão L01 (idempotente) ────────────────────────────
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO production_lines (code, name, description, is_active, created_at, updated_at)
            VALUES (:code, :name, :description, true, now(), now())
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {
            "code": DEFAULT_LINE_CODE,
            "name": DEFAULT_LINE_NAME,
            "description": "Linha padrão criada automaticamente na migration 0007 "
                            "(Sprint 10C.1) para compatibilidade retroativa.",
        },
    )

    # ── 6. Backfill: inspeções antigas → linha padrão L01 ──────────────────
    conn.execute(
        sa.text(
            """
            UPDATE inspections
            SET line_id = (SELECT id FROM production_lines WHERE code = :code)
            WHERE line_id IS NULL
            """
        ),
        {"code": DEFAULT_LINE_CODE},
    )


def downgrade() -> None:
    # Reverte na ordem inversa — constraints antes das tabelas
    op.drop_index("ix_inspections_inspection_run_id", table_name="inspections")
    op.drop_index("ix_inspections_line_id",            table_name="inspections")

    op.drop_constraint("fk_inspections_inspection_run_id", "inspections", type_="foreignkey")
    op.drop_constraint("fk_inspections_camera_id",          "inspections", type_="foreignkey")
    op.drop_constraint("fk_inspections_line_id",            "inspections", type_="foreignkey")

    op.drop_column("inspections", "inspection_run_id")
    op.drop_column("inspections", "camera_id")
    op.drop_column("inspections", "line_id")

    op.drop_index("ix_inspection_runs_active_line_unique", table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_status",             table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_production_line_id", table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_id",                 table_name="inspection_runs")
    op.drop_table("inspection_runs")

    op.drop_index("ix_cameras_production_line_id", table_name="cameras")
    op.drop_index("ix_cameras_id",                 table_name="cameras")
    op.drop_table("cameras")

    op.drop_index("ix_production_lines_code", table_name="production_lines")
    op.drop_index("ix_production_lines_id",   table_name="production_lines")
    op.drop_table("production_lines")
