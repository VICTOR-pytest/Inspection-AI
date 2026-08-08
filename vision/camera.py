"""
vision/camera.py
----------------
Abstração da câmera industrial.

Suporta:
  - Webcam física  (source=0, 1, 2 …)
  - Arquivo de vídeo (source="video.mp4")
  - Imagem estática  (via CameraSimulator)

Padrão de uso:
    with Camera(source=0) as cam:
        frame = cam.capture()
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Tipo aceito como "frame" em todo o módulo vision
Frame = np.ndarray


class CameraError(RuntimeError):
    """Erro de inicialização ou captura da câmera."""


class Camera:
    """
    Wrapper sobre cv2.VideoCapture com suporte a context manager.

    Parameters
    ----------
    source : int | str
        Índice da webcam (0 = padrão) ou caminho para arquivo de vídeo.
    width : int
        Largura desejada do frame.
    height : int
        Altura desejada do frame.
    """

    def __init__(
        self,
        source: Union[int, str] = 0,
        width: int = 1280,
        height: int = 720,
    ) -> None:
        self.source = source
        self.width = width
        self.height = height
        self._cap: cv2.VideoCapture | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def open(self) -> "Camera":
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            raise CameraError(
                f"Não foi possível abrir a câmera/fonte: {self.source!r}"
            )
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        log.info("Câmera aberta: source=%s (%dx%d)", self.source, self.width, self.height)
        return self

    def close(self) -> None:
        if self._cap and self._cap.isOpened():
            self._cap.release()
            log.info("Câmera encerrada: source=%s", self.source)

    def __enter__(self) -> "Camera":
        return self.open()

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Captura
    # ------------------------------------------------------------------

    def capture(self) -> Frame:
        """
        Captura um único frame.

        Returns
        -------
        Frame (numpy ndarray BGR)

        Raises
        ------
        CameraError
            Se a câmera não estiver aberta ou a captura falhar.
        """
        if self._cap is None or not self._cap.isOpened():
            raise CameraError("Câmera não está aberta. Use Camera.open() ou context manager.")

        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise CameraError("Falha ao capturar frame da câmera.")
        return frame

    def stream(self):
        """
        Gerador infinito de frames.

        Yields
        ------
        Frame
        """
        while True:
            try:
                yield self.capture()
            except CameraError:
                break


class CameraSimulator:
    """
    Câmera simulada: carrega um frame fixo de arquivo de imagem ou array.

    Útil para testes e ambientes sem hardware de câmera.

    Parameters
    ----------
    image_path : str | Path | None
        Caminho para imagem local. Se None, é necessário chamar
        ``set_frame()`` antes de ``capture()``.
    """

    def __init__(self, image_path: Union[str, Path, None] = None) -> None:
        self._frame: Frame | None = None
        if image_path is not None:
            self.load(image_path)

    def load(self, image_path: Union[str, Path]) -> "CameraSimulator":
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {path}")
        frame = cv2.imread(str(path))
        if frame is None:
            raise CameraError(f"OpenCV não conseguiu abrir a imagem: {path}")
        self._frame = frame
        log.info("CameraSimulator: imagem carregada (%s)", path)
        return self

    def set_frame(self, frame: Frame) -> "CameraSimulator":
        """Define um frame diretamente (útil para testes unitários)."""
        self._frame = frame
        return self

    def capture(self) -> Frame:
        if self._frame is None:
            raise CameraError("CameraSimulator não possui frame. Chame load() ou set_frame().")
        return self._frame.copy()

    # Context manager compatível com Camera
    def __enter__(self) -> "CameraSimulator":
        return self

    def __exit__(self, *_) -> None:
        pass
