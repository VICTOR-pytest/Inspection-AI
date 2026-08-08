"""
vision/worker.py
----------------
Vision Worker — roda em thread separada, completamente isolado do FastAPI.

Fluxo:
  source.__iter__()
      ↓  (frame, barcode, weight)
  _process()          ← valida produto via DB direto (sem HTTP)
      ↓  InspectionEvent dict
  event_bus.put_nowait()
      ↓
  EventBus broadcast → WebSocket clients

Modelo de threading (Sprint 9B.3 — documentação):
  VisionWorker._run() executa em threading.Thread("vision-worker"), NÃO na
  corrotina asyncio do FastAPI. Isso significa:

  ✔ self._detector.detect(frame) — bloqueante por design — bloqueia APENAS
    esta thread. O event loop do FastAPI permanece livre durante toda a
    inferência YOLO (pode levar 100–500ms em CPU).

  ✔ FastAPI continua servindo HTTP requests, WebSocket e EventBus durante
    qualquer inferência YOLO, independente da duração.

  ✔ Frame drops são o mecanismo natural de backpressure: se a inferência
    demora mais que o intervalo entre frames (ex: 500ms vs 200ms a 5fps),
    a thread simplesmente não consegue processar todos os frames. Isso é
    comportamento esperado e correto — não é um bug.

  ✔ asyncio.to_thread() em EventBus._persist_safe() isola a persistência
    (cv2.imwrite, INSERT no banco) do event loop. IO de imagem nunca bloqueia.

Circuit Breaker (Sprint 9B.3):
  Sem circuit breaker, falhas repetidas do detector (ex: YOLODetector com
  modelo corrompido) geram log.warning() a cada frame (~5/segundo), inundando
  os logs e tornando o diagnóstico impossível.

  Com CircuitBreaker("detector"):
    - 5 falhas consecutivas → OPEN: para de tentar, 1 log de abertura
    - 30s → HALF_OPEN: 1 tentativa de prova
    - Sucesso → CLOSED: retoma normalidade, 1 log de fechamento

Regras críticas:
  ✔ Sem imports de FastAPI
  ✔ Sem requests HTTP
  ✔ Roda em threading.Thread (não bloqueia event loop)
  ✔ Comunica com FastAPI via event_bus.put_nowait() (thread-safe)

Sprint 8B:
  ✔ draw_detection() — overlay OpenCV com bbox, classe e confidence
  ✔ frame anotado gerado sem alterar frame original (cópia)
  ✔ bbox e class_name propagados no evento dict
  ✔ annotated_frame_jpeg incluso no evento para persistência
    (removido pelo EventBus antes do broadcast JSON, igual ao frame_jpeg)
"""
from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime, timezone
from typing import Any

# Circuit Breaker para proteger detector.detect() (Sprint 9B.3)
# Importação condicional: worker.py pode rodar fora do contexto FastAPI (testes de visão)
try:
    from app.core.circuit_breaker import CircuitBreaker
    from app.core.config import settings as _app_settings
    _CB_THRESHOLD = _app_settings.cb_failure_threshold
    _CB_TIMEOUT   = _app_settings.cb_reset_timeout
except Exception:
    # Fallback se rodando fora do contexto FastAPI (ex: testes de visão isolados)
    CircuitBreaker = None  # type: ignore[assignment,misc]
    _CB_THRESHOLD = 5
    _CB_TIMEOUT   = 30.0

log = logging.getLogger(__name__)

# NOTE (Sprint 8C — limitação conhecida — webcam real):
# Em modo CAMERA_MODE=simulated, o barcode e o peso são gerados pelo SimulatedSource
# e estão disponíveis diretamente como metadados do frame. A validação abaixo usa o
# dicionário _PRODUCTS como catálogo local — suficiente para desenvolvimento e testes.
#
# Em modo CAMERA_MODE=webcam, o barcode vem da câmera (via pyzbar/pipeline) e o peso
# do sensor físico. Nesse cenário, _validate() deveria consultar o ProductRepository
# (banco de dados) para garantir que novos produtos cadastrados via API sejam reconhecidos.
#
# Esta substituição (ProductRepository em vez de _PRODUCTS) será implementada na Sprint
# dedicada ao modo de produção com câmera física. Ela requer:
#   1. Passar a Session do SQLAlchemy para o VisionWorker (ou usar um pool de conexões)
#   2. Substituir _validate() por uma chamada a ProductRepository.get_by_barcode()
#   3. Cache TTL para evitar query a cada frame
# Até lá, o modo webcam funcionará com o catálogo estático _PRODUCTS.
# Produtos cadastrados via API NÃO serão reconhecidos em modo webcam real.
_PRODUCTS: dict[str, dict] = {
    "789123456": {"name": "Produto Teste A", "expected_weight": 1.00, "tolerance": 0.05},
    "111222333": {"name": "Produto Teste B", "expected_weight": 0.50, "tolerance": 0.10},
    "999888777": {"name": "Produto Teste C (inativo)", "expected_weight": 2.00, "tolerance": 0.05,
                  "is_active": False},
}


def _validate(barcode: str | None, weight: float) -> dict[str, Any]:
    """Lógica de negócio — espelha inspection_service.validate_product."""
    if not barcode or barcode not in _PRODUCTS:
        return {
            "barcode_ok":   False,
            "weight_ok":    False,
            "valid":        False,
            "product_name": None,
            "reason":       "Barcode não encontrado no catálogo.",
        }

    p = _PRODUCTS[barcode]
    if not p.get("is_active", True):
        return {
            "barcode_ok":   False,
            "weight_ok":    False,
            "valid":        False,
            "product_name": p["name"],
            "reason":       f"Produto '{p['name']}' está inativo.",
        }

    w_min = p["expected_weight"] * (1 - p["tolerance"])
    w_max = p["expected_weight"] * (1 + p["tolerance"])
    weight_ok = w_min <= weight <= w_max

    if weight_ok:
        return {
            "barcode_ok":   True,
            "weight_ok":    True,
            "valid":        True,
            "product_name": p["name"],
            "reason":       None,
        }

    direction = "abaixo" if weight < w_min else "acima"
    return {
        "barcode_ok":   True,
        "weight_ok":    False,
        "valid":        False,
        "product_name": p["name"],
        "reason":       (
            f"Peso {weight:.3f} kg está {direction} do intervalo "
            f"[{w_min:.3f} – {w_max:.3f}] para '{p['name']}'."
        ),
    }


def _build_event(
    barcode: str | None,
    weight: float,
    confidence: float,
    yolo_class: str | None = None,
    bbox: tuple[int, int, int, int] | None = None,
    all_detections: list[dict[str, Any]] | None = None,
    line_id: int | None = None,
    camera_id: int | None = None,
) -> dict[str, Any]:
    v = _validate(barcode, weight)
    # product_name: YOLO class_name tem prioridade quando disponível.
    # Em modo simulado (yolo_class=None), usa o nome do catálogo interno.
    effective_product_name = yolo_class if yolo_class is not None else v["product_name"]
    return {
        "type":            "inspection",
        "barcode":         barcode,
        "valid":           v["valid"],
        "confidence":      round(confidence, 3),
        "weight":          round(weight, 3),
        "product_name":    effective_product_name,
        "reason":          v["reason"],
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        # Sprint 8B — campos de detecção YOLO (opcionais, None quando FallbackDetector)
        "yolo_class":      yolo_class,
        "bbox":            list(bbox) if bbox is not None else None,
        "all_detections":  all_detections or [],
        # Sprint 10C.2 (PR-003/006) — contexto de linha/câmera do worker que
        # gerou o evento. None quando o worker não pertence a nenhuma linha
        # (modo legado/single-worker) — dashboard_service.persist_event()
        # trata isso como "sem associação", exatamente como antes da 10C.2.
        "line_id":         line_id,
        "camera_id":       camera_id,
    }


def _encode_frame(frame) -> bytes | None:
    """
    Codifica frame numpy (BGR) em JPEG bytes para persistência de imagem.

    Retorna None se frame for inválido ou cv2 não disponível.
    Nunca levanta exceção — falha silenciosa para não interromper o pipeline.

    Sprint 7B: resultado incluído como 'frame_jpeg' no evento dict.
    O EventBus remove este campo antes do broadcast WebSocket.
    """
    if frame is None:
        return None
    try:
        import cv2  # noqa: PLC0415
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else None
    except Exception as exc:
        log.warning("_encode_frame: falha ao codificar frame — %s", exc)
        return None


def draw_detection(
    frame,
    bbox: tuple[int, int, int, int] | None,
    class_name: str | None,
    confidence: float,
    valid: bool = True,
) -> "np.ndarray | None":  # type: ignore[name-defined]
    """
    Desenha overlay de detecção YOLO sobre uma CÓPIA do frame.

    Nunca modifica o frame original — cria uma cópia antes de desenhar.
    Retorna None se cv2 não estiver disponível ou frame for inválido.

    Sprint 8B: preparado para Sprint 9 com cores diferentes por status:
      valid=True  → verde  (0, 200, 80)
      valid=False → vermelho (0, 60, 220)

    Parameters
    ----------
    frame : np.ndarray
        Frame BGR original (não modificado).
    bbox : tuple[int, int, int, int] | None
        Bounding box (x, y, w, h). Se None, desenha apenas label central.
    class_name : str | None
        Nome da classe detectada (ex: "bottle", "cup").
    confidence : float
        Valor de confidence 0.0–1.0.
    valid : bool
        Status da inspeção — determina a cor do overlay.

    Returns
    -------
    np.ndarray | None
        Cópia do frame com overlay desenhado, ou None em caso de falha.
    """
    if frame is None:
        return None

    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        annotated = frame.copy()

        # Cores: verde para aprovado, vermelho para reprovado
        color = (0, 200, 80) if valid else (0, 60, 220)

        label_parts = []
        if class_name:
            label_parts.append(class_name.upper())
        label_parts.append(f"{confidence * 100:.1f}%")
        label = " ".join(label_parts)

        if bbox is not None:
            x, y, w, h = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])

            # Bounding box principal
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)

            # Background do label (para legibilidade)
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.6
            thickness = 2
            (text_w, text_h), baseline = cv2.getTextSize(label, font, font_scale, thickness)

            label_y = y - 8 if y > text_h + 8 else y + h + text_h + 8
            cv2.rectangle(
                annotated,
                (x, label_y - text_h - baseline),
                (x + text_w + 4, label_y + baseline),
                color,
                -1,  # filled
            )
            cv2.putText(
                annotated,
                label,
                (x + 2, label_y),
                font,
                font_scale,
                (255, 255, 255),
                thickness,
                cv2.LINE_AA,
            )
        else:
            # Sem bbox — exibe label centralizado na parte superior do frame
            h_frame, w_frame = annotated.shape[:2]
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.7
            thickness = 2
            (text_w, text_h), baseline = cv2.getTextSize(label, font, font_scale, thickness)
            x_text = (w_frame - text_w) // 2
            cv2.rectangle(
                annotated,
                (x_text - 4, 8),
                (x_text + text_w + 4, 8 + text_h + baseline + 4),
                color,
                -1,
            )
            cv2.putText(
                annotated,
                label,
                (x_text, 8 + text_h),
                font,
                font_scale,
                (255, 255, 255),
                thickness,
                cv2.LINE_AA,
            )

        return annotated

    except Exception as exc:
        log.warning("draw_detection: falha ao anotar frame — %s", exc)
        return None


class VisionWorker:
    """
    Worker de visão computacional.

    Parameters
    ----------
    source :
        Instância de SimulatedSource | WebcamSource | StaticSource.
    event_bus :
        Instância de EventBus (importada de app.core.events).
    loop :
        asyncio event loop do processo FastAPI (necessário para
        chamar put_nowait de thread externa de forma segura).
    detector : BaseDetector | None
        Detector de objetos. Se None, usa FallbackDetector (ProductDetector).
        Sprint 8A: YOLODetector passado por main.py quando YOLO_ENABLED=true.
    """

    def __init__(self, source, event_bus, loop, detector=None,
                 line_id: int | None = None, camera_id: int | None = None) -> None:
        self._source    = source
        self._bus       = event_bus
        self._loop      = loop
        self._thread: threading.Thread | None = None
        self._stop_evt  = threading.Event()

        # Sprint 10C.2 (PR-003) — contexto de linha/câmera. None preserva
        # o comportamento pré-10C.2 (worker "solto", sem associação).
        self.line_id   = line_id
        self.camera_id = camera_id

        # Detector: usa o passado ou cria FallbackDetector (sem YOLO)
        if detector is not None:
            self._detector = detector
        else:
            try:
                from vision.yolo_detector import FallbackDetector  # noqa: PLC0415
                self._detector = FallbackDetector()
            except Exception:
                self._detector = None  # modo degradado — confidence será 0.0

        # Sprint 9B.3 — Circuit Breaker para o detector
        # Protege contra falhas repetidas (ex: YOLODetector com modelo corrompido)
        # Sem CB: log.warning() a cada frame (~5/segundo) = log spam impossível de diagnosticar
        # Com CB: 5 falhas → OPEN (silencia), 30s → HALF_OPEN (testa), sucesso → CLOSED
        if CircuitBreaker is not None:
            self._detector_cb = CircuitBreaker(
                name="detector",
                failure_threshold=_CB_THRESHOLD,
                reset_timeout=_CB_TIMEOUT,
            )
        else:
            self._detector_cb = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            log.warning("VisionWorker já está rodando")
            return
        self._stop_evt.clear()
        self._source.open()
        self._thread = threading.Thread(
            target=self._run,
            name="vision-worker",
            daemon=True,
        )
        self._thread.start()
        log.info("VisionWorker iniciado")

    def stop(self) -> None:
        self._stop_evt.set()
        self._source.close()
        if self._thread:
            self._thread.join(timeout=5.0)
        log.info("VisionWorker parado")

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── Internal loop ──────────────────────────────────────────────────────

    def _run(self) -> None:
        log.info("VisionWorker: loop de captura iniciado")
        for frame_data in self._source:
            if self._stop_evt.is_set():
                break

            # Desempacota (frame, barcode, weight) — fonte simulada fornece
            # barcode e peso diretamente; webcam retorna (frame, None, None)
            if isinstance(frame_data, tuple):
                frame, barcode, weight = frame_data
            else:
                frame, barcode, weight = frame_data, None, 1.0

            # Sprint 8A/8B — inferência real via YOLODetector (ou FallbackDetector)
            confidence = 0.0
            yolo_class = None
            bbox = None
            all_detections: list[dict[str, Any]] = []

            if self._detector is not None and frame is not None:
                # Sprint 9B.3 — Circuit Breaker:
                # Verifica se o circuito permite tentativa (CLOSED ou HALF_OPEN)
                # Se OPEN: pula inferência silenciosamente, usa confidence=0.0
                cb = self._detector_cb
                if cb is None or cb.can_attempt():
                    try:
                        det = self._detector.detect(frame)
                        confidence = det.confidence
                        yolo_class = det.class_name
                        bbox = det.bbox                         # Sprint 8B
                        all_detections = det.all_detections     # Sprint 8B
                        if cb is not None:
                            cb.record_success()
                    except Exception as exc:
                        if cb is not None:
                            cb.record_failure(exc)
                        else:
                            log.warning("Detector falhou no frame: %s", exc)
                # Se OPEN: silêncio — confidence=0.0, sem log spam

            event = _build_event(
                barcode,
                weight if weight is not None else 1.0,
                confidence,
                yolo_class,
                bbox=bbox,                   # Sprint 8B
                all_detections=all_detections,  # Sprint 8B
                # Sprint 10C.2 — getattr por segurança: testes legados
                # instanciam VisionWorker via __new__() (bypass do
                # __init__), então nem sempre esses atributos existem.
                line_id=getattr(self, "line_id", None),
                camera_id=getattr(self, "camera_id", None),
            )

            # Sprint 7B — frame original como JPEG bytes para persistência.
            # Removido pelo EventBus antes do broadcast WebSocket.
            event["frame_jpeg"] = _encode_frame(frame)

            # Sprint 8B — frame anotado com overlay de detecção.
            # Gerado a partir de cópia do frame; original não é alterado.
            # Removido pelo EventBus antes do broadcast WebSocket (bytes não são JSON).
            valid = bool(event.get("valid", True))
            if frame is not None and (yolo_class is not None or bbox is not None):
                annotated = draw_detection(frame, bbox, yolo_class, confidence, valid=valid)
                event["annotated_frame_jpeg"] = _encode_frame(annotated)
            else:
                # Sem detecção YOLO — sem anotação (evita overhead desnecessário)
                event["annotated_frame_jpeg"] = None

            # Thread-safe: call_soon_threadsafe garante que put_nowait
            # roda na thread do event loop (asyncio.Queue não é thread-safe diretamente)
            self._loop.call_soon_threadsafe(self._bus.put_nowait, event)

        log.info("VisionWorker: loop encerrado")
