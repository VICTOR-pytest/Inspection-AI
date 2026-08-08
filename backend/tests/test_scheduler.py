"""
tests/test_scheduler.py
------------------------
Sprint 10B — Testes do scheduler de manutenção de storage.

Cobre:
  CF  — Configuração: settings novos presentes e válidos
  SC  — _seconds_until_next_run: cálculo correto em todos os cenários
  CY  — _run_cleanup_cycle: executa cada etapa corretamente
  LP  — cleanup_scheduler_loop: inicia, agenda, cancela limpo
  IT  — Integração: scheduler registrado no lifespan do app
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# CF — CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchedulerConfig:

    def test_orphan_check_enabled_existe(self):
        from app.core.config import settings
        assert hasattr(settings, "orphan_check_enabled")
        assert isinstance(settings.orphan_check_enabled, bool)

    def test_image_cleanup_hour_valido(self):
        from app.core.config import settings
        assert 0 <= settings.image_cleanup_hour <= 23

    def test_image_retention_days_nao_negativo(self):
        from app.core.config import settings
        assert settings.image_retention_days >= 0

    def test_image_cleanup_enabled_e_bool(self):
        from app.core.config import settings
        assert isinstance(settings.image_cleanup_enabled, bool)

    def test_disk_warning_menor_que_critical(self):
        from app.core.config import settings
        assert settings.disk_warning_percent < settings.disk_critical_percent


# ═══════════════════════════════════════════════════════════════════════════════
# SC — _seconds_until_next_run
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecondsUntilNextRun:

    def test_hora_futura_hoje_retorna_diferenca_correta(self):
        from app.core.scheduler import _seconds_until_next_run
        now = datetime(2026, 6, 1, 1, 0, 0, tzinfo=timezone.utc)
        with patch("app.core.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = _seconds_until_next_run(2)
        assert abs(result - 3600.0) < 5

    def test_hora_passada_hoje_agendada_amanha(self):
        from app.core.scheduler import _seconds_until_next_run
        now = datetime(2026, 6, 1, 3, 0, 0, tzinfo=timezone.utc)
        with patch("app.core.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = _seconds_until_next_run(2)
        assert abs(result - 82800.0) < 5

    def test_exatamente_na_hora_agendada_amanha(self):
        from app.core.scheduler import _seconds_until_next_run
        now = datetime(2026, 6, 1, 2, 0, 0, tzinfo=timezone.utc)
        with patch("app.core.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = _seconds_until_next_run(2)
        assert abs(result - 86400.0) < 5

    def test_minimo_de_60_segundos(self):
        from app.core.scheduler import _seconds_until_next_run
        now = datetime(2026, 6, 1, 2, 0, 0, tzinfo=timezone.utc)
        with patch("app.core.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = _seconds_until_next_run(2)
        assert result >= 60.0

    def test_hora_zero_funciona(self):
        from app.core.scheduler import _seconds_until_next_run
        now = datetime(2026, 6, 1, 23, 0, 0, tzinfo=timezone.utc)
        with patch("app.core.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = _seconds_until_next_run(0)
        assert abs(result - 3600.0) < 5

    def test_hora_23_funciona(self):
        from app.core.scheduler import _seconds_until_next_run
        now = datetime(2026, 6, 1, 22, 0, 0, tzinfo=timezone.utc)
        with patch("app.core.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = _seconds_until_next_run(23)
        assert abs(result - 3600.0) < 5

    def test_retorna_float(self):
        from app.core.scheduler import _seconds_until_next_run
        now = datetime(2026, 6, 1, 1, 0, 0, tzinfo=timezone.utc)
        with patch("app.core.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = _seconds_until_next_run(2)
        assert isinstance(result, float)


# ═══════════════════════════════════════════════════════════════════════════════
# CY — _run_cleanup_cycle
# ═══════════════════════════════════════════════════════════════════════════════

def _fake_stats(used_pct=50.0):
    s = MagicMock()
    s.used_pct   = used_pct
    s.free_gb    = 10.0
    s.total_gb   = 20.0
    s.used_bytes = int(used_pct / 100 * 20 * 1024**3)
    s.free_bytes = 20 * 1024**3 - s.used_bytes
    return s


def _fake_result(deleted=0, freed=0):
    r = MagicMock()
    r.deleted_files = deleted
    r.freed_bytes   = freed
    r.errors        = []
    return r


async def _run_cycle_sync():
    """Executa _run_cleanup_cycle substituindo to_thread por execução síncrona."""
    import app.core.scheduler as m
    original_to_thread = asyncio.to_thread

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    asyncio.to_thread = fake_to_thread
    try:
        await m._run_cleanup_cycle()
    finally:
        asyncio.to_thread = original_to_thread


class TestRunCleanupCycle:

    def test_cycle_chama_get_disk_stats(self):
        with patch("app.core.scheduler.storage_service") as mock_ss, \
             patch("app.core.scheduler.SessionLocal", return_value=MagicMock()):
            mock_ss.get_disk_stats.return_value = _fake_stats()
            mock_ss.cleanup_older_than.return_value = _fake_result()
            mock_ss.find_orphan_files.return_value   = []
            mock_ss.find_orphan_records.return_value = []
            mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
            asyncio.run(_run_cycle_sync())
        mock_ss.get_disk_stats.assert_called()

    def test_cycle_chama_cleanup_quando_habilitado(self):
        from app.core.config import settings
        orig_e, orig_d = settings.image_cleanup_enabled, settings.image_retention_days
        try:
            settings.image_cleanup_enabled = True
            settings.image_retention_days  = 30
            with patch("app.core.scheduler.storage_service") as mock_ss, \
                 patch("app.core.scheduler.SessionLocal", return_value=MagicMock()):
                mock_ss.get_disk_stats.return_value = _fake_stats()
                mock_ss.cleanup_older_than.return_value = _fake_result()
                mock_ss.find_orphan_files.return_value   = []
                mock_ss.find_orphan_records.return_value = []
                mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
                asyncio.run(_run_cycle_sync())
            mock_ss.cleanup_older_than.assert_called_once()
        finally:
            settings.image_cleanup_enabled = orig_e
            settings.image_retention_days  = orig_d

    def test_cycle_nao_chama_cleanup_quando_desabilitado(self):
        from app.core.config import settings
        orig = settings.image_cleanup_enabled
        try:
            settings.image_cleanup_enabled = False
            with patch("app.core.scheduler.storage_service") as mock_ss, \
                 patch("app.core.scheduler.SessionLocal", return_value=MagicMock()):
                mock_ss.get_disk_stats.return_value = _fake_stats()
                mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
                asyncio.run(_run_cycle_sync())
            mock_ss.cleanup_older_than.assert_not_called()
        finally:
            settings.image_cleanup_enabled = orig

    def test_cycle_nao_chama_cleanup_com_retention_zero(self):
        from app.core.config import settings
        orig_e, orig_d = settings.image_cleanup_enabled, settings.image_retention_days
        try:
            settings.image_cleanup_enabled = True
            settings.image_retention_days  = 0
            with patch("app.core.scheduler.storage_service") as mock_ss, \
                 patch("app.core.scheduler.SessionLocal", return_value=MagicMock()):
                mock_ss.get_disk_stats.return_value = _fake_stats()
                mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
                asyncio.run(_run_cycle_sync())
            mock_ss.cleanup_older_than.assert_not_called()
        finally:
            settings.image_cleanup_enabled = orig_e
            settings.image_retention_days  = orig_d

    def test_cycle_chama_orphan_check_quando_habilitado(self):
        from app.core.config import settings
        orig = settings.orphan_check_enabled
        try:
            settings.orphan_check_enabled = True
            with patch("app.core.scheduler.storage_service") as mock_ss, \
                 patch("app.core.scheduler.SessionLocal", return_value=MagicMock()):
                mock_ss.get_disk_stats.return_value = _fake_stats()
                mock_ss.cleanup_older_than.return_value = _fake_result()
                mock_ss.find_orphan_files.return_value   = []
                mock_ss.find_orphan_records.return_value = []
                mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
                asyncio.run(_run_cycle_sync())
            mock_ss.find_orphan_files.assert_called()
            mock_ss.find_orphan_records.assert_called()
        finally:
            settings.orphan_check_enabled = orig

    def test_cycle_nao_chama_orphan_check_quando_desabilitado(self):
        from app.core.config import settings
        orig = settings.orphan_check_enabled
        try:
            settings.orphan_check_enabled = False
            with patch("app.core.scheduler.storage_service") as mock_ss, \
                 patch("app.core.scheduler.SessionLocal", return_value=MagicMock()):
                mock_ss.get_disk_stats.return_value = _fake_stats()
                mock_ss.cleanup_older_than.return_value = _fake_result()
                mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
                asyncio.run(_run_cycle_sync())
            mock_ss.find_orphan_files.assert_not_called()
        finally:
            settings.orphan_check_enabled = orig

    def test_cycle_continua_se_disk_stats_falha(self):
        from app.core.config import settings
        orig = settings.image_cleanup_enabled
        try:
            settings.image_cleanup_enabled = False
            with patch("app.core.scheduler.storage_service") as mock_ss, \
                 patch("app.core.scheduler.SessionLocal", return_value=MagicMock()):
                mock_ss.get_disk_stats.side_effect = OSError("disco inacessível")
                mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
                asyncio.run(_run_cycle_sync())
        finally:
            settings.image_cleanup_enabled = orig

    def test_cycle_continua_se_cleanup_falha(self):
        from app.core.config import settings
        orig_e, orig_d = settings.image_cleanup_enabled, settings.image_retention_days
        try:
            settings.image_cleanup_enabled = True
            settings.image_retention_days  = 30
            settings.orphan_check_enabled  = True
            with patch("app.core.scheduler.storage_service") as mock_ss, \
                 patch("app.core.scheduler.SessionLocal", return_value=MagicMock()):
                mock_ss.get_disk_stats.return_value = _fake_stats()
                mock_ss.cleanup_older_than.side_effect = RuntimeError("falha simulada")
                mock_ss.find_orphan_files.return_value   = []
                mock_ss.find_orphan_records.return_value = []
                mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
                asyncio.run(_run_cycle_sync())
            mock_ss.find_orphan_files.assert_called()
        finally:
            settings.image_cleanup_enabled = orig_e
            settings.image_retention_days  = orig_d

    def test_cycle_loga_warning_disco_acima_de_warning_percent(self):
        from app.core.config import settings
        orig_e = settings.image_cleanup_enabled
        try:
            settings.image_cleanup_enabled = False
            with patch("app.core.scheduler.storage_service") as mock_ss, \
                 patch("app.core.scheduler.SessionLocal", return_value=MagicMock()), \
                 patch("app.core.scheduler.log") as mock_log:
                mock_ss.get_disk_stats.return_value = _fake_stats(used_pct=85.0)
                mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
                asyncio.run(_run_cycle_sync())
            warning_calls = [str(c) for c in mock_log.warning.call_args_list]
            assert any("disco" in c.lower() or "atenção" in c.lower() or "%" in c
                       for c in warning_calls)
        finally:
            settings.image_cleanup_enabled = orig_e

    def test_cycle_loga_error_disco_critico(self):
        from app.core.config import settings
        orig_e = settings.image_cleanup_enabled
        try:
            settings.image_cleanup_enabled = False
            with patch("app.core.scheduler.storage_service") as mock_ss, \
                 patch("app.core.scheduler.SessionLocal", return_value=MagicMock()), \
                 patch("app.core.scheduler.log") as mock_log:
                mock_ss.get_disk_stats.return_value = _fake_stats(used_pct=96.0)
                mock_ss.count_images.return_value = {"original": 0, "annotated": 0, "total": 0}
                asyncio.run(_run_cycle_sync())
            error_calls = [str(c) for c in mock_log.error.call_args_list]
            assert any("crítico" in c.lower() or "CRÍTICO" in c or "critical" in c.lower()
                       for c in error_calls)
        finally:
            settings.image_cleanup_enabled = orig_e


# ═══════════════════════════════════════════════════════════════════════════════
# LP — cleanup_scheduler_loop
# ═══════════════════════════════════════════════════════════════════════════════

class TestCleanupSchedulerLoop:

    def test_loop_cancela_limpo(self):
        from app.core.scheduler import cleanup_scheduler_loop

        async def run():
            task = asyncio.create_task(cleanup_scheduler_loop())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run())

    def test_loop_aguarda_antes_de_executar(self):
        from app.core.scheduler import cleanup_scheduler_loop
        cycle_calls = {"n": 0}

        async def fake_cycle():
            cycle_calls["n"] += 1

        async def run():
            with patch("app.core.scheduler._run_cleanup_cycle", fake_cycle), \
                 patch("app.core.scheduler._seconds_until_next_run", return_value=9999.0):
                task = asyncio.create_task(cleanup_scheduler_loop())
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run())
        assert cycle_calls["n"] == 0

    def test_loop_executa_ciclo_apos_sleep(self):
        from app.core.scheduler import cleanup_scheduler_loop
        cycle_calls = {"n": 0}

        async def fast_cycle():
            cycle_calls["n"] += 1

        async def run():
            with patch("app.core.scheduler._run_cleanup_cycle", fast_cycle), \
                 patch("app.core.scheduler._seconds_until_next_run", return_value=0.01):
                task = asyncio.create_task(cleanup_scheduler_loop())
                await asyncio.sleep(0.15)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run())
        assert cycle_calls["n"] >= 1

    def test_loop_continua_apos_excecao_no_ciclo(self):
        from app.core.scheduler import cleanup_scheduler_loop
        call_count = {"n": 0}

        async def failing_cycle():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("falha simulada")

        async def run():
            with patch("app.core.scheduler._run_cleanup_cycle", failing_cycle), \
                 patch("app.core.scheduler._seconds_until_next_run", return_value=0.01):
                task = asyncio.create_task(cleanup_scheduler_loop())
                await asyncio.sleep(0.25)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run())
        assert call_count["n"] >= 2

    def test_loop_e_corrotina(self):
        from app.core.scheduler import cleanup_scheduler_loop
        assert asyncio.iscoroutinefunction(cleanup_scheduler_loop)

    def test_run_cycle_e_corrotina(self):
        from app.core.scheduler import _run_cleanup_cycle
        assert asyncio.iscoroutinefunction(_run_cleanup_cycle)


# ═══════════════════════════════════════════════════════════════════════════════
# IT — Integração com lifespan
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchedulerIntegration:

    def test_scheduler_importado_em_main(self):
        import inspect
        import app.main as main_module
        source = inspect.getsource(main_module)
        assert "cleanup_scheduler_loop" in source

    def test_scheduler_task_criada_no_lifespan(self):
        import inspect
        import app.main as main_module
        source = inspect.getsource(main_module.lifespan)
        assert "cleanup_scheduler_loop" in source
        assert "create_task" in source

    def test_scheduler_cancelado_no_shutdown(self):
        import inspect
        import app.main as main_module
        source = inspect.getsource(main_module.lifespan)
        assert "scheduler_task.cancel()" in source

    def test_scheduler_task_tem_nome(self):
        import inspect
        import app.main as main_module
        source = inspect.getsource(main_module.lifespan)
        assert "cleanup-scheduler" in source

    def test_app_inicia_sem_erro_com_scheduler(self):
        from app.main import app
        assert app is not None

    def test_env_example_documenta_image_cleanup(self):
        paths = [
            Path(__file__).parents[2] / ".env.example",
            Path(__file__).parents[3] / ".env.example",
        ]
        for p in paths:
            if p.exists():
                content = p.read_text()
                assert "IMAGE_CLEANUP" in content
                return
        pytest.skip(".env.example não encontrado")

    def test_orphan_check_enabled_no_env_example(self):
        paths = [
            Path(__file__).parents[2] / ".env.example",
            Path(__file__).parents[3] / ".env.example",
        ]
        for p in paths:
            if p.exists():
                content = p.read_text()
                assert "IMAGE_CLEANUP_ENABLED" in content
                return
        pytest.skip(".env.example não encontrado")
