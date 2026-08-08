#!/bin/sh

echo "[entrypoint] Aguardando banco ficar pronto..."
# Tenta conectar por até 30s antes de rodar migration
python -c "
import time, sys
from sqlalchemy import create_engine, text
from app.core.config import settings

for attempt in range(30):
    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('[entrypoint] Banco pronto!')
        sys.exit(0)
    except Exception as e:
        print(f'[entrypoint] Tentativa {attempt+1}/30: {e}')
        time.sleep(1)

print('[entrypoint] ERRO: banco nao respondeu em 30s')
sys.exit(1)
"

echo "[entrypoint] Rodando migrations..."
python -m alembic upgrade head
if [ $? -ne 0 ]; then
    echo "[entrypoint] ERRO na migration!"
    exit 1
fi
echo "[entrypoint] Migrations OK"

echo "[entrypoint] Rodando seed..."
python -c "
from app.database.seed import run_seed
run_seed()
print('[entrypoint] Seed OK')
" || echo "[entrypoint] Seed ignorado (pode ja existir)"

echo "[entrypoint] Subindo uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
