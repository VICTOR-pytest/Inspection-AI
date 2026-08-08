"""
vision/pipeline.py
------------------
Pipeline central de visão computacional.

Fluxo por frame:
  frame → detector (produto presente?) → barcode_reader (lê código) → dict

A função ``process_frame()`` é a interface pública consumida pelo backend.

Arquitetura intencional:
  - Stateless: cada chamada é independente
  - Sem acesso ao banco de dados (responsabilidade do backend)
  - Retorna dict tipado compatível com Pydantic
"""
from __future__ import annotations

import base64
import logging
from typing import TypedDict

import cv2
import numpy as np

from vision.barcode_reader import BarcodeResult, read_barcode
from vision.detector import DetectionResult, ProductDetector

log = logging.getLogger(__name__)

Frame = np.ndarray

# Instância compartilhada do detector (stateless, seguro para reuso)
_detector = ProductDetector()


class FrameAnalysis(TypedDict):
    """Resultado tipado do pipeline para consumo pelo backend."""

    barcode: str | None
    """Valor do código de barras lido, ou None se não detectado."""

    detected: bool
    """True se um objeto foi detectado na imagem."""

    detection_confidence: float
    """Confiança da detecção (0.0–1.0)."""

    symbology: str | None
    """Tipo do barcode ('EAN13', 'CODE128', 'QRCODE', …) ou None."""


def process_frame(frame: Frame) -> FrameAnalysis:
    """
    Processa um único frame da esteira e retorna análise estruturada.

    Esta é a função pública principal do módulo vision.

    Parameters
    ----------
    frame : Frame
        Imagem BGR (numpy ndarray) capturada pela câmera.

    Returns
    -------
    FrameAnalysis
        Dicionário com barcode, detected, confidence e symbology.
    """
    # 1. Detecção de presença de produto
    detection: DetectionResult = _detector.detect(frame)

    # 2. Leitura de barcode (mesmo se detecção falhar — barcode pode
    #    estar visível mesmo sem contorno significativo)
    barcode_result: BarcodeResult | None = read_barcode(frame)

    analysis: FrameAnalysis = {
        "barcode": barcode_result.data if barcode_result else None,
        "detected": detection.detected or (barcode_result is not None),
        "detection_confidence": detection.confidence,
        "symbology": barcode_result.symbology if barcode_result else None,
    }

    log.info(
        "Pipeline: detected=%s barcode=%s confidence=%.2f",
        analysis["detected"],
        analysis["barcode"] or "N/A",
        analysis["detection_confidence"],
    )
    return analysis


def decode_base64_image(b64_string: str) -> Frame:
    """
    Converte string base64 em frame numpy (BGR).

    Aceita tanto 'data:image/jpeg;base64,…' quanto base64 puro.

    Parameters
    ----------
    b64_string : str
        Imagem codificada em base64.

    Returns
    -------
    Frame

    Raises
    ------
    ValueError
        Se a string não puder ser decodificada como imagem.
    """
    # Remove prefixo data URI se presente
    if "," in b64_string:
        b64_string = b64_string.split(",", 1)[1]

    try:
        img_bytes = base64.b64decode(b64_string)
    except Exception as exc:
        raise ValueError(f"Base64 inválido: {exc}") from exc

    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if frame is None:
        raise ValueError(
            "Não foi possível decodificar a imagem. "
            "Verifique se o base64 é de uma imagem válida (JPEG, PNG, etc.)."
        )
    return frame


def encode_frame_base64(frame: Frame, fmt: str = ".jpg") -> str:
    """
    Codifica um frame numpy em base64 (útil para testes e debug).

    Parameters
    ----------
    frame : Frame
    fmt : str
        Extensão de formato: '.jpg', '.png', etc.

    Returns
    -------
    str
        Base64 puro (sem prefixo data URI).
    """
    ok, buffer = cv2.imencode(fmt, frame)
    if not ok:
        raise ValueError(f"Falha ao codificar frame como {fmt}")
    return base64.b64encode(buffer.tobytes()).decode("utf-8")
