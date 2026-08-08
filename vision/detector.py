"""
vision/detector.py
------------------
Detecção de presença de produto no campo de visão da câmera.

Sprint 3 usa detecção clássica por análise de contornos (sem modelos
de deep learning). A arquitetura permite substituição futura por YOLO
ou qualquer outro modelo sem alterar o pipeline.

Algoritmo:
  1. Converte para escala de cinza
  2. Aplica GaussianBlur para reduzir ruído
  3. Threshold adaptativo
  4. Detecta contornos
  5. Filtra por área mínima → produto presente se houver contorno válido
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

log = logging.getLogger(__name__)

Frame = np.ndarray

# Área mínima de contorno para considerar um objeto como "produto"
# (em pixels²). Ajuste conforme resolução da câmera e tamanho do produto.
DEFAULT_MIN_AREA = 5_000


@dataclass(frozen=True)
class DetectionResult:
    """Resultado da detecção de produto no frame."""

    detected: bool
    """True se um objeto foi detectado na ROI."""

    confidence: float
    """Valor 0.0–1.0 indicando certeza da detecção (heurística de área)."""

    bounding_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    """Lista de (x, y, w, h) dos contornos detectados."""

    area: float = 0.0
    """Área do maior contorno detectado (px²)."""


class ProductDetector:
    """
    Detector de presença de produto baseado em análise de contornos.

    Parameters
    ----------
    min_area : int
        Área mínima (px²) para um contorno ser considerado um produto.
    max_area : int | None
        Área máxima. None = sem limite superior.
    """

    def __init__(
        self,
        min_area: int = DEFAULT_MIN_AREA,
        max_area: int | None = None,
    ) -> None:
        self.min_area = min_area
        self.max_area = max_area

    def detect(self, frame: Frame) -> DetectionResult:
        """
        Analisa o frame e retorna se há produto detectado.

        Parameters
        ----------
        frame : Frame
            Frame BGR da câmera.

        Returns
        -------
        DetectionResult
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)

        # Threshold adaptativo lida melhor com variações de iluminação
        thresh = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            11,
            2,
        )

        # Morfologia para fechar buracos nos contornos
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        valid_boxes: list[tuple[int, int, int, int]] = []
        max_detected_area = 0.0

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area:
                continue
            if self.max_area and area > self.max_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            valid_boxes.append((x, y, w, h))
            if area > max_detected_area:
                max_detected_area = area

        detected = len(valid_boxes) > 0

        # Confiança heurística: proporção da área detectada em relação
        # a 10% da área total do frame (normalizada entre 0 e 1)
        frame_area = frame.shape[0] * frame.shape[1]
        confidence = min(max_detected_area / (frame_area * 0.10), 1.0) if detected else 0.0

        result = DetectionResult(
            detected=detected,
            confidence=round(confidence, 3),
            bounding_boxes=valid_boxes,
            area=round(max_detected_area, 1),
        )
        log.debug("Detecção: %s | confiança=%.2f | contornos=%d",
                  "PRODUTO" if detected else "VAZIO",
                  result.confidence,
                  len(valid_boxes))
        return result

    def draw_detections(self, frame: Frame, result: DetectionResult) -> Frame:
        """Anota bounding boxes sobre o frame para visualização."""
        annotated = frame.copy()
        color = (0, 255, 0) if result.detected else (0, 0, 255)
        for x, y, w, h in result.bounding_boxes:
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
        label = f"{'PRODUTO' if result.detected else 'VAZIO'} {result.confidence:.0%}"
        cv2.putText(
            annotated, label, (10, 80),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA,
        )
        return annotated
