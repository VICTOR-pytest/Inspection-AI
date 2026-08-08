# ── Inspection AI — Backend Dockerfile ───────────────────────────────────────
# Sprint 9B.2: processo roda como usuário não-root (appuser, UID 1001)
#
# Motivação de segurança:
#   Sem USER declarado, todos os processos rodam como UID 0 (root).
#   Uma exploração de vulnerabilidade no FastAPI, OpenCV ou qualquer
#   dependência daria acesso root ao container — e potencialmente ao host
#   via volume mounts (./storage:/app/storage).
#
#   Com appuser (UID 1001):
#     - Processo não pode escrever fora de /app
#     - Processo não pode instalar pacotes ou modificar o sistema
#     - Exploração de vulnerabilidade fica confinada ao usuário appuser
#
# Permissões de diretório:
#   /app          → chown appuser (aplicação e código)
#   /app/storage  → chown appuser (escrita de imagens de inspeção)
#   /tmp          → world-writable (padrão Linux — para libs que precisam)

FROM python:3.12-slim

# ── Metadados ─────────────────────────────────────────────────────────────────
LABEL org.opencontainers.image.title="Inspection AI Backend"
LABEL org.opencontainers.image.description="Sistema de inspeção visual industrial"

# ── Variáveis de ambiente Python ──────────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app:/vision_module"

# ── Dependências de sistema ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    gcc \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── Usuário não-root (Sprint 9B.2) ───────────────────────────────────────────
# UID/GID 1001 — evita conflito com UID 1000 (usuário padrão em muitas distros Linux)
# O grupo appgroup é criado separadamente para permitir futura adição de usuários
RUN groupadd --gid 1001 appgroup \
 && useradd  --uid 1001 --gid appgroup --shell /bin/sh --no-create-home appuser

# ── Diretório de trabalho ─────────────────────────────────────────────────────
WORKDIR /app

# ── Dependências Python ───────────────────────────────────────────────────────
# Instaladas ANTES de copiar o código — maximiza cache de layers do Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código da aplicação ───────────────────────────────────────────────────────
COPY . .

# ── Diretório de storage ──────────────────────────────────────────────────────
# Criado aqui para garantir que exista com permissões corretas ANTES do
# volume mount do docker-compose sobrescrevê-lo.
# O volume mount em docker-compose.yml (./storage:/app/storage) sobrescreve
# este diretório em runtime — mas se o diretório do host não existir,
# o Docker cria automaticamente com UID root. O script abaixo garante
# que o diretório tenha as permissões certas dentro do container.
RUN mkdir -p /app/storage \
 && chown -R appuser:appgroup /app \
 && chmod +x /app/entrypoint.sh

# ── Trocar para usuário não-root ──────────────────────────────────────────────
# Todas as instruções a partir daqui e o processo final rodam como appuser.
# IMPORTANTE: o entrypoint.sh roda migrations e seed — ambos usam DATABASE_URL
# para autenticar no PostgreSQL, não o usuário do OS. Não há impacto.
USER appuser

EXPOSE 8000

CMD ["/app/entrypoint.sh"]
