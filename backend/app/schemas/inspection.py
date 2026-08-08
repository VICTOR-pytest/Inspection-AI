from datetime import datetime

from pydantic import BaseModel, Field


class InspectionRequest(BaseModel):
    """Payload enviado pelo scanner da esteira."""

    barcode: str = Field(..., min_length=1, max_length=100)
    weight: float = Field(..., gt=0)


class InspectionResult(BaseModel):
    """Resposta retornada após a validação."""

    barcode_ok: bool
    weight_ok: bool
    valid: bool
    product_name: str | None = None
    reason: str | None = None


class InspectionRead(BaseModel):
    """Registro completo de inspeção (para listagem / auditoria)."""

    id: int
    barcode: str
    weight: float
    is_valid: bool
    reason: str | None
    created_at: datetime
    product_id: int | None
    confidence: float = 1.0
    product_name: str | None = None

    # Sprint 9A — campos de decisão humana
    decision: str = "PENDING"
    decision_reason: str | None = None
    reviewed_at: datetime | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Sprint 3 — Inspeção via imagem (realtime)
# ---------------------------------------------------------------------------

class RealtimeInspectionRequest(BaseModel):
    """
    Payload enviado pelo pipeline de visão computacional.

    A imagem deve ser codificada em base64 (JPEG ou PNG).
    Aceita formato puro ou com prefixo data URI
    (ex: 'data:image/jpeg;base64,…').
    """

    image: str = Field(
        ...,
        description="Imagem do produto em base64 (JPEG/PNG).",
    )
    weight: float = Field(
        ...,
        gt=0,
        description="Peso medido pelo sensor (kg ou g, consistente com o cadastro).",
    )


class RealtimeInspectionResult(BaseModel):
    """Resposta do endpoint /inspection/realtime."""

    barcode: str | None
    """Barcode extraído da imagem, ou None se não detectado."""

    product_name: str | None
    """Nome do produto no catálogo, ou None se barcode não encontrado."""

    valid: bool
    """True se barcode existe e peso está dentro da tolerância."""

    barcode_ok: bool
    """True se o barcode foi encontrado no banco de dados."""

    weight_ok: bool
    """True se o peso está dentro da faixa de tolerância."""

    reason: str | None
    """Motivo da rejeição, ou None se aprovado."""

    detected: bool
    """True se a visão computacional detectou um objeto na imagem."""

    detection_confidence: float
    """Confiança da detecção visual (0.0–1.0)."""
