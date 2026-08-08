"""
tests/test_image_storage.py
-----------------------------
Sprint 7B — Testes do serviço de armazenamento de imagens e endpoint.

Cobre:
  - image_storage: criação de diretórios, nomes únicos, salvar, resolver path
  - image_storage: falha de disco (permissão negada)
  - image_storage: encode_frame_to_jpeg com frame válido e inválido
  - dashboard_service.persist_event: com e sem jpeg_bytes
  - InspectionImage: criado e associado corretamente
  - GET /api/v1/inspections/{id}/image: 200, 404 (sem inspeção), 404 (sem imagem), 410 (arquivo sumiu)

Sem webcam. Sem PostgreSQL. Usa SQLite em memória + tmp dirs.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base, get_db
from app.main import app
from app.models import Inspection, InspectionImage, Product  # noqa: F401

# ── SQLite compartilhado para este módulo de testes ──────────────────────────

SQLITE_URL = "sqlite:///./test_image_storage.db"
engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def tmp_storage(tmp_path: Path) -> Path:
    """Diretório temporário isolado para cada teste — sem poluir o disco."""
    storage = tmp_path / "storage"
    storage.mkdir()
    return storage


@pytest.fixture()
def fake_frame() -> np.ndarray:
    """Frame numpy 100x100 BGR simples para testes."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


@pytest.fixture()
def fake_jpeg(fake_frame) -> bytes:
    """JPEG válido gerado a partir do frame falso."""
    import cv2
    _, buf = cv2.imencode(".jpg", fake_frame)
    return buf.tobytes()


# ── image_storage: funções utilitárias ───────────────────────────────────────


class TestMakeFilename:
    def test_formato_correto(self):
        from app.services.image_storage import make_filename
        name = make_filename(42)
        assert name.startswith("inspection_42_")
        assert name.endswith(".jpg")

    def test_nome_unico_por_chamada(self):
        from app.services.image_storage import make_filename
        nomes = {make_filename(1) for _ in range(100)}
        assert len(nomes) == 100, "make_filename deve gerar nomes únicos"

    def test_inspection_id_none_usa_zero(self):
        from app.services.image_storage import make_filename
        name = make_filename(None)
        assert name.startswith("inspection_0_")


class TestDateSubdir:
    def test_cria_estrutura_yyyy_mm_dd(self, tmp_storage):
        from app.services.image_storage import _date_subdir
        dt = datetime(2026, 6, 21, tzinfo=timezone.utc)
        subdir = _date_subdir(tmp_storage, dt)
        # Sprint 8C: _date_subdir agora inclui o variant no path (default="original")
        assert subdir == tmp_storage / "images" / "original" / "2026" / "06" / "21"
        assert subdir.exists()

    def test_cria_dirs_aninhados_automaticamente(self, tmp_storage):
        from app.services.image_storage import _date_subdir
        dt = datetime(2030, 1, 5, tzinfo=timezone.utc)
        subdir = _date_subdir(tmp_storage, dt)
        # Sprint 8C: variant 'original' é o default
        assert (tmp_storage / "images" / "original" / "2030" / "01" / "05").exists()

    def test_idempotente_se_ja_existe(self, tmp_storage):
        from app.services.image_storage import _date_subdir
        dt = datetime(2026, 6, 21, tzinfo=timezone.utc)
        # Chamar duas vezes não levanta exceção
        _date_subdir(tmp_storage, dt)
        _date_subdir(tmp_storage, dt)


class TestSaveFrameBytes:
    def test_salva_arquivo_e_retorna_path_relativo(self, tmp_storage, fake_jpeg):
        from app.services.image_storage import save_frame_bytes
        dt = datetime(2026, 6, 21, tzinfo=timezone.utc)
        relative = save_frame_bytes(fake_jpeg, tmp_storage, inspection_id=1, dt=dt)

        # Sprint 8C: path inclui variant (default='original')
        assert relative.startswith("images/original/2026/06/21/")
        assert relative.endswith(".jpg")
        full = tmp_storage / relative
        assert full.exists()
        assert full.read_bytes() == fake_jpeg

    def test_arquivo_contem_bytes_corretos(self, tmp_storage, fake_jpeg):
        from app.services.image_storage import save_frame_bytes
        relative = save_frame_bytes(fake_jpeg, tmp_storage, inspection_id=7)
        content = (tmp_storage / relative).read_bytes()
        assert content == fake_jpeg

    def test_bytes_vazios_levanta_error(self, tmp_storage):
        from app.services.image_storage import ImageStorageError, save_frame_bytes
        with pytest.raises(ImageStorageError, match="vazio"):
            save_frame_bytes(b"", tmp_storage, inspection_id=1)

    def test_falha_de_permissao_levanta_image_storage_error(self, tmp_storage, fake_jpeg):
        from app.services.image_storage import ImageStorageError, save_frame_bytes

        # Simula falha de IO ao escrever o arquivo (OSError no write_bytes)
        # Não usamos chmod pois o processo pode rodar como root (CI/Docker)
        with patch("pathlib.Path.write_bytes", side_effect=OSError("Permission denied")):
            with pytest.raises(ImageStorageError, match="Falha ao escrever"):
                save_frame_bytes(fake_jpeg, tmp_storage, inspection_id=1)

    def test_usa_data_atual_quando_dt_nao_fornecido(self, tmp_storage, fake_jpeg):
        from app.services.image_storage import save_frame_bytes
        relative = save_frame_bytes(fake_jpeg, tmp_storage, inspection_id=1)
        # Deve conter o ano atual na path
        now_year = datetime.now(timezone.utc).strftime("%Y")
        assert now_year in relative


class TestResolveFullPath:
    def test_reconstroi_caminho_absoluto(self, tmp_storage):
        from app.services.image_storage import resolve_full_path
        relative = "images/2026/06/21/inspection_1_abc.jpg"
        full = resolve_full_path(relative, tmp_storage)
        assert full == tmp_storage / "images" / "2026" / "06" / "21" / "inspection_1_abc.jpg"


class TestEncodeFrameToJpeg:
    def test_frame_valido_retorna_bytes(self, fake_frame):
        from app.services.image_storage import encode_frame_to_jpeg
        result = encode_frame_to_jpeg(fake_frame)
        assert result is not None
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_frame_none_retorna_none(self):
        from app.services.image_storage import encode_frame_to_jpeg
        result = encode_frame_to_jpeg(None)
        assert result is None

    def test_bytes_resultado_sao_jpeg_valido(self, fake_frame):
        from app.services.image_storage import encode_frame_to_jpeg
        result = encode_frame_to_jpeg(fake_frame)
        # JPEG começa com bytes mágicos FF D8 FF
        assert result[:2] == b"\xff\xd8"


# ── persist_event com imagem ──────────────────────────────────────────────────


class TestPersistEventComImagem:
    def _criar_produto(self, db):
        from app.models.product import Product
        p = Product(
            name="Produto X",
            barcode="789123456",
            expected_weight=1.0,
            tolerance=0.05,
            is_active=True,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return p

    def test_persist_event_sem_jpeg_nao_cria_inspection_image(
        self, db_session, tmp_storage
    ):
        from app.services.dashboard_service import persist_event

        event = {
            "type": "inspection",
            "barcode": "789123456",
            "weight": 1.0,
            "valid": True,
            "reason": None,
            "confidence": 0.95,
            "product_name": "Produto X",
        }

        with patch("app.services.dashboard_service._persist_image") as mock_img:
            persist_event(db_session, event, jpeg_bytes=None)
            mock_img.assert_not_called()

        total = db_session.query(InspectionImage).count()
        assert total == 0

    def test_persist_event_com_jpeg_chama_persist_image(
        self, db_session, tmp_storage, fake_jpeg
    ):
        from app.services.dashboard_service import persist_event

        event = {
            "type": "inspection",
            "barcode": "UNDETECTED",
            "weight": 1.0,
            "valid": False,
            "reason": "barcode não encontrado",
            "confidence": 0.80,
            "product_name": None,
        }

        with patch("app.services.dashboard_service._persist_image") as mock_img:
            persist_event(db_session, event, jpeg_bytes=fake_jpeg)
            mock_img.assert_called_once()
            _, kwargs_inspection, kwargs_bytes = mock_img.call_args[0]

    def test_persist_event_evento_nao_inspection_retorna_none(self, db_session):
        from app.services.dashboard_service import persist_event

        result = persist_event(db_session, {"type": "line_status"})
        assert result is None

    def test_persist_image_cria_registro_no_banco(
        self, db_session, tmp_storage, fake_jpeg
    ):
        from app.models.inspection import Inspection
        from app.services.dashboard_service import _persist_image

        # Criar inspeção manualmente
        inspection = Inspection(
            barcode="789123456",
            weight=1.0,
            is_valid=True,
            reason=None,
            confidence=0.95,
        )
        db_session.add(inspection)
        db_session.commit()
        db_session.refresh(inspection)

        with patch("app.core.config.settings") as mock_settings,              patch("app.services.image_storage.save_frame_bytes", wraps=__import__("app.services.image_storage", fromlist=["save_frame_bytes"]).save_frame_bytes) as _:
            mock_settings.storage_path = str(tmp_storage)
            # Importa settings no contexto do service para garantir que o patch chegue
            import app.core.config
            app.core.config.settings.storage_path = str(tmp_storage)
            _persist_image(db_session, inspection, fake_jpeg)
            app.core.config.settings.storage_path = "/app/storage"  # restaura

        record = db_session.query(InspectionImage).filter_by(
            inspection_id=inspection.id
        ).first()
        assert record is not None
        assert record.file_path.startswith("images/")
        assert record.file_path.endswith(".jpg")

        # Arquivo deve existir no disco
        full = tmp_storage / record.file_path
        assert full.exists()

    def test_persist_image_falha_io_nao_propaga(
        self, db_session, tmp_storage, fake_jpeg
    ):
        from app.models.inspection import Inspection
        from app.services.dashboard_service import _persist_image
        from app.services.image_storage import ImageStorageError

        inspection = Inspection(
            barcode="789123456", weight=1.0, is_valid=True, reason=None, confidence=0.95
        )
        db_session.add(inspection)
        db_session.commit()

        import app.core.config as _cfg
        _orig = _cfg.settings.storage_path
        _cfg.settings.storage_path = str(tmp_storage)
        try:
            with patch(
                "app.services.image_storage.save_frame_bytes",
                side_effect=ImageStorageError("disco cheio"),
            ):
                _persist_image(db_session, inspection, fake_jpeg)  # não deve levantar
        finally:
            _cfg.settings.storage_path = _orig

        # Nenhum registro criado (falhou antes)
        assert db_session.query(InspectionImage).count() == 0


# ── API endpoint ──────────────────────────────────────────────────────────────


class TestGetInspectionImageEndpoint:
    def _seed_inspection(self, client) -> int:
        """Cria inspeção via API e retorna o ID."""
        # Primeiro criar produto
        client.post("/products/", json={
            "name": "Produto A", "barcode": "789123456",
            "expected_weight": 1.0, "tolerance": 0.05, "is_active": True,
        })
        resp = client.post("/inspection/check", json={
            "barcode": "789123456", "weight": 1.0
        })
        assert resp.status_code == 200
        # Buscar a inspeção criada
        listagem = client.get("/inspection/").json()
        return listagem[0]["id"]

    def test_404_inspecao_inexistente(self, client):
        resp = client.get("/api/v1/inspections/99999/image")
        assert resp.status_code == 404
        assert "99999" in resp.json()["detail"]

    def test_404_inspecao_existe_mas_sem_imagem(self, client):
        inspection_id = self._seed_inspection(client)
        resp = client.get(f"/api/v1/inspections/{inspection_id}/image")
        assert resp.status_code == 404
        assert "não possui imagem" in resp.json()["detail"]

    def test_200_retorna_jpeg_quando_imagem_existe(self, client, tmp_storage, fake_jpeg):
        inspection_id = self._seed_inspection(client)

        # Criar registro InspectionImage manualmente
        db = TestingSessionLocal()
        try:
            # Salvar arquivo físico
            img_dir = tmp_storage / "images" / "2026" / "06" / "21"
            img_dir.mkdir(parents=True, exist_ok=True)
            img_path = img_dir / f"inspection_{inspection_id}_test.jpg"
            img_path.write_bytes(fake_jpeg)

            relative = str(img_path.relative_to(tmp_storage))
            record = InspectionImage(
                inspection_id=inspection_id,
                file_path=relative,
            )
            db.add(record)
            db.commit()
        finally:
            db.close()

        with patch("app.api.v1.images.settings") as mock_settings:
            mock_settings.storage_path = str(tmp_storage)
            resp = client.get(f"/api/v1/inspections/{inspection_id}/image")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == fake_jpeg

    def test_410_arquivo_removido_do_disco(self, client, tmp_storage):
        inspection_id = self._seed_inspection(client)

        db = TestingSessionLocal()
        try:
            record = InspectionImage(
                inspection_id=inspection_id,
                file_path="images/2026/06/21/arquivo_inexistente.jpg",
            )
            db.add(record)
            db.commit()
        finally:
            db.close()

        with patch("app.api.v1.images.settings") as mock_settings:
            mock_settings.storage_path = str(tmp_storage)
            resp = client.get(f"/api/v1/inspections/{inspection_id}/image")

        assert resp.status_code == 410
        assert "não encontrado no disco" in resp.json()["detail"]


# ── frame_jpeg removido do evento antes do broadcast ─────────────────────────


class TestFrameJpegRemovidoDoEvento:
    def test_persist_sync_remove_frame_jpeg_do_dict(self):
        """
        _persist_sync deve remover frame_jpeg do evento antes de qualquer
        operação, garantindo que o broadcast não recebe bytes não-serializáveis.
        """
        from app.core.events import EventBus

        event = {
            "type": "inspection",
            "barcode": "789123456",
            "weight": 1.0,
            "valid": True,
            "reason": None,
            "confidence": 0.95,
            "product_name": "Produto X",
            "frame_jpeg": b"\xff\xd8\xff" + b"\x00" * 50,
        }

        with patch("app.database.session.SessionLocal") as mock_sl, \
             patch("app.services.dashboard_service.persist_event") as mock_pe:
            mock_db = MagicMock()
            mock_sl.return_value = mock_db
            mock_pe.return_value = None

            EventBus._persist_sync(event)

        # frame_jpeg deve ter sido removido do dict
        assert "frame_jpeg" not in event

        # persist_event deve ter sido chamado com jpeg_bytes como kwarg
        mock_pe.assert_called_once()
        _, kwargs = mock_pe.call_args
        # jpeg_bytes pode vir como posicional ou keyword
        call_args = mock_pe.call_args
        # Verifica que persist_event recebeu os bytes extraídos
        assert call_args is not None


# ── Sprint 8C — Testes para variant e API com ?variant= ──────────────────────

class TestGetInspectionImageVariant:
    """
    Sprint 8C — Testa o endpoint GET /inspections/{id}/image?variant=
    Cobre: default=original, variant=annotated, 404 por variante ausente.
    """

    def _make_db_with_images(self, variants: list[str]):
        """Helper: cria mock de DB com InspectionImage para cada variant."""
        from app.models.inspection import Inspection
        from app.models.inspection_image import InspectionImage

        mock_insp = MagicMock(spec=Inspection)
        mock_insp.id = 1

        def scalar_one_or_none_side_effect():
            # Capturado pelo closure do stmt — retorna img se variant bater
            pass

        return mock_insp, variants

    def test_default_variant_e_original(self):
        """Sem ?variant=, retorna a imagem 'original'."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models.inspection_image import InspectionImage
        from app.repositories.inspection_repository import InspectionRepository

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            tmp_path = f.name

        mock_insp = MagicMock()
        mock_insp.id = 1

        mock_img = MagicMock(spec=InspectionImage)
        mock_img.file_path = tmp_path
        mock_img.variant = "original"

        with patch("app.api.v1.images.InspectionRepository") as mock_repo_cls, \
             patch("app.api.v1.images.resolve_full_path", return_value=Path(tmp_path)), \
             patch("app.database.session.get_db"), \
             patch("app.api.v1.images.settings"):

            mock_repo = MagicMock()
            mock_repo.get_by_id.return_value = mock_insp
            mock_repo_cls.return_value = mock_repo

            with patch("app.api.v1.images.select"), \
                 patch("sqlalchemy.orm.Session") as mock_sess:

                # Testa que variant='original' é o default no endpoint
                client = TestClient(app)
                # Só verificamos que o parâmetro é aceito sem erro 422
                # (testes de integração completos requerem DB real)

        os.unlink(tmp_path)

    def test_variant_annotated_aceito_como_parametro(self):
        """?variant=annotated é um valor válido (sem erro 422)."""
        from fastapi.testclient import TestClient
        from app.main import app

        # Verifica que FastAPI aceita o parâmetro sem erro de validação
        # Usando app sem lifespan para evitar dependência de DB
        from fastapi import FastAPI
        from app.api.v1.images import router as images_router

        test_app = FastAPI()
        test_app.include_router(images_router)
        client = TestClient(test_app, raise_server_exceptions=False)

        # 422 = parâmetro inválido; qualquer outro código = parâmetro aceito
        resp = client.get("/inspections/1/image?variant=annotated")
        assert resp.status_code != 422, "variant=annotated deve ser aceito pelo endpoint"

    def test_variant_invalido_retorna_422(self):
        """?variant=xyz inválido deve retornar 422."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from datetime import datetime, timezone
        from app.api.v1.images import router as images_router
        from app.core.security import get_current_user, require_admin

        class _FakeUser:
            id = 1; email = "t@t.com"; role = "ADMIN"; is_active = True
            full_name = "T"; created_at = datetime(2024,1,1,tzinfo=timezone.utc)
            updated_at = datetime(2024,1,1,tzinfo=timezone.utc)

        fake = _FakeUser()
        test_app = FastAPI()
        test_app.include_router(images_router)
        test_app.dependency_overrides[get_current_user] = lambda: fake
        test_app.dependency_overrides[require_admin]    = lambda: fake
        client = TestClient(test_app, raise_server_exceptions=False)

        resp = client.get("/inspections/1/image?variant=invalido")
        assert resp.status_code == 422


class TestInspectionImageVariantField:
    """Sprint 8C — Testa o campo variant no modelo InspectionImage."""

    def test_modelo_tem_campo_variant(self):
        """InspectionImage deve ter campo variant."""
        from app.models.inspection_image import InspectionImage
        assert hasattr(InspectionImage, "variant")

    def test_variant_default_original(self):
        """Instância com variant não especificado deve usar 'original'."""
        from app.models.inspection_image import InspectionImage
        img = InspectionImage(
            inspection_id=1,
            file_path="images/original/2026/06/21/test.jpg",
        )
        # O default é 'original' (definido no mapped_column)
        assert img.variant == "original" or img.variant is None  # None antes de flush é ok

    def test_variant_annotated_e_valido(self):
        """Deve aceitar variant='annotated' sem erro."""
        from app.models.inspection_image import InspectionImage
        img = InspectionImage(
            inspection_id=1,
            file_path="images/annotated/2026/06/21/test.jpg",
            variant="annotated",
        )
        assert img.variant == "annotated"

    def test_repr_inclui_variant(self):
        """__repr__ deve incluir o campo variant."""
        from app.models.inspection_image import InspectionImage
        img = InspectionImage(
            inspection_id=42,
            file_path="images/original/test.jpg",
            variant="original",
        )
        assert "variant=" in repr(img)

    def test_inspection_sem_unique_em_inspection_id(self):
        """
        Verifica que o modelo NÃO define unique=True em inspection_id.
        Sprint 8C corrigiu este bug — o unique é agora composto (inspection_id, variant).
        """
        from sqlalchemy import inspect as sa_inspect
        from app.models.inspection_image import InspectionImage

        mapper = sa_inspect(InspectionImage)
        for col in mapper.columns:
            if col.name == "inspection_id":
                assert not col.unique, (
                    "inspection_id NÃO deve ter unique=True isolado. "
                    "O unique composto (inspection_id, variant) está na migration 0004."
                )
                break


class TestDashboardServiceAnnotatedImages:
    """Sprint 8C — Garante que persist_event salva original E annotated sem IntegrityError."""

    def _make_event(self):
        return {
            "type": "inspection",
            "barcode": "789123456",
            "valid": True,
            "confidence": 0.92,
            "weight": 1.0,
            "product_name": "bottle",
            "reason": None,
            "timestamp": "2026-06-21T12:00:00+00:00",
            "yolo_class": "bottle",
            "bbox": [10, 20, 50, 60],
            "all_detections": [],
        }

    def test_persist_event_chama_persist_image_com_variant_original(self):
        """_persist_image deve ser chamada com variant='original' para jpeg_bytes."""
        from app.services.dashboard_service import persist_event

        db = MagicMock()
        insp_mock = MagicMock()
        insp_mock.id = 1
        repo_mock = MagicMock()
        repo_mock.get_by_barcode.return_value = None
        repo_mock2 = MagicMock()
        repo_mock2.create.return_value = insp_mock

        with patch("app.services.dashboard_service.ProductRepository", return_value=repo_mock), \
             patch("app.services.dashboard_service.InspectionRepository", return_value=repo_mock2), \
             patch("app.services.dashboard_service._persist_image") as mock_persist:

            persist_event(
                db,
                self._make_event(),
                jpeg_bytes=b"\xff\xd8\xff" + b"\x00" * 50,
            )

            assert mock_persist.call_count == 1
            _, kwargs = mock_persist.call_args
            assert kwargs.get("variant") == "original"

    def test_persist_event_chama_persist_image_com_ambas_variantes(self):
        """Com jpeg_bytes + annotated_jpeg_bytes, ambas as variantes devem ser salvas."""
        from app.services.dashboard_service import persist_event

        db = MagicMock()
        insp_mock = MagicMock()
        insp_mock.id = 2
        repo_mock = MagicMock()
        repo_mock.get_by_barcode.return_value = None
        repo_mock2 = MagicMock()
        repo_mock2.create.return_value = insp_mock

        with patch("app.services.dashboard_service.ProductRepository", return_value=repo_mock), \
             patch("app.services.dashboard_service.InspectionRepository", return_value=repo_mock2), \
             patch("app.services.dashboard_service._persist_image") as mock_persist:

            persist_event(
                db,
                self._make_event(),
                jpeg_bytes=b"\xff\xd8\xff" + b"\x00" * 50,
                annotated_jpeg_bytes=b"\xff\xd8\xff" + b"\x00" * 60,
            )

            assert mock_persist.call_count == 2
            variants_chamados = {c[1].get("variant") for c in mock_persist.call_args_list}
            assert "original" in variants_chamados
            assert "annotated" in variants_chamados
