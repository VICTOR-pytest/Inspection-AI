from sqlalchemy import create_engine, pool
from alembic import context
from app.core.config import settings
from app.database.session import Base

# Importa todos os models para que o autogenerate os detecte
import app.models  # noqa: F401

config = context.config

# Sobrescreve a URL com o valor correto lido do ambiente (DATABASE_URL)
# NÃO usar fileConfig() — destrói handlers de logging do uvicorn (exit code 3)
# NÃO usar engine_from_config() — leria sqlalchemy.url vazia do .ini

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Cria engine diretamente com a URL do ambiente — ignora .ini completamente
    connectable = create_engine(
        settings.database_url,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
