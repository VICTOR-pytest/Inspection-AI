"""
vision/yolo_detector.py
-----------------------
Sprint 8A — Detector YOLO real com fallback automático.

Hierarquia de decisão:
  YOLO disponível E model_path existe  →  YOLODetector.detect() usa ultralytics
  YOLO desabilitado (yolo_enabled=False) →  FallbackDetector (ProductDetector)
  ultralytics não instalado            →  FallbackDetector (ProductDetector)
  model_path não existe                →  FallbackDetector (ProductDetector)

Arquitetura preparada para modelos customizados:
  class_name é genérico — hoje retorna classes COCO ("bottle", "cup"…),
  futuramente pode retornar classes industriais ("produto_ok", "defeito"…).
  Nenhuma lógica depende de classes específicas.

Isolamento total:
  Toda dependência de ultralytics está NESTE arquivo.
  worker.py, pipeline.py e o restante do sistema NÃO importam ultralytics.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# Suprimir output verboso do ultralytics nos logs de produção
os.environ.setdefault("YOLO_VERBOSE", "False")


# ── Resultado padronizado ──────────────────────────────────────────────────────


@dataclass
class YOLOResult:
    """
    Resultado normalizado da inferência — agnóstico ao detector subjacente.

    Projetado para ser extensível: class_name pode ser qualquer string,
    não apenas classes COCO. Futuros modelos customizados retornarão
    classes industriais sem mudança de interface.
    """

    detected: bool
    """True se ao menos um objeto foi detectado acima do threshold de confidence."""

    class_name: str | None
    """
    Nome da classe detectada com maior confidence.
    Hoje: classes COCO ("bottle", "cup", "person"…).
    Futuro: classes customizadas ("produto_ok", "garrafa_sem_tampa"…).
    None se nada detectado.
    """

    confidence: float
    """Confidence da detecção principal (0.0–1.0). 0.0 se nada detectado."""

    bbox: tuple[int, int, int, int] | None = None
    """Bounding box (x, y, w, h) do objeto principal. None se não detectado."""

    all_detections: list[dict[str, Any]] = field(default_factory=list)
    """
    Todas as detecções acima do threshold, ordenadas por confidence desc.
    Cada item: {"class_name": str, "confidence": float, "bbox": (x,y,w,h)}
    Preparado para Sprint 8B (múltiplas detecções por frame).
    """


# ── Interface base (duck typing) ───────────────────────────────────────────────


class BaseDetector:
    """Interface que todos os detectores implementam."""

    def detect(self, frame: np.ndarray) -> YOLOResult:
        raise NotImplementedError


# ── Detector principal: YOLOv8 ────────────────────────────────────────────────


class YOLODetector(BaseDetector):
    """
    Detector baseado em YOLOv8 via ultralytics.

    Não instanciar diretamente — use make_detector() que trata fallback.

    Parameters
    ----------
    model_path : str | Path
        Caminho para o arquivo .pt. Se não existir, faz download automático
        para o mesmo diretório (respeitando o volume Docker montado).
    confidence_min : float
        Threshold mínimo de confidence (0.0–1.0). Detecções abaixo são ignoradas.
    """

    def __init__(
        self,
        model_path: str | Path = "vision/models/yolov8n.pt",
        confidence_min: float = 0.50,
    ) -> None:
        from ultralytics import YOLO  # import tardio — isolado aqui

        self._confidence_min = confidence_min
        model_path = Path(model_path)

        # Garante que o diretório de modelos existe antes do download
        model_path.parent.mkdir(parents=True, exist_ok=True)

        log.info(
            "Carregando modelo YOLO: %s (confidence_min=%.2f)",
            model_path,
            confidence_min,
        )
        self._model = YOLO(str(model_path))
        log.info("YOLODetector pronto — modelo: %s", model_path.name)

    def detect(self, frame: np.ndarray) -> YOLOResult:
        """
        Executa inferência no frame e retorna YOLOResult normalizado.

        Nunca levanta exceção — erros de inferência retornam resultado vazio.
        """
        if frame is None:
            return YOLOResult(detected=False, class_name=None, confidence=0.0)

        try:
            results = self._model(frame, verbose=False)
        except Exception as exc:
            log.warning("YOLODetector: erro na inferência — %s", exc)
            return YOLOResult(detected=False, class_name=None, confidence=0.0)

        all_dets: list[dict[str, Any]] = []

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                conf = float(box.conf[0])
                if conf < self._confidence_min:
                    continue
                cls_id = int(box.cls[0])
                cls_name = result.names.get(cls_id, str(cls_id))
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                bbox = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
                all_dets.append({
                    "class_name": cls_name,
                    "confidence": round(conf, 4),
                    "bbox": bbox,
                })

        # Ordena por confidence desc — o primeiro é o principal
        all_dets.sort(key=lambda d: d["confidence"], reverse=True)

        if not all_dets:
            return YOLOResult(
                detected=False,
                class_name=None,
                confidence=0.0,
                all_detections=[],
            )

        top = all_dets[0]
        return YOLOResult(
            detected=True,
            class_name=top["class_name"],
            confidence=top["confidence"],
            bbox=top["bbox"],
            all_detections=all_dets,
        )


# ── Fallback: ProductDetector clássico ────────────────────────────────────────


class FallbackDetector(BaseDetector):
    """
    Wraps ProductDetector (contornos) para compatibilidade com a interface YOLOResult.

    Usado quando:
      - ultralytics não está instalado
      - yolo_enabled=False
      - model_path não existe e download falhou
    """

    def __init__(self) -> None:
        from vision.detector import ProductDetector  # noqa: PLC0415
        self._inner = ProductDetector()
        log.info("FallbackDetector ativo (ProductDetector por contornos)")

    def detect(self, frame: np.ndarray) -> YOLOResult:
        if frame is None:
            return YOLOResult(detected=False, class_name=None, confidence=0.0)

        try:
            result = self._inner.detect(frame)
            return YOLOResult(
                detected=result.detected,
                class_name=None,           # contornos não identificam classes
                confidence=result.confidence,
                bbox=result.bounding_boxes[0] if result.bounding_boxes else None,
            )
        except Exception as exc:
            log.warning("FallbackDetector: erro — %s", exc)
            return YOLOResult(detected=False, class_name=None, confidence=0.0)


# ── Factory pública ────────────────────────────────────────────────────────────


def make_detector(
    yolo_enabled: bool = False,
    model_path: str | Path = "vision/models/yolov8n.pt",
    confidence_min: float = 0.50,
) -> BaseDetector:
    """
    Factory que decide qual detector usar.

    Fluxo:
      1. yolo_enabled=False             → FallbackDetector (rápido, sem rede)
      2. ultralytics não instalado      → FallbackDetector + warning
      3. model_path não existe          → FallbackDetector + warning
      4. Tudo ok                        → YOLODetector

    Nunca levanta exceção — sempre retorna um detector funcional.

    Parameters
    ----------
    yolo_enabled : bool
        Se False, pula YOLOv8 e usa fallback diretamente.
    model_path : str | Path
        Caminho para yolov8n.pt (ou modelo customizado).
    confidence_min : float
        Threshold de confidence para YOLODetector.
    """
    if not yolo_enabled:
        log.info("YOLO desabilitado (YOLO_ENABLED=false) — usando FallbackDetector")
        return FallbackDetector()

    try:
        import ultralytics  # noqa: F401 — testa disponibilidade
    except ImportError:
        log.warning(
            "ultralytics não instalado — usando FallbackDetector. "
            "Para ativar YOLO: pip install ultralytics"
        )
        return FallbackDetector()

    try:
        detector = YOLODetector(
            model_path=model_path,
            confidence_min=confidence_min,
        )
        return detector
    except Exception as exc:
        log.warning(
            "YOLODetector falhou ao inicializar (%s) — usando FallbackDetector",
            exc,
        )
        return FallbackDetector()
