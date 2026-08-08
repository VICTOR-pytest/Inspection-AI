from datetime import datetime

from pydantic import BaseModel, Field


class InspectionRunCreate(BaseModel):
    production_line_id: int
    product_id: int | None = Field(default=None)
    operator: str | None = Field(default=None, max_length=255)


class InspectionRunRead(BaseModel):
    id: int
    production_line_id: int
    product_id: int | None
    started_at: datetime
    finished_at: datetime | None
    operator: str | None
    status: str

    model_config = {"from_attributes": True}
