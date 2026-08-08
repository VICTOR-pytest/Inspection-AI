"""
vision/source.py
----------------
Abstração da fonte de frames da esteira.

Modos:
  SimulatedSource  → frames sintéticos com texto de barcode (dev/CI)
  WebcamSource     → câmera física OpenCV (produção)
  StaticSource     → imagem fixa em disco (testes)
"""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Generator

import cv2
import numpy as np

log = logging.getLogger(__name__)
Frame = np.ndarray

# Espelha seed.py — 789123456 e 111222333 são produtos válidos
_SEED_BARCODES  = ["789123456", "111222333", "999888777", "INVALID-99"]
_SEED_WEIGHTS   = [1.02, 0.50, 1.90, 0.80]   # índice alinhado com barcodes


class SimulatedSource:
    """
    Fonte simulada: gera frames BGR com o texto do barcode desenhado.

    O pipeline lê esse texto via OCR simples (cv2 text não é pyzbar, mas
    o worker usa a lógica de simulação direta — veja worker.py).
    """

    def __init__(self, fps: float = 2.0, width: int = 640, height: int = 480) -> None:
        self.fps    = fps
        self.width  = width
        self.height = height
        self._open  = False

    def open(self) -> None:
        self._open = True
        log.info("SimulatedSource aberta  fps=%.1f", self.fps)

    def close(self) -> None:
        self._open = False

    def read(self) -> tuple[Frame, str, float]:
        """
        Retorna (frame, barcode, weight) — o barcode e peso são metadados
        do simulador que o worker usa diretamente (sem precisar de pyzbar
        para decodificar pixels em modo simulado).
        """
        idx = random.choices(range(len(_SEED_BARCODES)), weights=[35, 30, 10, 25])[0]
        barcode = _SEED_BARCODES[idx]

        # Peso: 70 % dentro da tolerância, 30 % fora
        base_weight = _SEED_WEIGHTS[idx]
        if random.random() > 0.30:
            noise = random.uniform(-0.03, 0.03)
        else:
            sign = 1 if random.random() > 0.5 else -1
            noise = sign * random.uniform(0.15, 0.40)
        weight = round(base_weight + noise, 3)

        # Frame visual (útil para debug/display)
        frame = np.ones((self.height, self.width, 3), dtype=np.uint8) * 25
        cx, cy = self.width // 2, self.height // 2
        cv2.rectangle(frame, (cx - 130, cy - 70), (cx + 130, cy + 70), (45, 45, 45), -1)
        cv2.putText(frame, barcode, (cx - 110, cy + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85, (200, 200, 200), 2, cv2.LINE_AA)
        cv2.putText(frame, f"{weight:.3f} kg", (cx - 60, cy + 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (120, 200, 120), 1, cv2.LINE_AA)
        noise_arr = np.random.randint(0, 12, frame.shape, dtype=np.uint8)
        frame = cv2.add(frame, noise_arr)

        return frame, barcode, weight

    def __iter__(self) -> Generator[tuple[Frame, str, float], None, None]:
        interval = 1.0 / self.fps
        while self._open:
            yield self.read()
            # Sleep em pequenos incrementos para que close() seja percebido rapidamente
            elapsed = 0.0
            while elapsed < interval and self._open:
                time.sleep(0.05)
                elapsed += 0.05


class WebcamSource:
    """Câmera física via OpenCV."""

    def __init__(self, index: int = 0, fps: float = 5.0,
                 width: int = 1280, height: int = 720) -> None:
        self.index  = index
        self.fps    = fps
        self.width  = width
        self.height = height
        self._cap: cv2.VideoCapture | None = None
        self._open  = False

    def open(self) -> None:
        self._open = True
        self._cap = cv2.VideoCapture(self.index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Câmera index={self.index} não disponível")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        log.info("WebcamSource aberta  index=%d", self.index)

    def close(self) -> None:
        self._open = False
        if self._cap:
            self._cap.release()

    def read(self) -> tuple[Frame, None, None]:
        """Webcam não conhece barcode/peso antecipadamente — pipeline detecta."""
        if not self._cap or not self._cap.isOpened():
            return None, None, None  # type: ignore[return-value]
        ok, frame = self._cap.read()
        return (frame, None, None) if ok else (None, None, None)  # type: ignore[return-value]

    def __iter__(self) -> Generator[tuple[Frame, None, None], None, None]:
        interval = 1.0 / self.fps
        while self._open and self._cap and self._cap.isOpened():
            yield self.read()
            time.sleep(interval)


class StaticSource:
    """Imagem fixa — para testes unitários."""

    def __init__(self, image_path: str | Path, barcode: str = "789123456",
                 weight: float = 1.02, repeat: int = 3) -> None:
        self.image_path = Path(image_path)
        self.barcode    = barcode
        self.weight     = weight
        self.repeat     = repeat
        self._frame: Frame | None = None

    def open(self) -> None:
        self._frame = cv2.imread(str(self.image_path))
        if self._frame is None:
            raise FileNotFoundError(f"Imagem não encontrada: {self.image_path}")

    def close(self) -> None:
        self._frame = None

    def read(self) -> tuple[Frame, str, float]:
        return self._frame.copy(), self.barcode, self.weight  # type: ignore[return-value]

    def __iter__(self) -> Generator[tuple[Frame, str, float], None, None]:
        for _ in range(self.repeat):
            yield self.read()
            time.sleep(0.5)


def make_source(mode: str = "simulated", **kwargs):
    """Factory: 'simulated' | 'webcam' | 'static'"""
    if mode == "simulated":
        return SimulatedSource(**kwargs)
    if mode == "webcam":
        return WebcamSource(**kwargs)
    if mode == "static":
        return StaticSource(**kwargs)
    raise ValueError(f"Modo inválido: {mode!r}")
