"""
Testes unitários do pipeline de visão computacional.
Rodam sem câmera física, sem banco de dados e sem Docker.

Estratégia:
  - Gerar frames sintéticos com numpy/OpenCV
  - Mockar read_barcode para testar o pipeline isoladamente
  - Testar decode_base64_image com imagens geradas em memória
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

# Garante que o módulo vision seja encontrado em ambiente de teste local
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from vision.pipeline import decode_base64_image, encode_frame_base64, process_frame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _blank_frame(h: int = 480, w: int = 640) -> np.ndarray:
    """Frame BGR totalmente branco."""
    return np.ones((h, w, 3), dtype=np.uint8) * 255


def _frame_to_b64(frame: np.ndarray) -> str:
    _, buf = cv2.imencode(".jpg", frame)
    return base64.b64encode(buf.tobytes()).decode()


# ---------------------------------------------------------------------------
# decode_base64_image
# ---------------------------------------------------------------------------

class TestDecodeBase64Image:
    def test_jpeg_puro(self):
        frame = _blank_frame()
        b64 = _frame_to_b64(frame)
        result = decode_base64_image(b64)
        assert isinstance(result, np.ndarray)
        assert result.shape[2] == 3  # BGR

    def test_data_uri_prefix(self):
        frame = _blank_frame()
        b64 = "data:image/jpeg;base64," + _frame_to_b64(frame)
        result = decode_base64_image(b64)
        assert result is not None

    def test_base64_invalido_levanta_value_error(self):
        with pytest.raises(ValueError, match="Base64 inválido"):
            decode_base64_image("!@#$%não_é_base64!!!")

    def test_base64_valido_mas_nao_imagem(self):
        dados_aleatorios = base64.b64encode(b"isso nao e uma imagem").decode()
        with pytest.raises(ValueError, match="decodificar"):
            decode_base64_image(dados_aleatorios)


# ---------------------------------------------------------------------------
# encode_frame_base64 (round-trip)
# ---------------------------------------------------------------------------

class TestEncodeFrameBase64:
    def test_round_trip(self):
        original = _blank_frame()
        b64 = encode_frame_base64(original)
        recovered = decode_base64_image(b64)
        assert recovered.shape == original.shape


# ---------------------------------------------------------------------------
# process_frame
# ---------------------------------------------------------------------------

class TestProcessFrame:
    def test_frame_sem_barcode_retorna_none(self):
        frame = _blank_frame()
        result = process_frame(frame)
        assert result["barcode"] is None
        assert isinstance(result["detected"], bool)
        assert 0.0 <= result["detection_confidence"] <= 1.0
        assert result["symbology"] is None

    def test_frame_com_barcode_mockado(self):
        """Mocka read_barcode para simular leitura bem-sucedida."""
        from vision.barcode_reader import BarcodeResult

        mock_result = BarcodeResult(data="789123456", symbology="EAN13")
        frame = _blank_frame()

        with patch("vision.pipeline.read_barcode", return_value=mock_result):
            result = process_frame(frame)

        assert result["barcode"] == "789123456"
        assert result["detected"] is True
        assert result["symbology"] == "EAN13"

    def test_estrutura_do_resultado(self):
        frame = _blank_frame()
        result = process_frame(frame)
        assert "barcode" in result
        assert "detected" in result
        assert "detection_confidence" in result
        assert "symbology" in result
