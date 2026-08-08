from sqlalchemy.orm import Session

from app.models.product import Product
from app.schemas.product import ProductCreate


class ProductRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_barcode(self, barcode: str) -> Product | None:
        return (
            self.db.query(Product)
            .filter(Product.barcode == barcode, Product.is_active.is_(True))
            .first()
        )

    def get_by_id(self, product_id: int) -> Product | None:
        return self.db.query(Product).filter(Product.id == product_id).first()

    def list_all(self) -> list[Product]:
        return self.db.query(Product).order_by(Product.id).all()

    def create(self, data: ProductCreate) -> Product:
        product = Product(**data.model_dump())
        self.db.add(product)
        self.db.commit()
        self.db.refresh(product)
        return product
