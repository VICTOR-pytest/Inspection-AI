from datetime import datetime

from pydantic import BaseModel, Field


class CameraBase(BaseModel):
    production_line_id: int
    name: str = Field(..., min_length=1, max_length=255)
    source: str = Field(..., min_length=1, max_length=255)
    resolution: str | None = Field(default=None, max_length=20)
    fps: float | None = Field(default=None, gt=0)
    enabled: bool = Field(default=True)


class CameraCreate(CameraBase):
    pass


class CameraRead(CameraBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}
