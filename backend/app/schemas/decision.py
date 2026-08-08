"""
app/schemas/decision.py
------------------------
Sprint 9A — Schemas Pydantic para o fluxo de decisão humana.

DecisionRequest:
  Payload enviado pelo operador via POST /api/v1/inspections/{id}/decision.
  Validação:
    - decision obrigatório: "PENDING" | "APPROVED" | "REJECTED"
    - reason obrigatório quando decision == "REJECTED"
    - reason ignorada (mas aceita) quando decision == "APPROVED"

DecisionResponse:
  Resposta retornada após registrar a decisão.
  Inclui os campos da inspeção + campos de decisão atualizados.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

from app.models.inspection import DecisionStatus


class DecisionRequest(BaseModel):
    """
    Payload do operador para registrar decisão sobre uma inspeção.

    Exemplos válidos:
      {"decision": "APPROVED"}
      {"decision": "APPROVED", "reason": "Dentro dos padrões"}
      {"decision": "REJECTED", "reason": "Rótulo danificado"}

    Exemplos inválidos:
      {"decision": "REJECTED"}               → reason obrigatória
      {"decision": "INVALID"}                → valor não permitido
      {}                                     → decision obrigatória
    """

    decision: DecisionStatus
    reason: str | None = None

    @model_validator(mode="after")
    def reason_obrigatoria_para_rejected(self) -> "DecisionRequest":
        """Garante que REJECTED sempre tenha motivo."""
        if self.decision == DecisionStatus.REJECTED:
            if not self.reason or not self.reason.strip():
                raise ValueError(
                    "O campo 'reason' é obrigatório quando decision é 'REJECTED'."
                )
        return self

    @field_validator("reason", mode="before")
    @classmethod
    def normalizar_reason(cls, v: str | None) -> str | None:
        """Remove espaços em branco nas extremidades; None permanece None."""
        if isinstance(v, str):
            stripped = v.strip()
            return stripped if stripped else None
        return v


class DecisionResponse(BaseModel):
    """
    Resposta completa após registrar uma decisão.

    Retorna o estado atualizado da inspeção incluindo os campos de decisão.
    Compatible com InspectionItem para facilitar atualização de estado no frontend.
    """

    id: int
    barcode: str
    weight: float
    is_valid: bool
    confidence: float
    product_name: str | None
    reason: str | None
    created_at: datetime

    # Campos de decisão humana (Sprint 9A)
    decision: str
    decision_reason: str | None
    reviewed_at: datetime | None

    model_config = {"from_attributes": True}
