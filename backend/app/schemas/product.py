from pydantic import BaseModel, Field


class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    barcode: str = Field(..., min_length=1, max_length=100)
    expected_weight: float = Field(..., gt=0)
    tolerance: float = Field(default=0.05, ge=0.0, le=1.0)
    is_active: bool = Field(default=True)


class ProductCreate(ProductBase):
    pass


class ProductRead(ProductBase):
    id: int

    model_config = {"from_attributes": True}
