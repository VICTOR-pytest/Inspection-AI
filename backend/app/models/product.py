from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    barcode: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    expected_weight: Mapped[float] = mapped_column(Float, nullable=False)
    tolerance: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<Product id={self.id} name={self.name!r} barcode={self.barcode!r}>"
