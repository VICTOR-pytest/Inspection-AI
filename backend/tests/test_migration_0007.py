"""
tests/test_migration_0007.py
-------------------------------
Sprint 10C.1 — Testes de integração da migration 0007 contra PostgreSQL real.

Diferente dos demais testes do projeto (que usam SQLite em memória para
velocidade e isolamento), estes testes validam comportamentos que SQLite
não reproduz fielmente:
  - Índice único PARCIAL (postgresql_where) que garante "um run ativo por
    linha" a nível de banco.
  - Foreign key enforcement real.
  - O resultado efetivo do backfill de dados feito pela migration.

Requer PostgreSQL acessível via app.core.config.settings.database_url
(mesma variável usada pela aplicação/Docker). Se a conexão falhar, os
testes são pulados (skip) — não quebram um ambiente sem Postgres
disponível, seguindo o princípio de não travar o CI padrão do projeto.

Cada teste roda dentro de uma transação com ROLLBACK automático ao final,
então nenhum dado de teste persiste no banco real.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

try:
    _engine = create_engine(settings.database_url)
    with _engine.connect() as _conn:
        _conn.execute(text("SELECT 1"))
    POSTGRES_AVAILABLE = True
except OperationalError:
    POSTGRES_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not POSTGRES_AVAILABLE,
    reason="PostgreSQL não disponível em settings.database_url — pulando testes de migration.",
)


@pytest.fixture()
def pg_session():
    """Sessão transacional — todo o teste roda em uma transação com ROLLBACK."""
    connection = _engine.connect()
    trans = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


class TestMigrationSchema:

    def test_tabelas_novas_existem(self):
        insp = inspect(_engine)
        tables = insp.get_table_names()
        assert "production_lines" in tables
        assert "cameras" in tables
        assert "inspection_runs" in tables

    def test_inspections_tem_novas_colunas_nullable(self):
        insp = inspect(_engine)
        cols = {c["name"]: c for c in insp.get_columns("inspections")}
        for col_name in ("line_id", "camera_id", "inspection_run_id"):
            assert col_name in cols
            assert cols[col_name]["nullable"] is True

    def test_production_lines_code_e_unique(self):
        insp = inspect(_engine)
        unique_constraints = insp.get_indexes("production_lines")
        assert any(
            "code" in idx["column_names"] and idx["unique"]
            for idx in unique_constraints
        )

    def test_indice_unico_parcial_de_run_ativo_existe(self):
        insp = inspect(_engine)
        indexes = insp.get_indexes("inspection_runs")
        assert any(
            idx["name"] == "ix_inspection_runs_active_line_unique"
            for idx in indexes
        )


class TestSeedELinhaPadrao:

    def test_linha_padrao_l01_existe(self, pg_session):
        row = pg_session.execute(
            text("SELECT code, name FROM production_lines WHERE code = 'L01'")
        ).fetchone()
        assert row is not None
        assert row[0] == "L01"

    def test_linha_padrao_e_idempotente_em_reexecucoes(self, pg_session):
        """A migration usa ON CONFLICT DO NOTHING — não deve duplicar L01."""
        count = pg_session.execute(
            text("SELECT COUNT(*) FROM production_lines WHERE code = 'L01'")
        ).scalar()
        assert count == 1


class TestBackfillDeInspecoesAntigas:
    """
    Nota de design: o banco de dev (settings.database_url) é compartilhado
    com outros arquivos de teste do projeto que já existiam antes desta
    sprint (ex.: test_inspection_service.py, test_yolo_detector.py) e
    inserem registros reais nele sem passar por override de get_db. Por
    isso, não é seguro afirmar "toda inspeção no banco tem line_id
    preenchido" — inspeções criadas por outros testes DEPOIS da migration
    0007 legitimamente têm line_id NULL (o backfill só migra o que já
    existia no momento da migration; não é um trigger contínuo).

    Para testar a lógica de backfill de forma isolada e determinística,
    replicamos exatamente a instrução SQL da migration (UPDATE ...
    WHERE line_id IS NULL) contra uma tabela TEMPORARY criada dentro da
    própria transação de teste — que é descartada no rollback do fixture
    pg_session, sem qualquer efeito no banco compartilhado.
    """

    def test_logica_de_backfill_migra_registro_legado_para_l01(self, pg_session):
        pg_session.execute(text(
            "CREATE TEMP TABLE tmp_inspections_backfill "
            "(id serial PRIMARY KEY, barcode text, line_id integer) "
            "ON COMMIT DROP"
        ))
        pg_session.execute(text(
            "INSERT INTO tmp_inspections_backfill (barcode, line_id) "
            "VALUES ('LEGACY-SIM', NULL)"
        ))

        # Mesma instrução usada em upgrade() na migration 0007
        pg_session.execute(text(
            "UPDATE tmp_inspections_backfill "
            "SET line_id = (SELECT id FROM production_lines WHERE code = 'L01') "
            "WHERE line_id IS NULL"
        ))

        row = pg_session.execute(
            text("SELECT line_id FROM tmp_inspections_backfill WHERE barcode = 'LEGACY-SIM'")
        ).fetchone()
        l01_id = pg_session.execute(
            text("SELECT id FROM production_lines WHERE code = 'L01'")
        ).scalar()
        assert row[0] == l01_id

    def test_logica_de_backfill_nao_sobrescreve_line_id_ja_preenchido(self, pg_session):
        """O backfill só afeta WHERE line_id IS NULL — não deve sobrescrever."""
        other_line_id = pg_session.execute(
            text(
                "INSERT INTO production_lines (code, name, is_active, created_at, updated_at) "
                "VALUES ('MIGTEST-L3', 'Outra Linha', true, now(), now()) RETURNING id"
            )
        ).scalar()

        pg_session.execute(text(
            "CREATE TEMP TABLE tmp_inspections_backfill2 "
            "(id serial PRIMARY KEY, barcode text, line_id integer) "
            "ON COMMIT DROP"
        ))
        pg_session.execute(
            text(
                "INSERT INTO tmp_inspections_backfill2 (barcode, line_id) "
                "VALUES ('JA-TEM-LINHA', :lid)"
            ),
            {"lid": other_line_id},
        )

        pg_session.execute(text(
            "UPDATE tmp_inspections_backfill2 "
            "SET line_id = (SELECT id FROM production_lines WHERE code = 'L01') "
            "WHERE line_id IS NULL"
        ))

        row = pg_session.execute(
            text("SELECT line_id FROM tmp_inspections_backfill2 WHERE barcode = 'JA-TEM-LINHA'")
        ).fetchone()
        assert row[0] == other_line_id

    def test_nova_inspecao_real_sem_line_id_nao_e_afetada_retroativamente(self, pg_session):
        """
        Confirma, na tabela real (dentro da transação com rollback), que
        inserir uma inspeção sem line_id simplesmente a deixa NULL — o
        backfill não é reexecutado automaticamente fora da migration.
        """
        pg_session.execute(
            text(
                "INSERT INTO inspections "
                "(barcode, weight, is_valid, confidence, decision, created_at) "
                "VALUES ('MIGTEST001', 100.0, true, 0.9, 'APPROVED', now())"
            )
        )
        row = pg_session.execute(
            text("SELECT line_id FROM inspections WHERE barcode = 'MIGTEST001'")
        ).fetchone()
        assert row[0] is None


class TestIntegridadeReferencialReal:

    def test_camera_com_linha_inexistente_falha_fk(self, pg_session):
        with pytest.raises(IntegrityError):
            pg_session.execute(
                text(
                    "INSERT INTO cameras (production_line_id, name, source, enabled, created_at) "
                    "VALUES (999999, 'Cam órfã', '0', true, now())"
                )
            )
            pg_session.flush()

    def test_run_com_linha_inexistente_falha_fk(self, pg_session):
        with pytest.raises(IntegrityError):
            pg_session.execute(
                text(
                    "INSERT INTO inspection_runs (production_line_id, started_at, status) "
                    "VALUES (999999, now(), 'ACTIVE')"
                )
            )
            pg_session.flush()


class TestIndiceUnicoParcialRunAtivo:

    def test_dois_runs_ativos_na_mesma_linha_viola_indice_unico(self, pg_session):
        line_id = pg_session.execute(
            text(
                "INSERT INTO production_lines (code, name, is_active, created_at, updated_at) "
                "VALUES ('MIGTEST-L1', 'Linha Teste Migration', true, now(), now()) "
                "RETURNING id"
            )
        ).scalar()

        pg_session.execute(
            text(
                "INSERT INTO inspection_runs (production_line_id, started_at, status) "
                "VALUES (:lid, now(), 'ACTIVE')"
            ),
            {"lid": line_id},
        )
        pg_session.flush()

        with pytest.raises(IntegrityError):
            pg_session.execute(
                text(
                    "INSERT INTO inspection_runs (production_line_id, started_at, status) "
                    "VALUES (:lid, now(), 'ACTIVE')"
                ),
                {"lid": line_id},
            )
            pg_session.flush()

    def test_dois_runs_finalizados_na_mesma_linha_nao_conflitam(self, pg_session):
        """
        O índice é PARCIAL (WHERE finished_at IS NULL) — múltiplos runs
        FINALIZADOS na mesma linha devem conviver sem conflito.
        """
        line_id = pg_session.execute(
            text(
                "INSERT INTO production_lines (code, name, is_active, created_at, updated_at) "
                "VALUES ('MIGTEST-L2', 'Linha Teste Migration 2', true, now(), now()) "
                "RETURNING id"
            )
        ).scalar()

        for _ in range(2):
            pg_session.execute(
                text(
                    "INSERT INTO inspection_runs "
                    "(production_line_id, started_at, finished_at, status) "
                    "VALUES (:lid, now(), now(), 'FINISHED')"
                ),
                {"lid": line_id},
            )
        pg_session.flush()

        count = pg_session.execute(
            text("SELECT COUNT(*) FROM inspection_runs WHERE production_line_id = :lid"),
            {"lid": line_id},
        ).scalar()
        assert count == 2
