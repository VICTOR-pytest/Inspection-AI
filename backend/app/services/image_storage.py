"""
app/services/image_storage.py
------------------------------
Sprint 7B — Serviço dedicado ao armazenamento de imagens de inspeção.
Sprint 8B — Suporte a duas versões: original/ e annotated/

Responsabilidades:
  - Criar estrutura de diretórios YYYY/MM/DD automaticamente.
  - Gerar nomes de arquivo únicos (inspection_{id}_{uuid}.jpg).
  - Salvar frame JPEG em disco.
  - Retornar caminho relativo (relativo a storage_path) para persistência no banco.
  - Tratar erros de IO sem derrubar o pipeline.

Sprint 8B: save_frame_bytes aceita parâmetro `variant` ("original" | "annotated")
para separar as duas versões em subdiretórios distintos.
Backward-compatible: variant="original" por padrão.

Estrutura de diretórios:
  storage/
    images/
      original/
        YYYY/MM/DD/
          inspection_{id}_{uuid}.jpg
      annotated/
        YYYY/MM/DD/
          inspection_{id}_{uuid}.jpg
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

ImageVariant = Literal["original", "annotated"]


class ImageStorageError(OSError):
    """Erro ao salvar imagem — capturado pelo caller para não derrubar o pipeline."""


def _date_subdir(base: Path, dt: datetime, variant: ImageVariant = "original") -> Path:
    """
    Retorna Path para images/{variant}/YYYY/MM/DD dentro de base/, criando se necessário.

    Sprint 8B: `variant` separa imagens originais e anotadas em subdiretórios distintos.

    >>> _date_subdir(Path('/app/storage'), datetime(2026, 6, 21, ...), "original")
    PosixPath('/app/storage/images/original/2026/06/21')

    >>> _date_subdir(Path('/app/storage'), datetime(2026, 6, 21, ...), "annotated")
    PosixPath('/app/storage/images/annotated/2026/06/21')
    """
    subdir = (
        base
        / "images"
        / variant
        / dt.strftime("%Y")
        / dt.strftime("%m")
        / dt.strftime("%d")
    )
    subdir.mkdir(parents=True, exist_ok=True)
    return subdir


def make_filename(inspection_id: int | None = None) -> str:
    """
    Gera nome de arquivo único para uma imagem de inspeção.

    Formato: inspection_{id}_{uuid4}.jpg
    Se inspection_id for None (ainda não persistido), usa 0 como placeholder.

    Exemplos:
      inspection_42_3f7a1b2c-....jpg
      inspection_0_8e4d....jpg
    """
    uid = uuid.uuid4().hex[:12]  # 12 hex chars = 48 bits de entropia, nome curto
    prefix = inspection_id if inspection_id is not None else 0
    return f"inspection_{prefix}_{uid}.jpg"


def save_frame_bytes(
    jpeg_bytes: bytes,
    base_path: str | Path,
    inspection_id: int | None = None,
    dt: datetime | None = None,
    variant: ImageVariant = "original",
) -> str:
    """
    Salva bytes JPEG em disco e retorna o caminho relativo a base_path.

    Parameters
    ----------
    jpeg_bytes : bytes
        Frame codificado como JPEG. Deve ser válido; não recodifica.
    base_path : str | Path
        Raiz do storage (settings.storage_path).
    inspection_id : int | None
        ID da inspeção para compor o nome do arquivo.
    dt : datetime | None
        Data/hora da captura (UTC). Se None, usa now(UTC).
    variant : "original" | "annotated"
        Sprint 8B: subdiretório de destino.
        "original"  → images/original/YYYY/MM/DD/
        "annotated" → images/annotated/YYYY/MM/DD/

    Returns
    -------
    str
        Caminho relativo a base_path,
        ex: "images/original/2026/06/21/inspection_42_abc.jpg"

    Raises
    ------
    ImageStorageError
        Se o diretório não puder ser criado ou o arquivo não puder ser escrito.
    """
    if not jpeg_bytes:
        raise ImageStorageError("jpeg_bytes está vazio — nada para salvar")

    base = Path(base_path)
    ts = dt or datetime.now(timezone.utc)

    try:
        subdir = _date_subdir(base, ts, variant)
    except OSError as exc:
        raise ImageStorageError(
            f"Não foi possível criar diretório de imagens em {base}: {exc}"
        ) from exc

    filename = make_filename(inspection_id)
    full_path = subdir / filename

    try:
        full_path.write_bytes(jpeg_bytes)
    except OSError as exc:
        raise ImageStorageError(
            f"Falha ao escrever imagem em {full_path}: {exc}"
        ) from exc

    # Retorna caminho relativo para armazenar no banco
    relative = full_path.relative_to(base)
    log.debug("Imagem salva (%s): %s (%d bytes)", variant, relative, len(jpeg_bytes))
    return str(relative)


class PathTraversalError(ValueError):
    """
    Tentativa de path traversal detectada.

    Levantada quando `relative_path` tenta escapar do `base_path` usando
    sequências como `../`, `..\\`, ou caminhos absolutos como `/etc/passwd`.

    Nunca deve ocorrer em operação normal — indica dado malicioso no banco
    ou bug de inserção. Tratada como erro de segurança, não de negócio.
    """


def resolve_full_path(relative_path: str, base_path: str | Path) -> Path:
    """
    Reconstrói o caminho absoluto a partir do caminho relativo salvo no banco.

    Sprint 9B.2 — Proteção contra Path Traversal:
      O campo `file_path` vem do banco de dados. Se o banco for comprometido
      ou um bug de inserção introduzir um valor como `../../etc/passwd`, esta
      função detecta a tentativa e levanta `PathTraversalError` em vez de
      servir o arquivo malicioso.

    Algoritmo:
      1. Resolve o caminho candidato com `.resolve()` (canonicaliza `..` e symlinks)
      2. Resolve o base_path com `.resolve()` (mesmo processo)
      3. Verifica que o caminho candidato começa com o base_path
      4. Se não começar: levanta PathTraversalError com detalhes para o log

    Parameters
    ----------
    relative_path : str
        Valor de InspectionImage.file_path — proveniente do banco de dados.
    base_path : str | Path
        Raiz do storage (settings.storage_path).

    Returns
    -------
    Path
        Caminho absoluto canonicalizado. Pode não existir — verificação
        de existência é responsabilidade do caller.

    Raises
    ------
    PathTraversalError
        Se o caminho resolvido escapar do base_path.
        O caller deve tratar como 400 Bad Request ou 404, NÃO como 500.
    """
    base_resolved   = Path(base_path).resolve()
    target_resolved = (Path(base_path) / relative_path).resolve()

    # Verificação de prefixo — a única proteção confiável contra traversal
    # `Path.is_relative_to()` é Python 3.9+; usamos string prefix para compatibilidade
    base_str   = str(base_resolved)
    target_str = str(target_resolved)

    # Adiciona separador para evitar falso positivo:
    # base=/app/storage, target=/app/storage2 não deve passar
    if not (target_str == base_str or target_str.startswith(base_str + "/")):
        log.error(
            "ALERTA DE SEGURANÇA — Path traversal bloqueado: "
            "relative_path=%r base=%r resolved=%r",
            relative_path,
            base_str,
            target_str,
        )
        raise PathTraversalError(
            f"Caminho inválido: '{relative_path}' escapa do diretório de storage. "
            "Possível tentativa de path traversal."
        )

    return target_resolved


def encode_frame_to_jpeg(frame) -> bytes | None:
    """
    Converte frame numpy (BGR) para bytes JPEG.

    Retorna None se cv2 não estiver disponível ou o frame for inválido.
    Nunca levanta exceção — falha silenciosa para não derrubar o pipeline.
    """
    if frame is None:
        return None
    try:
        import cv2  # noqa: PLC0415
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else None
    except Exception as exc:  # pragma: no cover
        log.warning("encode_frame_to_jpeg falhou: %s", exc)
        return None
