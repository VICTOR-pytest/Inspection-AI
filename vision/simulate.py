"""
vision/simulate.py
------------------
Modo de simulação standalone — testa o pipeline sem o backend.

Uso:
    # Com imagem local:
    python simulate.py --image /caminho/para/barcode.jpg

    # Com webcam (índice 0):
    python simulate.py --webcam

    # Gerar imagem de teste com barcode embutido (requer python-barcode):
    python simulate.py --generate

Pressione 'q' para sair do modo webcam.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("simulate")

# Adiciona o diretório pai ao path para permitir import relativo
sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2

from vision.camera import Camera, CameraSimulator, CameraError
from vision.pipeline import decode_base64_image, encode_frame_base64, process_frame


def _print_result(result: dict) -> None:
    print("\n" + "=" * 50)
    print("📦  RESULTADO DO PIPELINE")
    print("=" * 50)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("=" * 50 + "\n")


def run_image(image_path: str) -> None:
    """Processa uma imagem estática."""
    log.info("Modo imagem: %s", image_path)
    sim = CameraSimulator(image_path)
    frame = sim.capture()
    result = process_frame(frame)
    _print_result(result)

    # Mostra a imagem com anotações se display disponível
    try:
        from vision.barcode_reader import BarcodeResult, draw_barcode_overlay
        from vision.detector import ProductDetector
        detector = ProductDetector()
        det = detector.detect(frame)
        annotated = detector.draw_detections(frame, det)
        cv2.imshow("Inspection AI — Simulação", annotated)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    except Exception:
        pass  # Ambiente sem display (ex: servidor)


def run_webcam(source: int = 0) -> None:
    """Processa stream de webcam em tempo real."""
    log.info("Modo webcam: source=%d", source)
    from vision.barcode_reader import draw_barcode_overlay, read_barcode
    from vision.detector import ProductDetector

    detector = ProductDetector()

    try:
        with Camera(source=source) as cam:
            print("Webcam aberta. Pressione 'q' para sair, 's' para capturar frame.")
            for frame in cam.stream():
                result = process_frame(frame)

                # Anotações visuais
                det = detector.detect(frame)
                annotated = detector.draw_detections(frame, det)

                bc = read_barcode(frame)
                if bc:
                    annotated = draw_barcode_overlay(annotated, bc)

                status = "✓ VÁLIDO" if result["barcode"] else "⏳ AGUARDANDO BARCODE"
                cv2.putText(
                    annotated, status, (10, annotated.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2,
                )

                cv2.imshow("Inspection AI — Esteira", annotated)
                key = cv2.waitKey(1) & 0xFF

                if key == ord("q"):
                    break
                if key == ord("s"):
                    _print_result(result)

    except CameraError as exc:
        log.error("Erro de câmera: %s", exc)
        sys.exit(1)
    finally:
        cv2.destroyAllWindows()


def run_generate() -> None:
    """
    Gera uma imagem de teste com barcode Code128.
    Requer: pip install python-barcode pillow
    """
    try:
        import barcode  # type: ignore
        from barcode.writer import ImageWriter  # type: ignore
        from PIL import Image  # type: ignore
        import numpy as np

        CODE = "789123456"
        bc = barcode.get("code128", CODE, writer=ImageWriter())
        pil_img = bc.render()
        frame = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        out = Path("test_barcode.jpg")
        cv2.imwrite(str(out), frame)
        log.info("Imagem de teste gerada: %s", out.resolve())

        result = process_frame(frame)
        _print_result(result)

    except ImportError:
        log.error(
            "Para gerar imagens de teste instale: pip install python-barcode pillow"
        )
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspection AI — Simulação de visão")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", metavar="PATH", help="Processar imagem estática")
    group.add_argument("--webcam", action="store_true", help="Usar webcam (source=0)")
    group.add_argument("--webcam-index", type=int, metavar="N", help="Webcam com índice N")
    group.add_argument("--generate", action="store_true", help="Gerar imagem de teste")
    args = parser.parse_args()

    if args.image:
        run_image(args.image)
    elif args.webcam:
        run_webcam(0)
    elif args.webcam_index is not None:
        run_webcam(args.webcam_index)
    elif args.generate:
        run_generate()
