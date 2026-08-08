"""
vision/barcode_reader.py
------------------------
Leitura automática de códigos de barras e QR Codes a partir de frames.

Estratégia em camadas:
  1. pyzbar  — rápido, suporta 1D/QR, não requer GPU
  2. OpenCV  — fallback usando cv2.QRCodeDetector (QR apenas)

A função pública é ``read_barcode(frame)``, que retorna o primeiro
código encontrado ou None.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)

# pyzbar é obrigatório; importamos aqui para falhar rápido se ausente
try:
    from pyzbar import pyzbar  # type: ignore
    _PYZBAR_AVAILABLE = True
except ImportError:  # pragma: no cover
    log.warning("pyzbar não encontrado. Instale: pip install pyzbar")
    _PYZBAR_AVAILABLE = False

Frame = np.ndarray


@dataclass(frozen=True)
class BarcodeResult:
    """Resultado de uma leitura de barcode."""

    data: str
    """Valor decodificado (ex: '789123456')."""

    symbology: str
    """Tipo do código (ex: 'EAN13', 'CODE128', 'QRCODE')."""

    confidence: float = 1.0
    """Confiança da leitura (0.0–1.0). pyzbar sempre retorna 1.0."""


def _preprocess(frame: Frame) -> list[Frame]:
    """
    Retorna uma lista de variações do frame para aumentar a taxa de leitura.
    Algumas câmeras/iluminações dificultam a detecção direta.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    variants: list[Frame] = [gray]

    # Equalização de histograma (melhora contraste)
    variants.append(cv2.equalizeHist(gray))

    # Desfoque suave (reduz ruído de sensor)
    variants.append(cv2.GaussianBlur(gray, (3, 3), 0))

    # Nitidez via kernel de aguçamento
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    variants.append(cv2.filter2D(gray, -1, kernel))

    return variants


def _read_pyzbar(frame: Frame) -> BarcodeResult | None:
    """Tenta decodificar todos os barcodes visíveis com pyzbar."""
    if not _PYZBAR_AVAILABLE:
        return None

    for variant in _preprocess(frame):
        decoded = pyzbar.decode(variant)
        if decoded:
            best = decoded[0]
            data = best.data.decode("utf-8", errors="replace").strip()
            if data:
                return BarcodeResult(
                    data=data,
                    symbology=best.type,
                )
    return None


def _read_opencv_qr(frame: Frame) -> BarcodeResult | None:
    """Fallback: tenta detectar QR Code com o detector nativo do OpenCV."""
    detector = cv2.QRCodeDetector()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    data, _, _ = detector.detectAndDecode(gray)
    if data:
        return BarcodeResult(data=data.strip(), symbology="QRCODE")
    return None


def read_barcode(frame: Frame) -> BarcodeResult | None:
    """
    Função principal de leitura de barcode.

    Tenta pyzbar primeiro (todos os tipos), depois OpenCV QR como fallback.

    Parameters
    ----------
    frame : Frame
        Frame BGR capturado pela câmera.

    Returns
    -------
    BarcodeResult | None
        Resultado da leitura, ou None se nenhum código for detectado.
    """
    result = _read_pyzbar(frame)
    if result:
        log.debug("Barcode lido [pyzbar]: %s (%s)", result.data, result.symbology)
        return result

    result = _read_opencv_qr(frame)
    if result:
        log.debug("Barcode lido [OpenCV QR]: %s", result.data)
        return result

    log.debug("Nenhum barcode detectado no frame.")
    return None


def draw_barcode_overlay(frame: Frame, result: BarcodeResult) -> Frame:
    """
    Desenha informações do barcode sobre o frame (útil para debug/display).

    Retorna uma cópia do frame com a anotação.
    """
    annotated = frame.copy()
    label = f"{result.symbology}: {result.data}"
    cv2.putText(
        annotated,
        label,
        (10, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    return annotated
