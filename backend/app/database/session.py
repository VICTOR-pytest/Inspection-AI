from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    # Sprint 9B.2 — todos os parâmetros de pool configuráveis via Settings/env vars.
    # Valores padrão conservadores adequados para PC industrial com 4–8 cores.
    pool_pre_ping=True,                       # detecta conexões mortas antes de usar
    pool_size=settings.db_pool_size,          # conexões permanentes no pool
    max_overflow=settings.db_max_overflow,    # extras acima do pool_size
    pool_timeout=settings.db_pool_timeout,    # espera máxima por conexão (segundos)
    pool_recycle=settings.db_pool_recycle,    # recicla conexões após N segundos de idle
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
