"""
tests/test_yolo_detector.py
-----------------------------
Sprint 8A — Testes do YOLODetector, FallbackDetector, make_detector() e integração
com VisionWorker.

Estratégia:
  - ultralytics é SEMPRE mockado — sem download, sem GPU, sem rede
  - ProductDetector (fallback) é mockado quando necessário
  - Todos os testes rodam em CI sem dependências externas

Cobre:
  1. YOLOResult dataclass
  2. YOLODetector com ultralytics mockado
  3. FallbackDetector (ProductDetector como base)
  4. make_detector() — todos os caminhos de decisão
  5. Integração com VisionWorker
  6. Integração com EventBus (campo class_name/product_name)
  7. _build_event() com yolo_class
  8. Compatibilidade backward com VisionWorker sem detector
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _blank_frame(h: int = 100, w: int = 100) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _make_fake_box(confidence: float, cls_id: int, x1: int, y1: int, x2: int, y2: int):
    """Cria um box falso com valores reais (não MagicMock) para .conf, .cls, .xyxy."""
    box = MagicMock()
    # conf[0] e cls[0] precisam ser float/int — o código faz float(box.conf[0])
    box.conf = [float(confidence)]
    box.cls = [int(cls_id)]
    # xyxy[0] precisa ser iterável com 4 valores — o código faz box.xyxy[0].tolist()
    # Usamos um objeto que implementa .tolist()
    class FakeTensor(list):
        def tolist(self):
            return list(self)
    box.xyxy = [FakeTensor([x1, y1, x2, y2])]
    return box


def _make_fake_ultralytics(
    class_name: str = "bottle",
    confidence: float = 0.92,
    bbox: tuple = (10, 20, 50, 60),
    n_detections: int = 1,
):
    """
    Cria um módulo ultralytics falso que retorna detecções controladas.
    Usado para testar YOLODetector sem instalar ultralytics.
    """
    x1, y1, w, h = bbox

    fake_box = _make_fake_box(confidence, 0, x1, y1, x1 + w, y1 + h)
    fake_result = MagicMock()
    fake_result.boxes = [fake_box] * n_detections
    fake_result.names = {0: class_name}

    # YOLO é uma classe: YOLO(model_path) retorna uma instância callable
    # Precisamos de dois níveis: YOLO_class(path) -> yolo_instance; yolo_instance(frame) -> results
    fake_yolo_model = MagicMock()          # instância do modelo
    fake_yolo_model.return_value = [fake_result]  # chamada com frame retorna resultados

    fake_yolo_class = MagicMock()          # a classe YOLO
    fake_yolo_class.return_value = fake_yolo_model  # YOLO(path) retorna a instância

    fake_ultralytics = types.ModuleType("ultralytics")
    fake_ultralytics.YOLO = fake_yolo_class

    return fake_ultralytics, fake_yolo_class


# ── 1. YOLOResult ─────────────────────────────────────────────────────────────


class TestYOLOResult:
    def test_campos_obrigatorios(self):
        from vision.yolo_detector import YOLOResult
        r = YOLOResult(detected=True, class_name="bottle", confidence=0.92)
        assert r.detected is True
        assert r.class_name == "bottle"
        assert r.confidence == 0.92
        assert r.bbox is None
        assert r.all_detections == []

    def test_com_bbox(self):
        from vision.yolo_detector import YOLOResult
        r = YOLOResult(detected=True, class_name="cup", confidence=0.85, bbox=(10, 20, 50, 60))
        assert r.bbox == (10, 20, 50, 60)

    def test_nao_detectado(self):
        from vision.yolo_detector import YOLOResult
        r = YOLOResult(detected=False, class_name=None, confidence=0.0)
        assert r.detected is False
        assert r.class_name is None
        assert r.confidence == 0.0

    def test_class_name_customizado(self):
        """class_name é genérico — aceita classes industriais futuras."""
        from vision.yolo_detector import YOLOResult
        r = YOLOResult(detected=True, class_name="garrafa_sem_tampa", confidence=0.97)
        assert r.class_name == "garrafa_sem_tampa"

    def test_all_detections_populado(self):
        from vision.yolo_detector import YOLOResult
        dets = [
            {"class_name": "bottle", "confidence": 0.92, "bbox": (0, 0, 10, 10)},
            {"class_name": "cup", "confidence": 0.75, "bbox": (20, 20, 10, 10)},
        ]
        r = YOLOResult(detected=True, class_name="bottle", confidence=0.92, all_detections=dets)
        assert len(r.all_detections) == 2
        assert r.all_detections[0]["class_name"] == "bottle"


# ── 2. YOLODetector com ultralytics mockado ───────────────────────────────────


class TestYOLODetector:
    def test_detect_retorna_yolo_result(self):
        from vision.yolo_detector import YOLODetector, YOLOResult

        fake_ultra, _ = _make_fake_ultralytics("bottle", 0.92)
        with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
            detector = YOLODetector(model_path="fake.pt", confidence_min=0.50)
            result = detector.detect(_blank_frame())

        assert isinstance(result, YOLOResult)
        assert result.detected is True
        assert result.class_name == "bottle"
        assert result.confidence == pytest.approx(0.92, abs=0.01)

    def test_detect_retorna_bbox(self):
        from vision.yolo_detector import YOLODetector

        fake_ultra, _ = _make_fake_ultralytics("cup", 0.88, bbox=(10, 20, 50, 60))
        with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
            detector = YOLODetector(model_path="fake.pt", confidence_min=0.50)
            result = detector.detect(_blank_frame())

        assert result.bbox is not None
        x, y, w, h = result.bbox
        assert x == 10 and y == 20

    def test_detect_abaixo_threshold_retorna_nao_detectado(self):
        """Detecção com confidence < threshold deve ser ignorada."""
        from vision.yolo_detector import YOLODetector

        fake_ultra, _ = _make_fake_ultralytics("bottle", 0.30)  # abaixo de 0.50
        with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
            detector = YOLODetector(model_path="fake.pt", confidence_min=0.50)
            result = detector.detect(_blank_frame())

        assert result.detected is False
        assert result.class_name is None
        assert result.confidence == 0.0

    def test_detect_multiplas_retorna_maior_confidence(self):
        """Com múltiplas detecções, class_name deve ser a de maior confidence."""
        from vision.yolo_detector import YOLODetector, YOLOResult

        fake_ultra = types.ModuleType("ultralytics")
        box_high = _make_fake_box(0.95, 1, 0, 0, 10, 10)
        box_low  = _make_fake_box(0.70, 0, 5, 5, 15, 15)

        fake_result = MagicMock()
        fake_result.boxes = [box_high, box_low]
        fake_result.names = {0: "cup", 1: "bottle"}

        fake_yolo_model = MagicMock(return_value=[fake_result])
        fake_yolo_class = MagicMock(return_value=fake_yolo_model)
        fake_ultra.YOLO = fake_yolo_class

        with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
            detector = YOLODetector(model_path="fake.pt", confidence_min=0.50)
            result = detector.detect(_blank_frame())

        assert result.class_name == "bottle"
        assert result.confidence == pytest.approx(0.95, abs=0.01)
        assert len(result.all_detections) == 2

    def test_detect_frame_none_retorna_nao_detectado(self):
        from vision.yolo_detector import YOLODetector

        fake_ultra, _ = _make_fake_ultralytics()
        with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
            detector = YOLODetector(model_path="fake.pt", confidence_min=0.50)
            result = detector.detect(None)

        assert result.detected is False
        assert result.confidence == 0.0

    def test_detect_erro_inferencia_retorna_nao_detectado(self):
        """Erro durante inferência não pode derrubar o pipeline."""
        from vision.yolo_detector import YOLODetector

        fake_ultra = types.ModuleType("ultralytics")
        fake_yolo_instance = MagicMock(side_effect=RuntimeError("CUDA OOM"))
        fake_ultra.YOLO = MagicMock(return_value=fake_yolo_instance)

        with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
            detector = YOLODetector.__new__(YOLODetector)
            detector._confidence_min = 0.50
            detector._model = fake_yolo_instance
            result = detector.detect(_blank_frame())

        assert result.detected is False
        assert result.confidence == 0.0

    def test_confidence_arredondada_4_casas(self):
        from vision.yolo_detector import YOLODetector

        fake_ultra, _ = _make_fake_ultralytics("bottle", 0.923456789)
        with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
            detector = YOLODetector(model_path="fake.pt", confidence_min=0.50)
            result = detector.detect(_blank_frame())

        # confidence deve ter no máximo 4 casas decimais
        assert result.confidence == round(0.923456789, 4)


# ── 3. FallbackDetector ───────────────────────────────────────────────────────


class TestFallbackDetector:
    def test_retorna_yolo_result_sem_class_name(self):
        """FallbackDetector (contornos) não identifica classes — class_name=None."""
        from vision.yolo_detector import FallbackDetector

        detector = FallbackDetector()
        result = detector.detect(_blank_frame())

        assert result.class_name is None
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0

    def test_frame_none_retorna_nao_detectado(self):
        from vision.yolo_detector import FallbackDetector

        detector = FallbackDetector()
        result = detector.detect(None)

        assert result.detected is False
        assert result.confidence == 0.0

    def test_nao_levanta_excecao_em_erro(self):
        """FallbackDetector com ProductDetector quebrado não propaga exceção."""
        from vision.yolo_detector import FallbackDetector

        detector = FallbackDetector()
        with patch.object(detector._inner, "detect", side_effect=RuntimeError("falha")):
            result = detector.detect(_blank_frame())

        assert result.detected is False
        assert result.confidence == 0.0


# ── 4. make_detector() — todos os caminhos ────────────────────────────────────


class TestMakeDetector:
    def test_yolo_desabilitado_retorna_fallback(self):
        from vision.yolo_detector import FallbackDetector, make_detector

        detector = make_detector(yolo_enabled=False)
        assert isinstance(detector, FallbackDetector)

    def test_ultralytics_nao_instalado_retorna_fallback(self):
        """ImportError de ultralytics nunca deve derrubar o sistema."""
        from vision.yolo_detector import FallbackDetector, make_detector

        with patch.dict(sys.modules, {"ultralytics": None}):
            detector = make_detector(yolo_enabled=True, model_path="qualquer.pt")

        assert isinstance(detector, FallbackDetector)

    def test_yolo_habilitado_com_mock_retorna_yolo_detector(self):
        from vision.yolo_detector import YOLODetector, make_detector

        fake_ultra, _ = _make_fake_ultralytics()
        with patch.dict(sys.modules, {"ultralytics": fake_ultra}), \
             patch("pathlib.Path.mkdir"):
            detector = make_detector(
                yolo_enabled=True,
                model_path="fake/model.pt",
                confidence_min=0.60,
            )

        assert isinstance(detector, YOLODetector)

    def test_yolo_init_falha_retorna_fallback(self):
        """Erro ao carregar o modelo (arquivo corrompido, etc.) cai no fallback."""
        from vision.yolo_detector import FallbackDetector, make_detector

        fake_ultra = types.ModuleType("ultralytics")
        fake_ultra.YOLO = MagicMock(side_effect=RuntimeError("model load failed"))

        with patch.dict(sys.modules, {"ultralytics": fake_ultra}), \
             patch("pathlib.Path.mkdir"):
            detector = make_detector(yolo_enabled=True, model_path="broken.pt")

        assert isinstance(detector, FallbackDetector)

    def test_confidence_min_propagada_ao_detector(self):
        from vision.yolo_detector import YOLODetector, make_detector

        fake_ultra, _ = _make_fake_ultralytics()
        with patch.dict(sys.modules, {"ultralytics": fake_ultra}), \
             patch("pathlib.Path.mkdir"):
            detector = make_detector(
                yolo_enabled=True,
                model_path="fake.pt",
                confidence_min=0.75,
            )

        assert isinstance(detector, YOLODetector)
        assert detector._confidence_min == 0.75

    def test_make_detector_nunca_levanta_excecao(self):
        """make_detector() deve ser à prova de falhas em qualquer cenário."""
        from vision.yolo_detector import FallbackDetector, make_detector

        # Cenário normal: yolo_enabled=False sempre retorna FallbackDetector
        detector = make_detector(yolo_enabled=False)
        assert isinstance(detector, FallbackDetector)

        # Cenário: ultralytics disponível mas YOLO() levanta exceção → FallbackDetector
        fake_ultra = types.ModuleType("ultralytics")
        fake_ultra.YOLO = MagicMock(side_effect=RuntimeError("model not found"))
        with patch.dict(sys.modules, {"ultralytics": fake_ultra}), \
             patch("vision.yolo_detector.Path") as mock_path:
            mock_path.return_value.parent.mkdir = MagicMock()
            mock_path.return_value.__str__ = lambda s: "bad.pt"
            detector2 = make_detector(yolo_enabled=True, model_path="bad.pt")
        assert isinstance(detector2, FallbackDetector)


# ── 5. _build_event() com yolo_class ─────────────────────────────────────────


class TestBuildEvent:
    def _import(self):
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from vision.worker import _build_event
        return _build_event

    def test_yolo_class_sobrescreve_product_name(self):
        _build_event = self._import()
        event = _build_event(
            barcode="789123456",
            weight=1.0,
            confidence=0.94,
            yolo_class="bottle",
        )
        assert event["product_name"] == "bottle"
        assert event["confidence"] == pytest.approx(0.94, abs=0.001)

    def test_sem_yolo_class_usa_catalogo(self):
        _build_event = self._import()
        event = _build_event(
            barcode="789123456",
            weight=1.0,
            confidence=0.88,
            yolo_class=None,
        )
        # 789123456 → "Produto Teste A" no catálogo do worker
        assert event["product_name"] == "Produto Teste A"

    def test_confidence_real_preservada(self):
        _build_event = self._import()
        event = _build_event(None, 1.0, 0.934, "cup")
        assert event["confidence"] == pytest.approx(0.934, abs=0.001)

    def test_evento_tem_type_inspection(self):
        _build_event = self._import()
        event = _build_event(None, 1.0, 0.0, None)
        assert event["type"] == "inspection"

    def test_timestamp_presente(self):
        _build_event = self._import()
        event = _build_event(None, 1.0, 0.0, None)
        assert "timestamp" in event
        assert len(event["timestamp"]) > 0

    def test_class_name_industrial_futuro(self):
        """Classe industrial customizada deve funcionar sem mudança de código."""
        _build_event = self._import()
        event = _build_event(None, 1.0, 0.97, "garrafa_sem_tampa")
        assert event["product_name"] == "garrafa_sem_tampa"


# ── 6. VisionWorker — integração com detector ─────────────────────────────────


class TestVisionWorkerComDetector:
    @pytest.fixture()
    def event_loop_sync(self):
        import asyncio
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture()
    def mock_bus(self):
        bus = MagicMock()
        bus.put_nowait = MagicMock()
        return bus

    def test_worker_aceita_detector_none(self, event_loop_sync, mock_bus):
        """VisionWorker(source, bus, loop) sem detector continua funcionando."""
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker

        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(source=source, event_bus=mock_bus, loop=event_loop_sync)
        assert worker is not None

    def test_worker_aceita_detector_yolo(self, event_loop_sync, mock_bus):
        """VisionWorker com YOLODetector mockado aceita o parâmetro."""
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker
        from vision.yolo_detector import YOLOResult

        mock_detector = MagicMock()
        mock_detector.detect.return_value = YOLOResult(
            detected=True, class_name="bottle", confidence=0.93
        )

        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(
            source=source,
            event_bus=mock_bus,
            loop=event_loop_sync,
            detector=mock_detector,
        )
        assert worker._detector is mock_detector

    def test_worker_aceita_detector_fallback(self, event_loop_sync, mock_bus):
        """VisionWorker com FallbackDetector explícito funciona."""
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker
        from vision.yolo_detector import FallbackDetector

        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(
            source=source,
            event_bus=mock_bus,
            loop=event_loop_sync,
            detector=FallbackDetector(),
        )
        assert worker.is_running is False  # ainda não iniciou

    def test_worker_inicia_e_para_com_yolo_mock(self, event_loop_sync, mock_bus):
        """Worker com YOLODetector mockado deve iniciar e parar limpo."""
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker
        from vision.yolo_detector import YOLOResult

        mock_detector = MagicMock()
        mock_detector.detect.return_value = YOLOResult(
            detected=True, class_name="bottle", confidence=0.92
        )

        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(
            source=source,
            event_bus=mock_bus,
            loop=event_loop_sync,
            detector=mock_detector,
        )

        worker.start()
        assert worker.is_running

        worker.stop()
        assert not worker.is_running

    def test_evento_tem_confidence_real_do_detector(self, event_loop_sync):
        """Confidence no evento deve vir do detector, não de random()."""
        import time
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker
        from vision.yolo_detector import YOLOResult

        eventos_capturados = []

        mock_bus = MagicMock()
        mock_bus.put_nowait = lambda evt: eventos_capturados.append(evt)

        mock_detector = MagicMock()
        mock_detector.detect.return_value = YOLOResult(
            detected=True, class_name="bottle", confidence=0.9999
        )

        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(
            source=source,
            event_bus=mock_bus,
            loop=event_loop_sync,
            detector=mock_detector,
        )

        # call_soon_threadsafe agenda no loop mas o loop não está rodando.
        # Patch para executar put_nowait diretamente na thread do worker.
        event_loop_sync.call_soon_threadsafe = lambda fn, *a: fn(*a)

        worker.start()
        time.sleep(0.15)
        worker.stop()

        assert len(eventos_capturados) > 0
        for evt in eventos_capturados:
            assert evt["confidence"] == pytest.approx(0.9999, abs=0.001), (
                "confidence deve ser do detector YOLO, não random()"
            )

    def test_evento_tem_class_name_do_detector(self, event_loop_sync):
        """product_name no evento deve vir do detector quando YOLO detecta."""
        import time
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker
        from vision.yolo_detector import YOLOResult

        eventos_capturados = []

        mock_bus = MagicMock()
        mock_bus.put_nowait = lambda evt: eventos_capturados.append(evt)

        mock_detector = MagicMock()
        mock_detector.detect.return_value = YOLOResult(
            detected=True, class_name="bottle", confidence=0.92
        )

        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(
            source=source,
            event_bus=mock_bus,
            loop=event_loop_sync,
            detector=mock_detector,
        )

        # Executa put_nowait diretamente (loop não está rodando em thread)
        event_loop_sync.call_soon_threadsafe = lambda fn, *a: fn(*a)

        worker.start()
        time.sleep(0.15)
        worker.stop()

        assert len(eventos_capturados) > 0
        for evt in eventos_capturados:
            assert evt["product_name"] == "bottle", (
                "product_name deve vir da class_name do YOLO"
            )

    def test_backward_compat_sem_detector_kwarg(self, event_loop_sync, mock_bus):
        """VisionWorker(source, bus, loop) — chamada antiga sem detector — deve funcionar."""
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker

        # Chamada no formato pré-Sprint 8A — sem detector=
        source = SimulatedSource(fps=50.0)
        worker = VisionWorker(source, mock_bus, event_loop_sync)

        worker.start()
        assert worker.is_running
        worker.stop()
        assert not worker.is_running
