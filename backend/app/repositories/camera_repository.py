from sqlalchemy.orm import Session

from app.models.camera import Camera
from app.schemas.camera import CameraCreate


class CameraRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, camera_id: int) -> Camera | None:
        return self.db.query(Camera).filter(Camera.id == camera_id).first()

    def list_all(self) -> list[Camera]:
        return self.db.query(Camera).order_by(Camera.id).all()

    def list_by_line(self, production_line_id: int) -> list[Camera]:
        return (
            self.db.query(Camera)
            .filter(Camera.production_line_id == production_line_id)
            .order_by(Camera.id)
            .all()
        )

    def create(self, data: CameraCreate) -> Camera:
        camera = Camera(**data.model_dump())
        self.db.add(camera)
        self.db.commit()
        self.db.refresh(camera)
        return camera
