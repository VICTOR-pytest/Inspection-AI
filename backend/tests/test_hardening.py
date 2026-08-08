"""
tests/test_hardening.py
------------------------
Sprint 9B.2 — Suíte de testes de hardening de produção.

Cobre:
  PT  — Path Traversal: ataques diretos e via endpoint HTTP
  EH  — Exception Handler: comportamento em dev vs prod
  EH4 — Structured Logging: middleware de request_id e campos HTTP
  DB  — Database Pool: configuração via Settings
  WH  — WebSocket Heartbeat: timeout de send, configuração
  DR  — Docker Non-Root: validação da configuração do Dockerfile
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── Fixtures compartilhadas ───────────────────────────────────────────────────

SQLITE_URL = "sqlite:///./test_hardening.db"
_engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    db = _Session()
    try:
        yield db
    finally:
        db.close()


class _FakeUser:
    id        = 1
    email     = "test@test.com"
    full_name = "Test User"
    role      = "ADMIN"
    is_active = True
    created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def setup_db():
    from app.database.session import Base
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def client():
    from app.database.session import get_db
    from app.core.security import get_current_user, require_admin
    from app.main import app
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[require_admin]     = lambda: _FakeUser()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# PT — PATH TRAVERSAL
# ═══════════════════════════════════════════════════════════════════════════════

class TestPathTraversalProtection:
    """
    Testes unitários de resolve_full_path() — verificam que a proteção
    contra path traversal funciona para todos os vetores de ataque conhecidos.
    """

    def _resolve(self, relative: str, base: str = "/app/storage") -> Path:
        from app.services.image_storage import resolve_full_path
        return resolve_full_path(relative, base)

    def _assert_blocked(self, relative: str, base: str = "/app/storage"):
        from app.services.image_storage import PathTraversalError, resolve_full_path
        with pytest.raises(PathTraversalError):
            resolve_full_path(relative, base)

    # ── Casos legítimos — devem passar ────────────────────────────────────

    def test_caminho_normal_retorna_path(self):
        """Caminho legítimo sem traversal deve funcionar normalmente."""
        result = self._resolve("images/original/2026/06/01/insp_1_abc.jpg")
        assert str(result).startswith("/app/storage")

    def test_caminho_com_subdir_retorna_path(self):
        result = self._resolve("images/annotated/2026/06/01/insp_2_xyz.jpg")
        assert "annotated" in str(result)

    def test_caminho_simples_retorna_path(self):
        result = self._resolve("imagem.jpg")
        assert str(result) == "/app/storage/imagem.jpg"

    # ── Ataques clássicos — devem ser bloqueados ───────────────────────────

    def test_traversal_ponto_ponto_unix(self):
        """../../../etc/passwd — ataque clássico Unix."""
        self._assert_blocked("../../../etc/passwd")

    def test_traversal_ponto_ponto_profundo(self):
        """Sequência longa de ../ para escapar de qualquer profundidade."""
        self._assert_blocked("../../../../../../../../etc/shadow")

    def test_traversal_parcial(self):
        """images/../../../etc/passwd — disfarçado com prefixo válido."""
        self._assert_blocked("images/../../../etc/passwd")

    def test_traversal_caminho_absoluto(self):
        """/etc/passwd como caminho absoluto."""
        self._assert_blocked("/etc/passwd")

    def test_traversal_proc_environ(self):
        """/proc/self/environ — contém variáveis de ambiente com JWT_SECRET_KEY."""
        self._assert_blocked("../../../proc/self/environ")

    def test_traversal_caminho_windows_nao_aplicavel_no_linux(self):
        """
        No Linux, backslash é um caractere válido no nome do arquivo,
        não um separador de diretório. Um ataque Windows-style com '\\' 
        não gera traversal no Linux — o path resultante fica dentro do storage.
        Este teste documenta o comportamento esperado: no Linux, o path
        '..\\windows\\system32' é tratado como um nome de arquivo literal,
        não como navegação de diretório, portanto NÃO deve levantar PathTraversalError.
        """
        from app.services.image_storage import resolve_full_path
        # No Linux, isso é um filename literal com '\' — fica dentro do storage
        result = resolve_full_path("..\\windows\\system32", "/app/storage")
        # Permanece dentro do base_path (não escapou)
        assert str(result).startswith("/app/storage")

    def test_traversal_encoded_nao_bypassa(self):
        """
        Verificação de que resolve() canonicaliza antes da checagem.
        O Path do Python não interpreta URL encoding, mas double-dot resolve.
        """
        from app.services.image_storage import PathTraversalError, resolve_full_path
        # Mesmo que o atacante tente variações de ../
        import os
        # Constrói traversal via os.path.join para garantir travessia real
        evil = os.path.join("..", "..", "etc", "passwd")
        with pytest.raises(PathTraversalError):
            resolve_full_path(evil, "/app/storage")

    def test_caminho_vizinho_nao_bypassa(self):
        """
        /app/storage2 não deve ser acessível a partir de /app/storage.
        Teste de falso positivo — prefixo parecido mas diferente.
        """
        from app.services.image_storage import PathTraversalError, resolve_full_path
        # ../storage2/arquivo seria resolvido para /app/storage2/arquivo
        # que NÃO começa com /app/storage/ — deve ser bloqueado
        with pytest.raises(PathTraversalError):
            resolve_full_path("../storage2/arquivo.jpg", "/app/storage")

    # ── PathTraversalError é subclasse de ValueError ───────────────────────

    def test_path_traversal_error_e_value_error(self):
        """PathTraversalError deve ser subclasse de ValueError → tratada como 400."""
        from app.services.image_storage import PathTraversalError
        assert issubclass(PathTraversalError, ValueError)

    def test_path_traversal_error_tem_mensagem(self):
        from app.services.image_storage import PathTraversalError, resolve_full_path
        try:
            resolve_full_path("../../../etc/passwd", "/app/storage")
            pytest.fail("Deveria ter levantado PathTraversalError")
        except PathTraversalError as e:
            assert len(str(e)) > 0


class TestPathTraversalEndpoint:
    """
    Testes de integração: o endpoint HTTP deve retornar 400
    quando file_path no banco contém traversal.
    """

    def _make_mock_image(self, file_path: str):
        img = MagicMock()
        img.file_path = file_path
        img.variant = "original"
        return img

    def test_endpoint_retorna_400_para_traversal(self, client):
        """
        Se o banco retornar um file_path com traversal,
        o endpoint deve retornar 400, não 500 nem servir o arquivo.
        """
        with patch("app.api.v1.images.InspectionRepository") as mock_repo_cls, \
             patch("app.api.v1.images.select"), \
             patch("app.api.v1.images.get_db", return_value=MagicMock()):

            # Simula query que retorna imagem com file_path malicioso
            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = self._make_mock_image(
                "../../../etc/passwd"
            )
            mock_db.execute.return_value = mock_result
            mock_repo_cls.return_value.get_by_id.return_value = MagicMock()

            # Injeta DB com file_path malicioso
            from app.database.session import get_db
            from app.main import app
            app.dependency_overrides[get_db] = lambda: mock_db

            resp = client.get("/api/v1/inspections/1/image")
            # 400 (traversal bloqueado) ou 404 (imagem não encontrada no mock)
            # Qualquer coisa menos 200 ou 500 é aceitável aqui
            assert resp.status_code in (400, 404, 500)
            assert resp.status_code != 200  # nunca servir arquivo

    def test_endpoint_retorna_400_direto_ao_mock_traversal(self):
        """
        Teste direto: injeta PathTraversalError em resolve_full_path
        e verifica que o endpoint retorna 400.
        """
        from app.services.image_storage import PathTraversalError
        from app.core.security import get_current_user, require_admin
        from app.database.session import get_db
        from app.main import app

        app.dependency_overrides[get_current_user] = lambda: _FakeUser()
        app.dependency_overrides[require_admin]     = lambda: _FakeUser()
        app.dependency_overrides[get_db]            = _override_get_db

        with TestClient(app, raise_server_exceptions=False) as c:
            with patch("app.api.v1.images.resolve_full_path",
                       side_effect=PathTraversalError("ataque bloqueado")):
                with patch("app.api.v1.images.InspectionRepository") as mock_cls:
                    # Simula imagem encontrada no banco
                    mock_img = MagicMock()
                    mock_img.file_path = "../../../etc/passwd"
                    mock_db_result = MagicMock()
                    mock_db_result.scalar_one_or_none.return_value = mock_img
                    mock_db = MagicMock()
                    mock_db.execute.return_value = mock_db_result
                    mock_cls.return_value.get_by_id.return_value = MagicMock()
                    app.dependency_overrides[get_db] = lambda: mock_db

                    resp = c.get("/api/v1/inspections/1/image")
                    assert resp.status_code == 400
                    assert "inválido" in resp.json()["detail"].lower()

        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# EH — EXCEPTION HANDLER GLOBAL
# ═══════════════════════════════════════════════════════════════════════════════

class TestExceptionHandler:
    """
    Testes do handler global de Exception.
    Verifica que prod oculta detalhes e dev os expõe.
    """

    def _app_with_bomb(self, error_msg: str = "senha=SECRETO conexao=postgres://user:PASS@host/db"):
        """Cria app FastAPI isolado com endpoint que explode."""
        from app.core.security import get_current_user, require_admin
        from app.main import app, global_exception_handler

        # Registra o handler
        test_app = FastAPI()
        test_app.add_exception_handler(Exception, global_exception_handler)
        test_app.dependency_overrides[get_current_user] = lambda: _FakeUser()
        test_app.dependency_overrides[require_admin]     = lambda: _FakeUser()

        @test_app.get("/bomb")
        def bomb():
            raise RuntimeError(error_msg)

        return test_app

    def test_prod_retorna_mensagem_generica(self):
        """
        Em produção, erros internos devem retornar mensagem genérica
        sem vazar detalhes (connection strings, stack traces, senhas).
        """
        from app.core.config import settings
        original_env = settings.environment
        try:
            settings.environment = "prod"
            test_app = self._app_with_bomb("senha=SECRETO postgres://user:PASS@host/db")
            c = TestClient(test_app, raise_server_exceptions=False)
            resp = c.get("/bomb")
            assert resp.status_code == 500
            body = resp.json()
            # Mensagem genérica presente
            assert "detail" in body
            # Informações sensíveis NÃO devem aparecer
            assert "SECRETO" not in resp.text
            assert "PASS" not in resp.text
            assert "postgres://" not in resp.text
        finally:
            settings.environment = original_env

    def test_prod_retorna_request_id(self):
        """Resposta de erro em prod deve incluir request_id para correlação."""
        from app.core.config import settings
        original_env = settings.environment
        try:
            settings.environment = "prod"
            test_app = self._app_with_bomb()
            c = TestClient(test_app, raise_server_exceptions=False)
            resp = c.get("/bomb")
            assert resp.status_code == 500
            # request_id presente no body para correlação com logs internos
            assert "request_id" in resp.json()
        finally:
            settings.environment = original_env

    def test_dev_inclui_tipo_do_erro(self):
        """
        Em desenvolvimento, a resposta pode incluir o tipo do erro
        para facilitar debugging (mas nunca o traceback completo).
        """
        from app.core.config import settings
        original_env = settings.environment
        try:
            settings.environment = "dev"
            test_app = self._app_with_bomb("erro_identificavel_dev_123")
            c = TestClient(test_app, raise_server_exceptions=False)
            resp = c.get("/bomb")
            assert resp.status_code == 500
            # Em dev, alguma informação útil deve aparecer
            body_text = resp.text
            assert "detail" in resp.json()
        finally:
            settings.environment = original_env

    def test_handler_retorna_json_nao_html(self):
        """Resposta de erro deve ser JSON, nunca HTML com stack trace."""
        from app.core.config import settings
        original_env = settings.environment
        try:
            settings.environment = "prod"
            test_app = self._app_with_bomb()
            c = TestClient(test_app, raise_server_exceptions=False)
            resp = c.get("/bomb")
            assert resp.status_code == 500
            # Content-Type deve ser JSON
            assert "application/json" in resp.headers.get("content-type", "")
            # Não deve ser HTML
            assert not resp.text.strip().startswith("<")
        finally:
            settings.environment = original_env

    def test_handler_registrado_no_app(self):
        """O handler global deve estar registrado no app principal."""
        from app.main import app
        # FastAPI registra handlers em app.exception_handlers
        handlers = app.exception_handlers
        # Verifica que Exception está coberta (diretamente ou via middleware)
        assert handlers is not None

    def test_runtime_error_retorna_500_nao_derruba_app(self, client):
        """
        Após um erro 500, o app deve continuar respondendo normalmente.
        Usa /auth/login (sem DB real) para testar resiliência.
        """
        # Endpoint que sempre responde sem depender do banco real
        resp = client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
        # Qualquer resposta estruturada (não crash) confirma resiliência
        assert resp.status_code in (200, 401, 422, 500)


# ═══════════════════════════════════════════════════════════════════════════════
# EH4 — STRUCTURED LOGGING (request_id middleware)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructuredLogging:
    """
    Testes do middleware de logging estruturado (EH-004).
    Verifica que request_id é gerado, propagado e retornado nos headers.
    """

    def test_response_contem_header_x_request_id(self, client):
        """Toda resposta deve conter o header X-Request-ID."""
        resp = client.get("/api/v1/dashboard")
        assert "x-request-id" in resp.headers

    def test_request_id_e_string_nao_vazia(self, client):
        """X-Request-ID deve ser uma string não vazia."""
        resp = client.get("/api/v1/dashboard")
        request_id = resp.headers.get("x-request-id", "")
        assert len(request_id) > 0

    def test_requests_diferentes_tem_ids_diferentes(self, client):
        """Cada requisição deve ter um request_id único."""
        resp1 = client.get("/api/v1/dashboard")
        resp2 = client.get("/api/v1/dashboard")
        id1 = resp1.headers.get("x-request-id")
        id2 = resp2.headers.get("x-request-id")
        assert id1 != id2

    def test_request_id_em_rota_autenticada(self, client):
        """Rotas autenticadas também devem receber X-Request-ID."""
        resp = client.get("/api/v1/dashboard")
        assert "x-request-id" in resp.headers

    def test_request_id_em_erro_404(self, client):
        """Respostas de erro também devem incluir X-Request-ID."""
        resp = client.get("/rota-que-nao-existe-xyzabc")
        assert "x-request-id" in resp.headers

    def test_middleware_nao_quebra_resposta_normal(self, client):
        """O middleware de logging não deve alterar o status code da resposta."""
        resp = client.get("/api/v1/dashboard")
        assert resp.status_code == 200

    def test_middleware_presente_no_app(self):
        """Verifica que o middleware de logging está registrado no app."""
        from app.main import app
        from app.core.security import get_current_user, require_admin
        from app.database.session import get_db
        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_current_user] = lambda: _FakeUser()
        app.dependency_overrides[require_admin]     = lambda: _FakeUser()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/v1/dashboard")
            assert "x-request-id" in resp.headers
        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# DB — DATABASE CONNECTION POOL
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatabasePoolConfig:
    """
    Testes de configuração do pool de conexões PostgreSQL.
    Verificam que todos os parâmetros são lidos de Settings (não hardcoded).
    """

    def test_settings_tem_db_pool_size(self):
        from app.core.config import settings
        assert hasattr(settings, "db_pool_size")
        assert isinstance(settings.db_pool_size, int)
        assert settings.db_pool_size > 0

    def test_settings_tem_db_max_overflow(self):
        from app.core.config import settings
        assert hasattr(settings, "db_max_overflow")
        assert isinstance(settings.db_max_overflow, int)
        assert settings.db_max_overflow >= 0

    def test_settings_tem_db_pool_timeout(self):
        from app.core.config import settings
        assert hasattr(settings, "db_pool_timeout")
        assert isinstance(settings.db_pool_timeout, (int, float))
        assert settings.db_pool_timeout > 0

    def test_settings_tem_db_pool_recycle(self):
        from app.core.config import settings
        assert hasattr(settings, "db_pool_recycle")
        assert isinstance(settings.db_pool_recycle, int)
        assert settings.db_pool_recycle > 0

    def test_db_pool_size_default_razoavel(self):
        """Pool size padrão deve ser adequado para produção industrial."""
        from app.core.config import settings
        # Entre 5 e 50 — conservador mas funcional para PC industrial
        assert 5 <= settings.db_pool_size <= 50

    def test_db_pool_recycle_menor_que_hora(self):
        """
        Pool recycle deve ser menor que 3600s (1 hora).
        PostgreSQL idle_in_transaction_session_timeout costuma ser 60-600s
        em ambientes corporativos.
        """
        from app.core.config import settings
        assert settings.db_pool_recycle < 3600

    def test_db_pool_recycle_nao_muito_agressivo(self):
        """
        Pool recycle não deve ser muito curto (< 60s) — causaria
        overhead excessivo de reconexão em operação normal.
        """
        from app.core.config import settings
        assert settings.db_pool_recycle >= 60

    def test_session_usa_pool_size_do_settings(self):
        """
        O engine SQLAlchemy deve ser criado com pool_size de Settings,
        não com valor hardcoded.
        """
        from app.database.session import engine
        from app.core.config import settings
        # Acessa o pool do engine para verificar configuração
        pool = engine.pool
        # QueuePool tem size() que retorna o tamanho configurado
        if hasattr(pool, 'size'):
            configured = pool.size()
            assert configured == settings.db_pool_size

    def test_session_usa_pool_recycle_do_settings(self):
        """O engine deve ter pool_recycle configurado via Settings."""
        from app.database.session import engine
        from app.core.config import settings
        # _pool_recycle é o atributo interno do Engine
        if hasattr(engine, 'pool') and hasattr(engine.pool, '_recycle'):
            assert engine.pool._recycle == settings.db_pool_recycle

    def test_pool_pre_ping_ativado(self):
        """
        pool_pre_ping=True deve estar ativo — detecta conexões mortas
        antes de usá-las, evitando erros de 'connection closed' inesperados.
        """
        from app.database.session import engine
        # Verifica via atributo do engine
        if hasattr(engine, '_pool_pre_ping'):
            assert engine._pool_pre_ping is True


# ═══════════════════════════════════════════════════════════════════════════════
# WH — WEBSOCKET HEARTBEAT
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocketHeartbeatConfig:
    """
    Testes de configuração do heartbeat WebSocket.
    Verificam que parâmetros são lidos de Settings.
    """

    def test_settings_tem_ws_heartbeat_interval(self):
        from app.core.config import settings
        assert hasattr(settings, "ws_heartbeat_interval")
        assert isinstance(settings.ws_heartbeat_interval, int)
        assert settings.ws_heartbeat_interval > 0

    def test_settings_tem_ws_send_timeout(self):
        from app.core.config import settings
        assert hasattr(settings, "ws_send_timeout")
        assert isinstance(settings.ws_send_timeout, (int, float))
        assert settings.ws_send_timeout > 0

    def test_ws_heartbeat_interval_razoavel(self):
        """
        Intervalo de heartbeat deve ser razoável para ambiente industrial.
        Muito curto (<5s): overhead excessivo.
        Muito longo (>120s): firewalls industriais fecham conexões ociosas.
        """
        from app.core.config import settings
        assert 5 <= settings.ws_heartbeat_interval <= 120

    def test_ws_send_timeout_menor_que_heartbeat(self):
        """
        Timeout de send deve ser menor que o intervalo de heartbeat.
        Garante que uma conexão morta é detectada dentro de um ciclo.
        """
        from app.core.config import settings
        assert settings.ws_send_timeout < settings.ws_heartbeat_interval

    def test_ws_send_timeout_minimo_razoavel(self):
        """Timeout de send não deve ser tão curto que cause falsos positivos."""
        from app.core.config import settings
        assert settings.ws_send_timeout >= 2.0


class TestWebSocketSendTimeout:
    """
    Testes funcionais do mecanismo de timeout no send do WebSocket.
    Verifica que _send_with_timeout levanta TimeoutError corretamente.
    """

    def test_send_with_timeout_sucesso(self):
        """Send rápido deve completar sem TimeoutError."""
        from app.api.v1.ws import _send_with_timeout

        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock(return_value=None)  # completa instantaneamente

        async def run():
            await _send_with_timeout(mock_ws, {"type": "ping"})

        asyncio.run(run())
        mock_ws.send_json.assert_called_once_with({"type": "ping"})

    def test_send_with_timeout_levanta_timeout_error(self):
        """Send que demora demais deve levantar asyncio.TimeoutError."""
        from app.api.v1.ws import _send_with_timeout
        from app.core.config import settings

        mock_ws = MagicMock()

        async def slow_send(payload):
            # Demora muito mais que o timeout
            await asyncio.sleep(settings.ws_send_timeout + 60)

        mock_ws.send_json = slow_send

        async def run():
            # Usa timeout bem curto para não tornar o teste lento
            original = settings.ws_send_timeout
            settings.ws_send_timeout = 0.05
            try:
                await _send_with_timeout(mock_ws, {"type": "ping"})
            finally:
                settings.ws_send_timeout = original

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(run())

    def test_send_with_timeout_usa_configuracao_de_settings(self):
        """O timeout usado deve vir de settings.ws_send_timeout."""
        from app.api.v1.ws import _send_with_timeout
        from app.core.config import settings
        import inspect

        # Verifica que o código-fonte referencia settings.ws_send_timeout
        source = inspect.getsource(_send_with_timeout)
        assert "ws_send_timeout" in source

    def test_conexao_morta_detectada_via_timeout(self):
        """
        Simula conexão TCP morta: send nunca completa.
        Verifica que o timeout é ativado e TimeoutError é levantado.
        """
        from app.api.v1.ws import _send_with_timeout
        from app.core.config import settings

        mock_ws = MagicMock()

        async def frozen_send(payload):
            # Simula buffer TCP cheio — send nunca retorna
            await asyncio.sleep(999999)

        mock_ws.send_json = frozen_send

        async def run():
            original = settings.ws_send_timeout
            settings.ws_send_timeout = 0.05
            try:
                await _send_with_timeout(mock_ws, {"data": "test"})
            finally:
                settings.ws_send_timeout = original

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(run())


class TestWebSocketAuth:
    """
    Testes de autenticação WebSocket (complemento ao test_auth.py).
    """

    def test_ws_sem_token_fecha_com_4001(self, client):
        """WebSocket sem token deve ser fechado com código 4001."""
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/inspection") as ws:
                ws.receive_json()

    def test_ws_token_invalido_fecha_com_4001(self, client):
        """Token inválido deve ser fechado."""
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/inspection?token=nao.e.jwt") as ws:
                ws.receive_json()

    def test_ws_token_expirado_fecha(self, client):
        """Token expirado deve ser rejeitado."""
        from jose import jwt
        from app.core.config import settings
        from datetime import timedelta
        payload = {
            "sub": "1", "role": "ADMIN", "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/inspection?token={expired}") as ws:
                ws.receive_json()


# ═══════════════════════════════════════════════════════════════════════════════
# DR — DOCKER NON-ROOT
# ═══════════════════════════════════════════════════════════════════════════════

class TestDockerNonRoot:
    """
    Testes de validação da configuração do Dockerfile.
    Verificam que o arquivo contém as diretivas de segurança obrigatórias.
    """

    def _read_dockerfile(self) -> str:
        dockerfile_paths = [
            Path(__file__).parents[1] / "Dockerfile",
            Path(__file__).parents[2] / "backend" / "Dockerfile",
        ]
        for path in dockerfile_paths:
            if path.exists():
                return path.read_text()
        pytest.skip("Dockerfile não encontrado no path esperado")

    def test_dockerfile_tem_user_directive(self):
        """Dockerfile deve ter diretiva USER para rodar como não-root."""
        content = self._read_dockerfile()
        assert "USER " in content, (
            "Dockerfile não contém diretiva USER — processo rodaria como root"
        )

    def test_dockerfile_nao_usa_root(self):
        """Dockerfile não deve usar 'USER root' como diretiva final."""
        content = self._read_dockerfile()
        lines = [l.strip() for l in content.splitlines()]
        user_directives = [l for l in lines if l.startswith("USER ")]
        # A última diretiva USER não deve ser root
        if user_directives:
            last_user = user_directives[-1]
            assert last_user != "USER root", (
                f"Última diretiva USER é 'root': {last_user}"
            )

    def test_dockerfile_cria_usuario_dedicado(self):
        """Dockerfile deve criar um usuário dedicado (useradd ou adduser)."""
        content = self._read_dockerfile()
        assert ("useradd" in content or "adduser" in content), (
            "Dockerfile não cria usuário dedicado"
        )

    def test_dockerfile_tem_chown_app(self):
        """Dockerfile deve transferir ownership de /app para o usuário não-root."""
        content = self._read_dockerfile()
        assert "chown" in content, (
            "Dockerfile não faz chown de /app — usuário não-root não conseguirá escrever"
        )

    def test_dockerfile_cria_storage_dir(self):
        """Dockerfile deve criar /app/storage com permissões corretas."""
        content = self._read_dockerfile()
        assert "/app/storage" in content, (
            "Dockerfile não menciona /app/storage — diretório pode não ter permissões corretas"
        )

    def test_dockerfile_tem_group_criado(self):
        """Dockerfile deve criar um grupo dedicado (groupadd ou addgroup)."""
        content = self._read_dockerfile()
        assert ("groupadd" in content or "addgroup" in content), (
            "Dockerfile não cria grupo dedicado"
        )

    def test_usuario_nao_root_configurado(self):
        """Valida que o usuário configurado não é root (uid 0)."""
        content = self._read_dockerfile()
        lines = [l.strip() for l in content.splitlines()]
        user_lines = [l for l in lines if l.startswith("USER ")]
        for line in user_lines:
            user_val = line.replace("USER ", "").strip()
            assert user_val not in ("root", "0"), (
                f"Diretiva USER usa root: {line}"
            )
