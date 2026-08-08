from sqlalchemy.orm import Session

from app.models.production_line import ProductionLine
from app.schemas.production_line import ProductionLineCreate


class ProductionLineRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_code(self, code: str) -> ProductionLine | None:
        return (
            self.db.query(ProductionLine)
            .filter(ProductionLine.code == code)
            .first()
        )

    def get_by_id(self, line_id: int) -> ProductionLine | None:
        return self.db.query(ProductionLine).filter(ProductionLine.id == line_id).first()

    def list_all(self) -> list[ProductionLine]:
        return self.db.query(ProductionLine).order_by(ProductionLine.id).all()

    def create(self, data: ProductionLineCreate) -> ProductionLine:
        line = ProductionLine(**data.model_dump())
        self.db.add(line)
        self.db.commit()
        self.db.refresh(line)
        return line
