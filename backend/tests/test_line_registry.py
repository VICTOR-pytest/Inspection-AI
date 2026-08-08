"""
tests/test_line_registry.py
------------------------------
Sprint 10C.2 (PR-002) — Testes do LineRegistry.

Testes puros (sem banco, sem threads reais) — usam LineContext com
objetos MagicMock no lugar de VisionWorker/EventBus reais, focando na
lógica de registro/lookup do próprio Registry.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from app.core.line_registry import LineContext, LineRegistry


@pytest.fixture()
def registry():
    return LineRegistry()


def _ctx(line_id: int, code: str, is_default: bool = False) -> LineContext:
    return LineContext(
        line_id=line_id,
        code=code,
        name=f"Linha {code}",
        worker=MagicMock(),
        event_bus=MagicMock(),
        is_default=is_default,
    )


class TestRegisterAndGet:

    def test_register_e_get_por_id(self, registry):
        registry.register(_ctx(1, "L01"))
        ctx = registry.get(1)
        assert ctx is not None
        assert ctx.code == "L01"

    def test_chave_e_o_id_nao_o_code(self, registry):
        """Ajuste do usuário: a chave interna DEVE ser o id, nunca o code."""
        registry.register(_ctx(42, "L01"))
        assert registry.get(42) is not None
        # get() espera um int (id); passar o código não deve encontrar nada
        assert registry.get("L01") is None  # type: ignore[arg-type]

    def test_get_id_inexistente_retorna_none(self, registry):
        assert registry.get(999) is None

    def test_get_by_code_encontra_pelo_code(self, registry):
        registry.register(_ctx(7, "L07"))
        ctx = registry.get_by_code("L07")
        assert ctx is not None
        assert ctx.line_id == 7

    def test_get_by_code_inexistente_retorna_none(self, registry):
        assert registry.get_by_code("INEXISTENTE") is None

    def test_register_sobrescreve_linha_existente(self, registry):
        registry.register(_ctx(1, "L01"))
        registry.register(_ctx(1, "L01-RENOMEADA"))
        assert registry.get(1).code == "L01-RENOMEADA"
        assert len(registry) == 1


class TestUnregister:

    def test_unregister_remove_e_retorna_contexto(self, registry):
        registry.register(_ctx(1, "L01"))
        removed = registry.unregister(1)
        assert removed is not None
        assert removed.line_id == 1
        assert registry.get(1) is None

    def test_unregister_inexistente_retorna_none(self, registry):
        assert registry.unregister(999) is None

    def test_unregister_limpa_default_se_era_a_linha_default(self, registry):
        registry.register(_ctx(1, "L01", is_default=True))
        assert registry.default() is not None
        registry.unregister(1)
        assert registry.default() is None


class TestAllAndLen:

    def test_all_retorna_todas_as_linhas(self, registry):
        registry.register(_ctx(1, "L01"))
        registry.register(_ctx(2, "L02"))
        all_ctx = registry.all()
        assert len(all_ctx) == 2
        assert {c.line_id for c in all_ctx} == {1, 2}

    def test_len_reflete_quantidade_registrada(self, registry):
        assert len(registry) == 0
        registry.register(_ctx(1, "L01"))
        assert len(registry) == 1

    def test_contains_operator(self, registry):
        registry.register(_ctx(5, "L05"))
        assert 5 in registry
        assert 6 not in registry


class TestDefault:

    def test_default_none_quando_nenhuma_linha_marcada(self, registry):
        registry.register(_ctx(1, "L01"))  # is_default=False
        assert registry.default() is None

    def test_default_retorna_linha_marcada_no_register(self, registry):
        registry.register(_ctx(1, "L01", is_default=True))
        assert registry.default().line_id == 1

    def test_set_default_altera_a_linha_default(self, registry):
        registry.register(_ctx(1, "L01", is_default=True))
        registry.register(_ctx(2, "L02"))
        registry.set_default(2)
        assert registry.default().line_id == 2
        assert registry.get(2).is_default is True

    def test_set_default_id_inexistente_e_noop(self, registry):
        registry.register(_ctx(1, "L01", is_default=True))
        registry.set_default(999)
        assert registry.default().line_id == 1  # inalterado


class TestClear:

    def test_clear_remove_todas_as_linhas(self, registry):
        registry.register(_ctx(1, "L01", is_default=True))
        registry.register(_ctx(2, "L02"))
        registry.clear()
        assert len(registry) == 0
        assert registry.default() is None


class TestThreadSafety:

    def test_registers_concorrentes_nao_perdem_entradas(self, registry):
        """
        20 threads registrando 20 linhas distintas concorrentemente —
        todas devem aparecer no registry ao final (nenhuma perdida por
        condição de corrida no dict interno).
        """
        def _worker(i: int) -> None:
            registry.register(_ctx(i, f"L{i:02d}"))

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(registry) == 20
        assert {c.line_id for c in registry.all()} == set(range(20))
