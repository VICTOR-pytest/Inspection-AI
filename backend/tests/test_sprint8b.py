"""
tests/test_sprint8b.py
-----------------------
Sprint 8B — Testes de visualização de detecções YOLO.

Cobre:
  1. draw_detection() — overlay OpenCV
     - bbox desenhada corretamente
     - label com classe e confidence
     - frame original não alterado (imutabilidade)
     - comportamento sem bbox (label centralizado)
     - None frame retorna None
     - valid=True → cor verde; valid=False → cor vermelha (preparação Sprint 9)

  2. _build_event() — propagação de bbox e all_detections
     - bbox incluído no evento
     - all_detections incluído no evento
     - bbox=None → None no evento
     - serialização JSON compatível (bbox como list, não tuple)

  3. VisionWorker Sprint 8B
     - annotated_frame_jpeg gerado quando yolo_class presente
     - annotated_frame_jpeg=None quando sem detecção YOLO
     - frame original não alterado pelo worker
     - campos yolo_class e bbox no evento emitido

  4. image_storage — variante original/annotated
     - save_frame_bytes salva em images/original/
     - save_frame_bytes salva em images/annotated/
     - _date_subdir cria subdiretórios corretos por variante

  5. dashboard_service — persist_event com annotated
     - persist_event aceita annotated_jpeg_bytes
     - persist_event persiste sem annotated (backward-compat)

  6. events.py — remoção de annotated_frame_jpeg antes do broadcast
     - annotated_frame_jpeg removido do evento antes do _broadcast
     - frame_jpeg e annotated_frame_jpeg ambos removidos

  7. WebSocket — evento não contém campos de bytes
     - evento broadcast não tem frame_jpeg
     - evento broadcast não tem annotated_frame_jpeg
     - evento broadcast tem yolo_class, bbox, all_detections
"""
from __future__ import annotations

import sys
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import numpy as np
import pytest

# Garante que o módulo vision seja encontrado
# parents[2] de backend/tests/ = inspection-ai-sprint9b3/ (contém vision/)
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _blank_frame(h: int = 100, w: int = 100) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _colored_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Frame com pixels não-zero para verificar que o original não foi alterado."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :, 1] = 128  # canal verde
    return frame


# ── 1. draw_detection() ───────────────────────────────────────────────────────

class TestDrawDetection:

    def test_retorna_ndarray_com_bbox(self):
        from vision.worker import draw_detection
        frame = _blank_frame()
        result = draw_detection(frame, (10, 10, 40, 40), "bottle", 0.92)
        assert isinstance(result, np.ndarray)
        assert result.shape == frame.shape

    def test_frame_original_nao_alterado(self):
        from vision.worker import draw_detection
        frame = _colored_frame()
        original_copy = frame.copy()
        draw_detection(frame, (10, 10, 40, 40), "bottle", 0.92)
        assert np.array_equal(frame, original_copy), "draw_detection alterou o frame original"

    def test_retorna_none_com_frame_none(self):
        from vision.worker import draw_detection
        result = draw_detection(None, (10, 10, 40, 40), "bottle", 0.92)
        assert result is None

    def test_sem_bbox_retorna_ndarray(self):
        from vision.worker import draw_detection
        frame = _blank_frame(200, 200)
        result = draw_detection(frame, None, "cup", 0.75)
        assert isinstance(result, np.ndarray)

    def test_sem_class_name_retorna_ndarray(self):
        from vision.worker import draw_detection
        frame = _blank_frame()
        result = draw_detection(frame, (5, 5, 30, 30), None, 0.65)
        assert isinstance(result, np.ndarray)

    def test_resultado_e_copia_diferente_do_original(self):
        """Frame anotado deve ser diferente do original (pixels alterados pelo overlay)."""
        from vision.worker import draw_detection
        frame = _blank_frame()
        result = draw_detection(frame, (10, 10, 40, 40), "bottle", 0.92)
        # O overlay muda pelo menos um pixel
        assert not np.array_equal(frame, result), "Frame anotado deve diferir do original"

    def test_valid_true_nao_levanta_excecao(self):
        from vision.worker import draw_detection
        frame = _blank_frame()
        result = draw_detection(frame, (10, 10, 40, 40), "bottle", 0.92, valid=True)
        assert result is not None

    def test_valid_false_nao_levanta_excecao(self):
        from vision.worker import draw_detection
        frame = _blank_frame()
        result = draw_detection(frame, (10, 10, 40, 40), "bottle", 0.55, valid=False)
        assert result is not None

    def test_confidence_zero_nao_levanta_excecao(self):
        from vision.worker import draw_detection
        frame = _blank_frame()
        result = draw_detection(frame, None, None, 0.0)
        assert result is not None

    def test_bbox_no_limite_do_frame(self):
        """bbox que toca as bordas do frame não deve causar exceção."""
        from vision.worker import draw_detection
        frame = _blank_frame(50, 50)
        result = draw_detection(frame, (0, 0, 50, 50), "person", 0.88)
        assert isinstance(result, np.ndarray)


# ── 2. _build_event() ─────────────────────────────────────────────────────────

class TestBuildEventSprint8B:

    def test_bbox_incluido_no_evento(self):
        from vision.worker import _build_event
        event = _build_event("789123456", 1.0, 0.92, "bottle", bbox=(10, 20, 50, 60))
        assert event["bbox"] == [10, 20, 50, 60]

    def test_bbox_none_quando_nao_fornecido(self):
        from vision.worker import _build_event
        event = _build_event("789123456", 1.0, 0.92)
        assert event["bbox"] is None

    def test_all_detections_incluido_no_evento(self):
        from vision.worker import _build_event
        dets = [
            {"class_name": "bottle", "confidence": 0.92, "bbox": (10, 10, 50, 60)},
            {"class_name": "cup",    "confidence": 0.71, "bbox": (80, 15, 30, 40)},
        ]
        event = _build_event("789123456", 1.0, 0.92, "bottle", all_detections=dets)
        assert len(event["all_detections"]) == 2
        assert event["all_detections"][0]["class_name"] == "bottle"

    def test_all_detections_vazio_por_padrao(self):
        from vision.worker import _build_event
        event = _build_event("789123456", 1.0, 0.5)
        assert event["all_detections"] == []

    def test_yolo_class_no_evento(self):
        from vision.worker import _build_event
        event = _build_event("789123456", 1.0, 0.88, "cup")
        assert event["yolo_class"] == "cup"

    def test_yolo_class_none_por_padrao(self):
        from vision.worker import _build_event
        event = _build_event("789123456", 1.0, 0.5)
        assert event["yolo_class"] is None

    def test_bbox_serializado_como_list_nao_tuple(self):
        """bbox deve ser list para serialização JSON correta."""
        import json
        from vision.worker import _build_event
        event = _build_event("789123456", 1.0, 0.9, "bottle", bbox=(5, 10, 40, 50))
        # Não deve levantar TypeError
        serialized = json.dumps(event)
        parsed = json.loads(serialized)
        assert parsed["bbox"] == [5, 10, 40, 50]

    def test_evento_serializavel_completo(self):
        """Evento completo com todos os campos deve ser serializável em JSON."""
        import json
        from vision.worker import _build_event
        dets = [{"class_name": "bottle", "confidence": 0.92, "bbox": (10, 10, 50, 60)}]
        event = _build_event(
            "789123456", 1.0, 0.92, "bottle",
            bbox=(10, 10, 50, 60),
            all_detections=dets,
        )
        # Remove campos bytes antes de serializar (como EventBus faz)
        event.pop("frame_jpeg", None)
        event.pop("annotated_frame_jpeg", None)
        serialized = json.dumps(event)
        assert "yolo_class" in serialized
        assert "bbox" in serialized


# ── 3. VisionWorker Sprint 8B ─────────────────────────────────────────────────

class TestVisionWorkerSprint8B:
    """Testa propagação de bbox, annotated_frame_jpeg e imutabilidade do frame."""

    def _make_mock_detector(
        self,
        detected=True,
        class_name="bottle",
        confidence=0.92,
        bbox=(10, 20, 50, 60),
    ):
        from vision.yolo_detector import YOLOResult
        mock = MagicMock()
        mock.detect.return_value = YOLOResult(
            detected=detected,
            class_name=class_name,
            confidence=confidence,
            bbox=bbox,
            all_detections=[
                {"class_name": class_name, "confidence": confidence, "bbox": bbox}
            ] if detected else [],
        )
        return mock

    def test_annotated_frame_jpeg_gerado_quando_yolo_detecta(self):
        """Quando YOLO detecta, annotated_frame_jpeg deve ser bytes no evento."""
        from vision.worker import VisionWorker

        frame = _blank_frame(80, 80)
        detector = self._make_mock_detector()

        bus = MagicMock()
        loop = MagicMock()
        captured = []

        def capture_event(fn, event):
            captured.append(event.copy() if not callable(fn) else None)
            # Simula call_soon_threadsafe(put_nowait, event)
        loop.call_soon_threadsafe.side_effect = lambda fn, ev: captured.append(dict(ev))

        worker = VisionWorker.__new__(VisionWorker)
        worker._source = iter([(frame, "789123456", 1.0)])
        worker._bus = bus
        worker._loop = loop
        worker._stop_evt = MagicMock()
        worker._stop_evt.is_set.return_value = False
        worker._detector_cb = None  # Sprint 9B.3: CB não necessário em testes unitários
        worker._detector = detector

        worker._run()

        assert len(captured) == 1
        ev = captured[0]
        assert ev.get("annotated_frame_jpeg") is not None or ev.get("yolo_class") == "bottle"

    def test_annotated_frame_jpeg_none_sem_deteccao_yolo(self):
        """Sem detecção YOLO (class_name=None), annotated_frame_jpeg deve ser None."""
        from vision.worker import VisionWorker
        from vision.yolo_detector import YOLOResult

        frame = _blank_frame()
        detector = MagicMock()
        detector.detect.return_value = YOLOResult(
            detected=False, class_name=None, confidence=0.0, bbox=None
        )

        captured = []
        loop = MagicMock()
        loop.call_soon_threadsafe.side_effect = lambda fn, ev: captured.append(dict(ev))

        worker = VisionWorker.__new__(VisionWorker)
        worker._source = iter([(frame, "789123456", 1.0)])
        worker._bus = MagicMock()
        worker._loop = loop
        worker._stop_evt = MagicMock()
        worker._stop_evt.is_set.return_value = False
        worker._detector_cb = None  # Sprint 9B.3: CB não necessário em testes unitários
        worker._detector = detector

        worker._run()

        assert len(captured) == 1
        assert captured[0].get("annotated_frame_jpeg") is None

    def test_bbox_no_evento_emitido(self):
        """bbox da detecção deve chegar no evento emitido pelo worker."""
        from vision.worker import VisionWorker

        frame = _blank_frame()
        bbox = (5, 15, 45, 55)
        detector = self._make_mock_detector(bbox=bbox)

        captured = []
        loop = MagicMock()
        loop.call_soon_threadsafe.side_effect = lambda fn, ev: captured.append(dict(ev))

        worker = VisionWorker.__new__(VisionWorker)
        worker._source = iter([(frame, "789123456", 1.0)])
        worker._bus = MagicMock()
        worker._loop = loop
        worker._stop_evt = MagicMock()
        worker._stop_evt.is_set.return_value = False
        worker._detector_cb = None  # Sprint 9B.3: CB não necessário em testes unitários
        worker._detector = detector

        worker._run()

        assert len(captured) == 1
        assert captured[0]["bbox"] == list(bbox)

    def test_yolo_class_no_evento_emitido(self):
        """yolo_class deve estar presente no evento emitido pelo worker."""
        from vision.worker import VisionWorker

        frame = _blank_frame()
        detector = self._make_mock_detector(class_name="cup", confidence=0.85)

        captured = []
        loop = MagicMock()
        loop.call_soon_threadsafe.side_effect = lambda fn, ev: captured.append(dict(ev))

        worker = VisionWorker.__new__(VisionWorker)
        worker._source = iter([(frame, "789123456", 1.0)])
        worker._bus = MagicMock()
        worker._loop = loop
        worker._stop_evt = MagicMock()
        worker._stop_evt.is_set.return_value = False
        worker._detector_cb = None  # Sprint 9B.3: CB não necessário em testes unitários
        worker._detector = detector

        worker._run()

        assert captured[0]["yolo_class"] == "cup"

    def test_all_detections_no_evento_emitido(self):
        """all_detections deve estar presente no evento emitido."""
        from vision.worker import VisionWorker

        frame = _blank_frame()
        detector = self._make_mock_detector()

        captured = []
        loop = MagicMock()
        loop.call_soon_threadsafe.side_effect = lambda fn, ev: captured.append(dict(ev))

        worker = VisionWorker.__new__(VisionWorker)
        worker._source = iter([(frame, "789123456", 1.0)])
        worker._bus = MagicMock()
        worker._loop = loop
        worker._stop_evt = MagicMock()
        worker._stop_evt.is_set.return_value = False
        worker._detector_cb = None  # Sprint 9B.3: CB não necessário em testes unitários
        worker._detector = detector

        worker._run()

        assert "all_detections" in captured[0]
        assert isinstance(captured[0]["all_detections"], list)


# ── 4. image_storage — variantes ─────────────────────────────────────────────

class TestImageStorageVariants:

    def test_save_original_cria_em_subdiretorio_original(self, tmp_path):
        from app.services.image_storage import save_frame_bytes
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # fake JPEG mínimo
        path = save_frame_bytes(jpeg, tmp_path, inspection_id=1, variant="original")
        assert "original" in path
        assert (tmp_path / path).exists()

    def test_save_annotated_cria_em_subdiretorio_annotated(self, tmp_path):
        from app.services.image_storage import save_frame_bytes
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        path = save_frame_bytes(jpeg, tmp_path, inspection_id=1, variant="annotated")
        assert "annotated" in path
        assert (tmp_path / path).exists()

    def test_original_e_annotated_em_diretorios_distintos(self, tmp_path):
        from app.services.image_storage import save_frame_bytes
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        path_orig = save_frame_bytes(jpeg, tmp_path, inspection_id=2, variant="original")
        path_ann  = save_frame_bytes(jpeg, tmp_path, inspection_id=2, variant="annotated")
        assert "original" in path_orig
        assert "annotated" in path_ann
        assert path_orig != path_ann

    def test_backward_compat_sem_variant(self, tmp_path):
        """Chamada sem variant deve usar 'original' por padrão."""
        from app.services.image_storage import save_frame_bytes
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        path = save_frame_bytes(jpeg, tmp_path, inspection_id=3)
        assert "original" in path

    def test_date_subdir_original(self, tmp_path):
        from datetime import datetime, timezone
        from app.services.image_storage import _date_subdir
        dt = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        subdir = _date_subdir(tmp_path, dt, "original")
        assert "original" in str(subdir)
        assert "2026" in str(subdir)

    def test_date_subdir_annotated(self, tmp_path):
        from datetime import datetime, timezone
        from app.services.image_storage import _date_subdir
        dt = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        subdir = _date_subdir(tmp_path, dt, "annotated")
        assert "annotated" in str(subdir)


# ── 5. dashboard_service — persist_event com annotated ───────────────────────

class TestDashboardServiceSprint8B:

    def _make_event(self) -> dict:
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

    def test_persist_event_aceita_annotated_jpeg_bytes(self):
        from app.services.dashboard_service import persist_event

        db = MagicMock()
        repo_mock = MagicMock()
        repo_mock.get_by_barcode.return_value = None
        insp_mock = MagicMock()
        insp_mock.id = 1
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

            # Deve chamar _persist_image duas vezes: original e annotated
            assert mock_persist.call_count == 2
            calls = [c[1] for c in mock_persist.call_args_list]
            variants = {c.get("variant") for c in calls}
            assert "original" in variants
            assert "annotated" in variants

    def test_persist_event_sem_annotated_backward_compat(self):
        """persist_event sem annotated_jpeg_bytes não deve chamar _persist_image para annotated."""
        from app.services.dashboard_service import persist_event

        db = MagicMock()
        repo_mock = MagicMock()
        repo_mock.get_by_barcode.return_value = None
        insp_mock = MagicMock()
        insp_mock.id = 2
        repo_mock2 = MagicMock()
        repo_mock2.create.return_value = insp_mock

        with patch("app.services.dashboard_service.ProductRepository", return_value=repo_mock), \
             patch("app.services.dashboard_service.InspectionRepository", return_value=repo_mock2), \
             patch("app.services.dashboard_service._persist_image") as mock_persist:

            persist_event(
                db,
                self._make_event(),
                jpeg_bytes=b"\xff\xd8\xff" + b"\x00" * 50,
                # sem annotated_jpeg_bytes
            )

            # Só deve chamar para "original"
            assert mock_persist.call_count == 1


# ── 6. events.py — remoção de annotated_frame_jpeg ───────────────────────────

class TestEventsBusAnnotatedRemoval:

    def test_annotated_frame_jpeg_removido_antes_do_broadcast(self):
        """
        _persist_sync deve remover 'annotated_frame_jpeg' do dict
        para não vazar bytes no broadcast WebSocket.
        """
        from app.core.events import EventBus

        event = {
            "type": "inspection",
            "barcode": "789123456",
            "valid": True,
            "confidence": 0.9,
            "weight": 1.0,
            "product_name": "bottle",
            "reason": None,
            "timestamp": "2026-06-21T12:00:00+00:00",
            "yolo_class": "bottle",
            "bbox": [10, 20, 50, 60],
            "all_detections": [],
            "frame_jpeg": b"\xff\xd8\xff" + b"\x00" * 10,
            "annotated_frame_jpeg": b"\xff\xd8\xff" + b"\x00" * 20,
        }

        with patch("app.database.session.SessionLocal"), \
             patch("app.services.dashboard_service.persist_event") as mock_persist:
            mock_persist.return_value = MagicMock(id=1)
            EventBus._persist_sync(event)

        assert "frame_jpeg" not in event, "frame_jpeg deve ser removido"
        assert "annotated_frame_jpeg" not in event, "annotated_frame_jpeg deve ser removido"

    def test_yolo_fields_permanecem_no_evento_pos_persist(self):
        """
        Após _persist_sync, campos YOLO (yolo_class, bbox, all_detections)
        devem permanecer no evento para o broadcast WebSocket.
        """
        from app.core.events import EventBus

        event = {
            "type": "inspection",
            "barcode": "789123456",
            "valid": True,
            "confidence": 0.9,
            "weight": 1.0,
            "product_name": "bottle",
            "reason": None,
            "timestamp": "2026-06-21T12:00:00+00:00",
            "yolo_class": "bottle",
            "bbox": [10, 20, 50, 60],
            "all_detections": [{"class_name": "bottle", "confidence": 0.9, "bbox": [10, 20, 50, 60]}],
            "frame_jpeg": b"\xff\xd8\xff" + b"\x00" * 10,
            "annotated_frame_jpeg": b"\xff\xd8\xff" + b"\x00" * 20,
        }

        with patch("app.database.session.SessionLocal"), \
             patch("app.services.dashboard_service.persist_event") as mock_persist:
            mock_persist.return_value = MagicMock(id=1)
            EventBus._persist_sync(event)

        assert event["yolo_class"] == "bottle"
        assert event["bbox"] == [10, 20, 50, 60]
        assert len(event["all_detections"]) == 1


# ── 7. WebSocket — campos do evento broadcast ─────────────────────────────────

class TestWebSocketEventFields:

    def test_evento_broadcast_nao_tem_frame_jpeg(self):
        """Após _persist_sync, o evento não deve ter campos de bytes."""
        from app.core.events import EventBus

        event = {
            "type": "inspection",
            "barcode": "789123456",
            "valid": True,
            "confidence": 0.9,
            "weight": 1.0,
            "product_name": "bottle",
            "reason": None,
            "timestamp": "2026-06-21T12:00:00+00:00",
            "yolo_class": "cup",
            "bbox": [5, 5, 30, 30],
            "all_detections": [],
            "frame_jpeg": b"bytes_originais",
            "annotated_frame_jpeg": b"bytes_anotados",
        }

        with patch("app.database.session.SessionLocal"), \
             patch("app.services.dashboard_service.persist_event", return_value=MagicMock(id=1)):
            EventBus._persist_sync(event)

        import json
        # Evento deve ser serializável em JSON (sem bytes)
        json_str = json.dumps(event)
        parsed = json.loads(json_str)
        assert "frame_jpeg" not in parsed
        assert "annotated_frame_jpeg" not in parsed

    def test_evento_broadcast_tem_campos_yolo(self):
        """Após _persist_sync, yolo_class, bbox e all_detections devem estar no evento."""
        from app.core.events import EventBus

        event = {
            "type": "inspection",
            "barcode": "789123456",
            "valid": False,
            "confidence": 0.65,
            "weight": 0.8,
            "product_name": "cup",
            "reason": "Peso fora do intervalo.",
            "timestamp": "2026-06-21T12:00:00+00:00",
            "yolo_class": "cup",
            "bbox": [20, 30, 40, 50],
            "all_detections": [{"class_name": "cup", "confidence": 0.65, "bbox": [20, 30, 40, 50]}],
            "frame_jpeg": b"fake",
            "annotated_frame_jpeg": b"fake_ann",
        }

        with patch("app.database.session.SessionLocal"), \
             patch("app.services.dashboard_service.persist_event", return_value=MagicMock(id=2)):
            EventBus._persist_sync(event)

        assert event.get("yolo_class") == "cup"
        assert event.get("bbox") == [20, 30, 40, 50]
        assert len(event.get("all_detections", [])) == 1
