"""
tests/test_camera_mode.py
--------------------------
Sprint 7A: Testes do sistema de seleção de câmera via CAMERA_MODE.

Cobre:
  - make_source() factory: 'simulated', 'webcam', valor inválido
  - _make_worker(): modo simulated instancia corretamente
  - _make_worker(): modo webcam com câmera indisponível → fallback para SimulatedSource
  - _make_worker(): CAMERA_MODE inválido → fallback para SimulatedSource
  - VisionWorker resultante é sempre funcional (start/stop sem câmera real)

Nenhum teste requer câmera física — cv2.VideoCapture é mockado.
Compatibilidade: 55 testes pré-existentes não são afetados.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def event_loop_for_worker():
    """Event loop isolado para passar ao VisionWorker (não usa pytest-asyncio)."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def mock_event_bus():
    bus = MagicMock()
    bus.put_nowait = MagicMock()
    return bus


# ── make_source() factory ─────────────────────────────────────────────────────


class TestMakeSourceFactory:
    def test_simulated_retorna_simulated_source(self):
        from vision.source import SimulatedSource, make_source
        source = make_source("simulated")
        assert isinstance(source, SimulatedSource)

    def test_simulated_fps_padrao(self):
        from vision.source import SimulatedSource, make_source
        source = make_source("simulated", fps=3.0)
        assert isinstance(source, SimulatedSource)
        assert source.fps == 3.0

    def test_webcam_retorna_webcam_source(self):
        from vision.source import WebcamSource, make_source
        source = make_source("webcam", index=0)
        assert isinstance(source, WebcamSource)

    def test_static_retorna_static_source(self):
        from vision.source import StaticSource, make_source
        source = make_source("static", image_path="fake.jpg", barcode="123")
        assert isinstance(source, StaticSource)

    def test_modo_invalido_levanta_value_error(self):
        from vision.source import make_source
        with pytest.raises(ValueError, match="Modo inválido"):
            make_source("yolo_camera")


# ── WebcamSource sem hardware ─────────────────────────────────────────────────


class TestWebcamSourceSemHardware:
    def test_open_levanta_runtime_error_sem_camera(self):
        """
        WebcamSource.open() deve levantar RuntimeError quando
        cv2.VideoCapture.isOpened() retorna False.
        """
        from vision.source import WebcamSource

        cap_mock = MagicMock()
        cap_mock.isOpened.return_value = False

        with patch("cv2.VideoCapture", return_value=cap_mock):
            source = WebcamSource(index=0)
            with pytest.raises(RuntimeError, match="não disponível"):
                source.open()

    def test_open_sucesso_com_camera_mockada(self):
        """WebcamSource.open() funciona quando VideoCapture.isOpened() = True."""
        from vision.source import WebcamSource

        cap_mock = MagicMock()
        cap_mock.isOpened.return_value = True

        with patch("cv2.VideoCapture", return_value=cap_mock):
            source = WebcamSource(index=0)
            source.open()  # não deve levantar
            source.close()

    def test_read_retorna_none_tuple_sem_camera_aberta(self):
        """read() sem câmera aberta retorna (None, None, None) sem crashar."""
        from vision.source import WebcamSource
        source = WebcamSource(index=0)
        # não chamamos open() — _cap é None
        frame, barcode, weight = source.read()
        assert frame is None
        assert barcode is None
        assert weight is None


# ── _make_worker() com settings mockados ─────────────────────────────────────


class TestMakeWorkerCameraMode:
    """
    Testa _make_worker() importando diretamente e mockando settings
    para não depender de variáveis de ambiente reais.
    """

    def _import_make_worker(self):
        """Import lazy para evitar side-effects no módulo level."""
        import importlib
        import app.main as main_module
        return main_module._make_worker

    def test_modo_simulated_instancia_worker(self, event_loop_for_worker, mock_event_bus):
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker
        import app.main as main_module

        mock_settings = MagicMock()
        mock_settings.camera_mode = "simulated"

        with patch.object(main_module, "settings", mock_settings), \
             patch.object(main_module, "event_bus", mock_event_bus):
            worker = main_module._make_worker(event_loop_for_worker)

        assert worker is not None
        assert isinstance(worker, VisionWorker)
        assert isinstance(worker._source, SimulatedSource)

    def test_modo_webcam_sem_hardware_faz_fallback(self, event_loop_for_worker, mock_event_bus):
        """
        Quando CAMERA_MODE=webcam mas câmera indisponível,
        _make_worker() retorna worker com SimulatedSource (não None, não crash).
        """
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker
        import app.main as main_module

        mock_settings = MagicMock()
        mock_settings.camera_mode = "webcam"
        mock_settings.camera_index = 0
        mock_settings.camera_fps = 5.0

        cap_mock = MagicMock()
        cap_mock.isOpened.return_value = False  # câmera indisponível

        with patch.object(main_module, "settings", mock_settings), \
             patch.object(main_module, "event_bus", mock_event_bus), \
             patch("cv2.VideoCapture", return_value=cap_mock):
            worker = main_module._make_worker(event_loop_for_worker)

        assert worker is not None, "fallback deve retornar worker, nunca None"
        assert isinstance(worker, VisionWorker)
        assert isinstance(worker._source, SimulatedSource), (
            "fallback deve usar SimulatedSource quando webcam indisponível"
        )

    def test_modo_webcam_com_hardware_usa_webcam_source(self, event_loop_for_worker, mock_event_bus):
        """
        Quando CAMERA_MODE=webcam e câmera disponível,
        _make_worker() usa WebcamSource (não SimulatedSource).
        """
        from vision.source import WebcamSource
        from vision.worker import VisionWorker
        import app.main as main_module

        mock_settings = MagicMock()
        mock_settings.camera_mode = "webcam"
        mock_settings.camera_index = 0
        mock_settings.camera_fps = 5.0

        cap_mock = MagicMock()
        cap_mock.isOpened.return_value = True   # câmera disponível

        with patch.object(main_module, "settings", mock_settings), \
             patch.object(main_module, "event_bus", mock_event_bus), \
             patch("cv2.VideoCapture", return_value=cap_mock):
            worker = main_module._make_worker(event_loop_for_worker)

        assert worker is not None
        assert isinstance(worker, VisionWorker)
        assert isinstance(worker._source, WebcamSource)

    def test_modo_invalido_faz_fallback_para_simulated(self, event_loop_for_worker, mock_event_bus):
        """
        CAMERA_MODE=invalido não deve crashar — faz fallback para SimulatedSource
        e loga warning.
        """
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker
        import app.main as main_module

        mock_settings = MagicMock()
        mock_settings.camera_mode = "modo_que_nao_existe"

        with patch.object(main_module, "settings", mock_settings), \
             patch.object(main_module, "event_bus", mock_event_bus):
            worker = main_module._make_worker(event_loop_for_worker)

        assert worker is not None
        assert isinstance(worker, VisionWorker)
        assert isinstance(worker._source, SimulatedSource)

    def test_vision_module_ausente_retorna_none(self, event_loop_for_worker, mock_event_bus):
        """
        Se o módulo vision não puder ser importado (deploy sem vision/),
        _make_worker() retorna None sem crashar o backend.
        """
        import app.main as main_module

        mock_settings = MagicMock()
        mock_settings.camera_mode = "simulated"

        with patch.object(main_module, "settings", mock_settings), \
             patch.object(main_module, "event_bus", mock_event_bus), \
             patch("builtins.__import__", side_effect=_selective_import_error):
            worker = main_module._make_worker(event_loop_for_worker)

        assert worker is None


def _selective_import_error(name, *args, **kwargs):
    """Levanta ImportError apenas para imports do módulo vision."""
    if name.startswith("vision"):
        raise ImportError(f"Módulo simulado ausente: {name}")
    return original_import(name, *args, **kwargs)


import builtins
original_import = builtins.__import__


# ── Integração: worker inicia e para sem câmera real ─────────────────────────


class TestWorkerStartStop:
    def test_simulated_worker_inicia_e_para(self, event_loop_for_worker, mock_event_bus):
        """
        Worker em modo simulated deve iniciar e parar limpo
        sem câmera física, sem event loop asyncio ativo.
        """
        from vision.source import SimulatedSource
        from vision.worker import VisionWorker

        source = SimulatedSource(fps=50.0)  # fps alto para iterar rápido no teste
        worker = VisionWorker(
            source=source,
            event_bus=mock_event_bus,
            loop=event_loop_for_worker,
        )

        worker.start()
        assert worker.is_running

        worker.stop()
        assert not worker.is_running
