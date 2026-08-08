from datetime import datetime

from pydantic import BaseModel, Field


class ProductionLineBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None)
    is_active: bool = Field(default=True)


class ProductionLineCreate(ProductionLineBase):
    pass


class ProductionLineRead(ProductionLineBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
