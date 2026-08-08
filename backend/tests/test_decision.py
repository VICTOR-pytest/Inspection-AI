"""
tests/test_decision.py
-----------------------
Sprint 9A — Testes do fluxo de decisão humana.

Cobre:
  1. DecisionRequest (schema Pydantic)
     - APPROVED aceito sem reason
     - APPROVED aceito com reason
     - REJECTED exige reason
     - REJECTED com reason válida
     - decision inválido rejeitado
     - reason com espaços é normalizada / rejeitada se só espaços

  2. InspectionRepository.update_decision()
     - atualiza decision, decision_reason, reviewed_at
     - retorna None para ID inexistente
     - reviewed_at é preenchido automaticamente

  3. InspectionRepository.count_by_decision()
     - conta corretamente por status
     - retorna 0 quando nenhum resultado

  4. POST /api/v1/inspections/{id}/decision
     - 200 para APPROVED
     - 200 para REJECTED com reason
     - 422 para REJECTED sem reason
     - 422 para decision inválido
     - 404 para ID inexistente
     - reviewed_at presente na resposta

  5. dashboard_service — métricas de decisão
     - approval_rate calculado corretamente
     - rejection_rate calculado corretamente
     - sem divisão por zero quando sem decisões
     - campos presentes em MetricsResponse e DashboardResponse

  6. Regressão — campos de decisão nos schemas existentes
     - InspectionRead tem os novos campos com defaults
     - InspectionItem.from_orm_inspection() mapeia decisão
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Garante que o backend seja encontrado
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_inspection(
    id: int = 1,
    decision: str = "PENDING",
    decision_reason: str | None = None,
    reviewed_at: datetime | None = None,
) -> MagicMock:
    insp = MagicMock()
    insp.id = id
    insp.barcode = "789123456"
    insp.weight = 1.0
    insp.is_valid = True
    insp.confidence = 0.92
    insp.product_name = "bottle"
    insp.reason = None
    insp.created_at = datetime(2026, 6, 22, 12, 0, 0)
    insp.decision = decision
    insp.decision_reason = decision_reason
    insp.reviewed_at = reviewed_at
    return insp


# ── 1. Schema — DecisionRequest ───────────────────────────────────────────────

class TestDecisionRequest:

    def test_approved_sem_reason(self):
        from app.schemas.decision import DecisionRequest
        r = DecisionRequest(decision="APPROVED")
        assert r.decision.value == "APPROVED"
        assert r.reason is None

    def test_approved_com_reason(self):
        from app.schemas.decision import DecisionRequest
        r = DecisionRequest(decision="APPROVED", reason="Dentro dos padrões")
        assert r.reason == "Dentro dos padrões"

    def test_rejected_sem_reason_falha(self):
        from app.schemas.decision import DecisionRequest
        with pytest.raises(Exception) as exc_info:
            DecisionRequest(decision="REJECTED")
        assert "reason" in str(exc_info.value).lower() or "REJECTED" in str(exc_info.value)

    def test_rejected_com_reason_valida(self):
        from app.schemas.decision import DecisionRequest
        r = DecisionRequest(decision="REJECTED", reason="Rótulo danificado")
        assert r.decision.value == "REJECTED"
        assert r.reason == "Rótulo danificado"

    def test_decision_invalido_falha(self):
        from app.schemas.decision import DecisionRequest
        with pytest.raises(Exception):
            DecisionRequest(decision="INVALIDO")

    def test_rejected_com_reason_so_espacos_falha(self):
        from app.schemas.decision import DecisionRequest
        with pytest.raises(Exception):
            DecisionRequest(decision="REJECTED", reason="   ")

    def test_reason_normalizada_remove_espacos(self):
        from app.schemas.decision import DecisionRequest
        r = DecisionRequest(decision="APPROVED", reason="  ok  ")
        assert r.reason == "ok"

    def test_pending_aceito(self):
        from app.schemas.decision import DecisionRequest
        r = DecisionRequest(decision="PENDING")
        assert r.decision.value == "PENDING"

    def test_decision_case_sensitive(self):
        """Valores em lowercase devem ser rejeitados pelo enum."""
        from app.schemas.decision import DecisionRequest
        with pytest.raises(Exception):
            DecisionRequest(decision="approved")


# ── 2. Repositório — update_decision ─────────────────────────────────────────

class TestInspectionRepositoryDecision:

    def _make_repo(self, inspection=None):
        from app.repositories.inspection_repository import InspectionRepository
        db = MagicMock()
        repo = InspectionRepository(db)
        repo.get_by_id = MagicMock(return_value=inspection)
        return repo, db

    def test_update_decision_approved(self):
        from app.repositories.inspection_repository import InspectionRepository
        insp = _make_inspection()
        repo, db = self._make_repo(inspection=insp)

        result = repo.update_decision(1, "APPROVED")

        assert result is insp
        assert insp.decision == "APPROVED"
        assert insp.decision_reason is None
        assert insp.reviewed_at is not None
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(insp)

    def test_update_decision_rejected_com_reason(self):
        from app.repositories.inspection_repository import InspectionRepository
        insp = _make_inspection()
        repo, db = self._make_repo(inspection=insp)

        result = repo.update_decision(1, "REJECTED", "Rótulo danificado")

        assert insp.decision == "REJECTED"
        assert insp.decision_reason == "Rótulo danificado"
        assert insp.reviewed_at is not None

    def test_update_decision_retorna_none_para_id_inexistente(self):
        from app.repositories.inspection_repository import InspectionRepository
        repo, db = self._make_repo(inspection=None)

        result = repo.update_decision(999, "APPROVED")

        assert result is None
        db.commit.assert_not_called()

    def test_reviewed_at_e_utc_e_recente(self):
        from app.repositories.inspection_repository import InspectionRepository
        insp = _make_inspection()
        repo, db = self._make_repo(inspection=insp)

        before = datetime.now(timezone.utc).replace(tzinfo=None)
        repo.update_decision(1, "APPROVED")
        after = datetime.now(timezone.utc).replace(tzinfo=None)

        # reviewed_at deve estar entre before e after
        assert insp.reviewed_at is not None
        reviewed = insp.reviewed_at.replace(tzinfo=None) if insp.reviewed_at.tzinfo else insp.reviewed_at
        assert before <= reviewed <= after

    def test_decisao_pode_ser_sobrescrita(self):
        """Operador pode corrigir decisão anterior."""
        from app.repositories.inspection_repository import InspectionRepository
        insp = _make_inspection(decision="APPROVED")
        repo, db = self._make_repo(inspection=insp)

        repo.update_decision(1, "REJECTED", "Corrigido: produto com defeito")

        assert insp.decision == "REJECTED"
        assert insp.decision_reason == "Corrigido: produto com defeito"


# ── 3. Repositório — count_by_decision ───────────────────────────────────────

class TestCountByDecision:

    def test_count_by_decision_retorna_inteiro(self):
        from app.repositories.inspection_repository import InspectionRepository
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 5
        repo = InspectionRepository(db)
        assert repo.count_by_decision("APPROVED") == 5

    def test_count_by_decision_zero(self):
        from app.repositories.inspection_repository import InspectionRepository
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 0
        repo = InspectionRepository(db)
        assert repo.count_by_decision("REJECTED") == 0


# ── 4. Endpoint POST /api/v1/inspections/{id}/decision ───────────────────────

class TestDecisionEndpoint:
    """
    Testes do endpoint POST /api/v1/inspections/{id}/decision.

    Sprint 9B.1: cada teste cria um FastAPI() isolado e injeta
    dependency_overrides para get_current_user e get_db, garantindo
    que a autenticação seja bypassada sem alterar a lógica de negócio.
    """

    def _make_isolated_app_with_auth_bypass(self):
        """
        Cria app FastAPI isolado com router de decisão e auth bypassada.
        Retorna (app, fake_user) para uso nos testes.
        """
        from fastapi import FastAPI
        from app.api.v1.decision import router
        from app.core.security import get_current_user, require_admin
        from datetime import datetime, timezone

        class _FakeUser:
            id            = 1
            email         = "test-admin@inspection.ai"
            full_name     = "Admin Teste"
            role          = "ADMIN"
            is_active     = True
            created_at    = datetime(2024, 1, 1, tzinfo=timezone.utc)
            updated_at    = datetime(2024, 1, 1, tzinfo=timezone.utc)

        fake_user = _FakeUser()
        isolated_app = FastAPI()
        isolated_app.include_router(router)
        isolated_app.dependency_overrides[get_current_user] = lambda: fake_user
        isolated_app.dependency_overrides[require_admin]    = lambda: fake_user
        return isolated_app, fake_user

    def _make_db_and_repo(self, inspection=None):
        db = MagicMock()
        repo = MagicMock()
        repo.update_decision.return_value = inspection
        return db, repo

    def test_approved_retorna_200(self):
        from fastapi.testclient import TestClient
        insp = _make_inspection(decision="APPROVED")
        isolated_app, _ = self._make_isolated_app_with_auth_bypass()

        with patch("app.api.v1.decision.InspectionRepository") as mock_cls, \
             patch("app.api.v1.decision.DecisionRepository") as mock_dec_cls, \
             patch("app.api.v1.decision.get_db", return_value=MagicMock()):
            mock_cls.return_value.update_decision.return_value = insp
            mock_dec_cls.return_value.create.return_value = MagicMock()
            client = TestClient(isolated_app, raise_server_exceptions=False)
            resp = client.post("/inspections/1/decision", json={"decision": "APPROVED"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "APPROVED"
        assert data["id"] == 1

    def test_rejected_com_reason_retorna_200(self):
        from fastapi.testclient import TestClient
        insp = _make_inspection(decision="REJECTED", decision_reason="Rótulo danificado")
        isolated_app, _ = self._make_isolated_app_with_auth_bypass()

        with patch("app.api.v1.decision.InspectionRepository") as mock_cls, \
             patch("app.api.v1.decision.DecisionRepository") as mock_dec_cls, \
             patch("app.api.v1.decision.get_db", return_value=MagicMock()):
            mock_cls.return_value.update_decision.return_value = insp
            mock_dec_cls.return_value.create.return_value = MagicMock()
            client = TestClient(isolated_app, raise_server_exceptions=False)
            resp = client.post(
                "/inspections/1/decision",
                json={"decision": "REJECTED", "reason": "Rótulo danificado"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "REJECTED"
        assert data["decision_reason"] == "Rótulo danificado"

    def test_rejected_sem_reason_retorna_422(self):
        from fastapi.testclient import TestClient
        isolated_app, _ = self._make_isolated_app_with_auth_bypass()
        client = TestClient(isolated_app, raise_server_exceptions=False)

        with patch("app.api.v1.decision.get_db", return_value=MagicMock()):
            resp = client.post("/inspections/1/decision", json={"decision": "REJECTED"})

        assert resp.status_code == 422

    def test_decision_invalido_retorna_422(self):
        from fastapi.testclient import TestClient
        isolated_app, _ = self._make_isolated_app_with_auth_bypass()
        client = TestClient(isolated_app, raise_server_exceptions=False)

        with patch("app.api.v1.decision.get_db", return_value=MagicMock()):
            resp = client.post("/inspections/1/decision", json={"decision": "INVALIDO"})

        assert resp.status_code == 422

    def test_id_inexistente_retorna_404(self):
        from fastapi.testclient import TestClient
        isolated_app, _ = self._make_isolated_app_with_auth_bypass()

        with patch("app.api.v1.decision.InspectionRepository") as mock_cls, \
             patch("app.api.v1.decision.DecisionRepository") as mock_dec_cls, \
             patch("app.api.v1.decision.get_db", return_value=MagicMock()):
            mock_cls.return_value.update_decision.return_value = None
            mock_dec_cls.return_value.create.return_value = MagicMock()
            client = TestClient(isolated_app, raise_server_exceptions=False)
            resp = client.post("/inspections/999/decision", json={"decision": "APPROVED"})

        assert resp.status_code == 404
        assert "999" in resp.json()["detail"]

    def test_reviewed_at_presente_na_resposta(self):
        from fastapi.testclient import TestClient
        reviewed = datetime(2026, 6, 22, 15, 30, 0)
        insp = _make_inspection(decision="APPROVED", reviewed_at=reviewed)
        isolated_app, _ = self._make_isolated_app_with_auth_bypass()

        with patch("app.api.v1.decision.InspectionRepository") as mock_cls, \
             patch("app.api.v1.decision.DecisionRepository") as mock_dec_cls, \
             patch("app.api.v1.decision.get_db", return_value=MagicMock()):
            mock_cls.return_value.update_decision.return_value = insp
            mock_dec_cls.return_value.create.return_value = MagicMock()
            client = TestClient(isolated_app, raise_server_exceptions=False)
            resp = client.post("/inspections/1/decision", json={"decision": "APPROVED"})

        assert resp.status_code == 200
        assert resp.json()["reviewed_at"] is not None

    def test_payload_vazio_retorna_422(self):
        from fastapi.testclient import TestClient
        isolated_app, _ = self._make_isolated_app_with_auth_bypass()
        client = TestClient(isolated_app, raise_server_exceptions=False)

        with patch("app.api.v1.decision.get_db", return_value=MagicMock()):
            resp = client.post("/inspections/1/decision", json={})

        assert resp.status_code == 422


# ── 5. Dashboard service — métricas de decisão ───────────────────────────────

class TestDashboardDecisionMetrics:

    def _make_repo_mock(
        self,
        total=10, valid=8, invalid=2,
        dec_approved=5, dec_rejected=3, dec_pending=2,
    ):
        repo = MagicMock()
        # Métodos legados (mantidos para compatibilidade)
        repo.count_total.return_value = total
        repo.count_by_validity.side_effect = lambda v: valid if v else invalid
        repo.count_by_decision.side_effect = lambda d: {
            "APPROVED": dec_approved,
            "REJECTED": dec_rejected,
            "PENDING":  dec_pending,
        }.get(d, 0)
        repo.hourly_breakdown.return_value = []

        # Sprint 9B.3 — métodos consolidados usados por get_metrics() e get_dashboard()
        repo.get_aggregate_stats.return_value = {
            "total":         total,
            "valid_count":   valid,
            "invalid_count": invalid,
            "dec_approved":  dec_approved,
            "dec_rejected":  dec_rejected,
            "dec_pending":   dec_pending,
        }
        repo.hourly_breakdown_sql.return_value = []
        return repo

    def test_metricas_incluem_campos_de_decisao(self):
        from app.services.dashboard_service import get_metrics

        db = MagicMock()
        with patch("app.services.dashboard_service.InspectionRepository",
                   return_value=self._make_repo_mock()):
            metrics = get_metrics(db)

        assert metrics.decision_approved == 5
        assert metrics.decision_rejected == 3
        assert metrics.decision_pending == 2

    def test_approval_rate_calculado_corretamente(self):
        from app.services.dashboard_service import get_metrics

        db = MagicMock()
        # 5 approved, 5 rejected → 50% approval rate
        repo = self._make_repo_mock(dec_approved=5, dec_rejected=5, dec_pending=0)
        with patch("app.services.dashboard_service.InspectionRepository", return_value=repo):
            metrics = get_metrics(db)

        assert metrics.approval_rate == 0.5
        assert metrics.rejection_rate == 0.5

    def test_sem_decisoes_nao_divide_por_zero(self):
        from app.services.dashboard_service import get_metrics

        db = MagicMock()
        repo = self._make_repo_mock(dec_approved=0, dec_rejected=0, dec_pending=10)
        with patch("app.services.dashboard_service.InspectionRepository", return_value=repo):
            metrics = get_metrics(db)

        assert metrics.approval_rate == 0.0
        assert metrics.rejection_rate == 0.0

    def test_dashboard_inclui_campos_de_decisao(self):
        from app.services.dashboard_service import get_dashboard

        db = MagicMock()
        with patch("app.services.dashboard_service.InspectionRepository",
                   return_value=self._make_repo_mock()):
            dashboard = get_dashboard(db)

        assert hasattr(dashboard, "decision_approved")
        assert hasattr(dashboard, "decision_rejected")
        assert hasattr(dashboard, "decision_pending")
        assert hasattr(dashboard, "approval_rate")
        assert hasattr(dashboard, "rejection_rate")


# ── 6. Regressão — schemas existentes com campos novos ───────────────────────

class TestDecisionFieldsRegressao:

    def test_inspection_read_tem_campos_de_decisao(self):
        from app.schemas.inspection import InspectionRead
        fields = InspectionRead.model_fields
        assert "decision" in fields
        assert "decision_reason" in fields
        assert "reviewed_at" in fields

    def test_inspection_read_decision_default_pending(self):
        from app.schemas.inspection import InspectionRead
        insp = InspectionRead(
            id=1, barcode="789", weight=1.0, is_valid=True,
            reason=None, created_at=datetime.now(), product_id=None,
        )
        assert insp.decision == "PENDING"
        assert insp.decision_reason is None
        assert insp.reviewed_at is None

    def test_inspection_item_from_orm_mapeia_decisao(self):
        from app.schemas.dashboard import InspectionItem
        insp = _make_inspection(decision="APPROVED", decision_reason="OK")
        item = InspectionItem.from_orm_inspection(insp)
        assert item.decision == "APPROVED"
        assert item.decision_reason == "OK"

    def test_inspection_item_from_orm_sem_decisao_usa_pending(self):
        """ORM sem campo decision (banco antigo) deve usar default PENDING."""
        from app.schemas.dashboard import InspectionItem
        insp = _make_inspection()
        # Remove o atributo decision do mock para simular ORM sem campo
        del insp.decision
        item = InspectionItem.from_orm_inspection(insp)
        assert item.decision == "PENDING"

    def test_decision_status_enum_valores(self):
        from app.models.inspection import DecisionStatus
        assert DecisionStatus.PENDING.value == "PENDING"
        assert DecisionStatus.APPROVED.value == "APPROVED"
        assert DecisionStatus.REJECTED.value == "REJECTED"

    def test_inspection_model_tem_campos_de_decisao(self):
        from app.models.inspection import Inspection
        assert hasattr(Inspection, "decision")
        assert hasattr(Inspection, "decision_reason")
        assert hasattr(Inspection, "reviewed_at")


# ── Sprint 9A.1 — Testes de hardening ────────────────────────────────────────

class TestVariantPersistenciaCorreta:
    """
    Sprint 9A.1 — Bug 1: variant não era gravado no InspectionImage.
    Garante que original e annotated são gravados com variant correto.
    """

    def _make_persist_mocks(self, inspection_id: int = 1):
        db = MagicMock()
        insp = _make_inspection(id=inspection_id)
        repo_product = MagicMock()
        repo_product.get_by_barcode.return_value = None
        repo_inspection = MagicMock()
        repo_inspection.create.return_value = insp
        return db, insp, repo_product, repo_inspection

    def test_persist_image_original_grava_variant_original(self, tmp_path):
        """_persist_image com variant='original' deve criar InspectionImage com variant='original'."""
        from app.services.dashboard_service import _persist_image

        insp = _make_inspection(id=1)
        jpeg = b"\xff\xd8\xff" + b"\x00" * 50
        db = MagicMock()
        criados = []
        db.add.side_effect = lambda obj: criados.append(obj)

        # save_frame_bytes e settings são importados LOCALMENTE em _persist_image
        with patch("app.core.config.settings") as mock_settings, \
             patch("app.services.image_storage.save_frame_bytes",
                   return_value="images/original/2026/test.jpg") as mock_save:
            mock_settings.storage_path = str(tmp_path)
            # Patch direto no import local — importar o módulo e substituir no sys.modules
            import sys
            import app.services.image_storage as img_storage_mod
            original_fn = img_storage_mod.save_frame_bytes
            img_storage_mod.save_frame_bytes = mock_save
            try:
                _persist_image(db, insp, jpeg, variant="original")
            finally:
                img_storage_mod.save_frame_bytes = original_fn

        assert len(criados) == 1
        assert criados[0].variant == "original", \
            f"Esperado variant='original', obtido '{criados[0].variant}'"

    def test_persist_image_annotated_grava_variant_annotated(self, tmp_path):
        """
        Sprint 9A.1 — Fix do Bug 1.
        _persist_image com variant='annotated' deve criar InspectionImage com variant='annotated'.
        Antes do fix, o campo ficava com o default 'original' porque não era passado ao construtor.
        """
        from app.services.dashboard_service import _persist_image
        import app.services.image_storage as img_storage_mod

        insp = _make_inspection(id=1)
        jpeg = b"\xff\xd8\xff" + b"\x00" * 50
        db = MagicMock()
        criados = []
        db.add.side_effect = lambda obj: criados.append(obj)

        mock_save = MagicMock(return_value="images/annotated/2026/test.jpg")
        original_fn = img_storage_mod.save_frame_bytes
        img_storage_mod.save_frame_bytes = mock_save
        try:
            with patch("app.core.config.settings") as mock_settings:
                mock_settings.storage_path = str(tmp_path)
                _persist_image(db, insp, jpeg, variant="annotated")
        finally:
            img_storage_mod.save_frame_bytes = original_fn

        assert len(criados) == 1
        assert criados[0].variant == "annotated", \
            f"Bug 9A.1: variant='annotated' não foi gravado. Obtido: '{criados[0].variant}'"

    def test_persist_event_grava_duas_variantes_distintas(self):
        """persist_event com jpeg_bytes + annotated_jpeg_bytes deve chamar _persist_image com variantes distintas."""
        from app.services.dashboard_service import persist_event

        db = MagicMock()
        insp = _make_inspection(id=5)
        repo_p = MagicMock()
        repo_p.get_by_barcode.return_value = None
        repo_i = MagicMock()
        repo_i.create.return_value = insp

        event = {
            "type": "inspection", "barcode": "789123456", "valid": True,
            "confidence": 0.9, "weight": 1.0, "product_name": "bottle",
            "reason": None, "timestamp": "2026-06-22T12:00:00+00:00",
            "yolo_class": "bottle", "bbox": None, "all_detections": [],
        }

        variantes_chamadas = []

        def capture_persist_image(db, insp, jpeg, variant="original"):
            variantes_chamadas.append(variant)

        with patch("app.services.dashboard_service.ProductRepository", return_value=repo_p), \
             patch("app.services.dashboard_service.InspectionRepository", return_value=repo_i), \
             patch("app.services.dashboard_service._persist_image", side_effect=capture_persist_image):

            persist_event(
                db, event,
                jpeg_bytes=b"\xff\xd8" + b"\x00" * 30,
                annotated_jpeg_bytes=b"\xff\xd8" + b"\x00" * 40,
            )

        assert "original" in variantes_chamadas, "variant='original' não foi chamado"
        assert "annotated" in variantes_chamadas, "variant='annotated' não foi chamado"
        assert variantes_chamadas.count("original") == 1
        assert variantes_chamadas.count("annotated") == 1


class TestInspectionIdNoWebSocket:
    """
    Sprint 9A.1 — Bug 2: inspection_id ausente no broadcast WS.
    Garante que após _persist_sync, o evento contém inspection_id.
    """

    def test_persist_sync_adiciona_inspection_id_ao_evento(self):
        """Após _persist_sync, o evento deve conter inspection_id da inspeção persistida."""
        from app.core.events import EventBus

        event = {
            "type": "inspection",
            "barcode": "789123456",
            "valid": True,
            "confidence": 0.9,
            "weight": 1.0,
            "product_name": "bottle",
            "reason": None,
            "timestamp": "2026-06-22T12:00:00+00:00",
            "yolo_class": "bottle",
            "bbox": None,
            "all_detections": [],
            "frame_jpeg": b"fake",
            "annotated_frame_jpeg": b"fake_ann",
        }

        insp_mock = _make_inspection(id=42)

        with patch("app.database.session.SessionLocal"), \
             patch("app.services.dashboard_service.persist_event", return_value=insp_mock):
            EventBus._persist_sync(event)

        assert "inspection_id" in event, \
            "inspection_id deve estar presente no evento após _persist_sync"
        assert event["inspection_id"] == 42, \
            f"Esperado inspection_id=42, obtido {event.get('inspection_id')}"

    def test_persist_sync_inspection_id_none_quando_persist_falha(self):
        """Se persist_event retornar None, inspection_id não é adicionado."""
        from app.core.events import EventBus

        event = {
            "type": "inspection",
            "barcode": "INVALIDO",
            "valid": False,
            "confidence": 0.0,
            "weight": 0.0,
            "product_name": None,
            "reason": "falha",
            "timestamp": "2026-06-22T12:00:00+00:00",
            "yolo_class": None,
            "bbox": None,
            "all_detections": [],
            "frame_jpeg": None,
            "annotated_frame_jpeg": None,
        }

        with patch("app.database.session.SessionLocal"), \
             patch("app.services.dashboard_service.persist_event", return_value=None):
            EventBus._persist_sync(event)

        # Não deve ter inspection_id se persist retornou None
        assert event.get("inspection_id") is None or "inspection_id" not in event

    def test_inspection_id_serializavel_em_json(self):
        """inspection_id deve ser serializável em JSON (int, não objeto SQLAlchemy)."""
        import json
        from app.core.events import EventBus

        event = {
            "type": "inspection",
            "barcode": "789123456",
            "valid": True,
            "confidence": 0.9,
            "weight": 1.0,
            "product_name": "bottle",
            "reason": None,
            "timestamp": "2026-06-22T12:00:00+00:00",
            "yolo_class": None,
            "bbox": None,
            "all_detections": [],
            "frame_jpeg": None,
            "annotated_frame_jpeg": None,
        }

        insp_mock = _make_inspection(id=99)

        with patch("app.database.session.SessionLocal"), \
             patch("app.services.dashboard_service.persist_event", return_value=insp_mock):
            EventBus._persist_sync(event)

        # Deve serializar sem TypeError
        json_str = json.dumps(event)
        parsed = json.loads(json_str)
        assert parsed["inspection_id"] == 99


class TestDecisionFieldsHardening:
    """
    Sprint 9A.1 — Garante que campos de decisão estão corretamente
    tipados e presentes em todos os contratos de dados.
    """

    def test_live_metrics_interface_tem_campos_de_decisao(self):
        """
        Valida (via schema Python) que MetricsResponse tem todos os campos
        que o frontend LiveMetrics espera.
        """
        from app.schemas.dashboard import MetricsResponse
        fields = MetricsResponse.model_fields
        assert "decision_approved" in fields
        assert "decision_rejected" in fields
        assert "decision_pending" in fields
        assert "approval_rate" in fields
        assert "rejection_rate" in fields

    def test_metrics_response_defaults_corretos(self):
        """Campos de decisão têm default=0 / 0.0 para não quebrar dashboards sem histórico."""
        from app.schemas.dashboard import MetricsResponse
        m = MetricsResponse(total=0, approved=0, rejected=0, error_rate=0.0, fps=0.0)
        assert m.decision_approved == 0
        assert m.decision_rejected == 0
        assert m.decision_pending == 0
        assert m.approval_rate == 0.0
        assert m.rejection_rate == 0.0

    def test_dashboard_response_tem_campos_de_decisao(self):
        """DashboardResponse também deve ter os campos de métricas de decisão."""
        from app.schemas.dashboard import DashboardResponse
        fields = DashboardResponse.model_fields
        assert "decision_approved" in fields
        assert "approval_rate" in fields

    def test_inspection_image_variant_e_gravado_no_banco(self):
        """
        InspectionImage criado com variant explícito deve preservar o valor.
        Testa o fix do Bug 1 no nível do modelo.
        """
        from app.models.inspection_image import InspectionImage
        img = InspectionImage(
            inspection_id=1,
            file_path="images/annotated/2026/test.jpg",
            variant="annotated",
        )
        assert img.variant == "annotated", \
            "InspectionImage deve preservar variant='annotated' quando explicitamente definido"
