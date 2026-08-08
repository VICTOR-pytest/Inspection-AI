# Inspection AI

> Industrial inspection system for production lines.

## Objective

Inspection AI will identify products, read barcodes, validate weight, count items,
approve or reject them, generate dashboards, and manage production lines.
This repository contains the Sprint 1 foundation.

---

## Directory Structure

```
inspection-ai/
├── backend/          # FastAPI REST API (Python 3.12)
├── frontend/         # React + TypeScript (Vite)
├── vision/           # Computer vision pipeline (future)
├── hardware/         # ESP32 firmware / load cells (future)
├── shared/           # Shared utilities (future)
├── docs/             # Architecture and documentation
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Requirements

- [Docker](https://www.docker.com/) 24+
- [Docker Compose](https://docs.docker.com/compose/) v2+

For local development without Docker:

- Python 3.12
- Node.js 20+
- PostgreSQL 16

---

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd inspection-ai

# Copy the environment file
cp .env.example .env
```

---

## Execution

### Docker (recommended)

```bash
docker compose up --build
```

This starts three containers:

| Container                    | Port   | Description          |
|------------------------------|--------|----------------------|
| `inspection-ai-postgres`     | 5432   | PostgreSQL 16        |
| `inspection-ai-backend`      | 8000   | FastAPI              |
| `inspection-ai-frontend`     | 5173   | React (Vite)         |

Stop all containers:

```bash
docker compose down
```

Stop and remove volumes:

```bash
docker compose down -v
```

---

## Backend

### Local development

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend available at: http://localhost:8000

### Endpoints

| Method | Path      | Description      |
|--------|-----------|------------------|
| GET    | `/`       | App info         |
| GET    | `/health` | Health check     |
| GET    | `/docs`   | Swagger UI       |
| GET    | `/redoc`  | ReDoc            |

---

## Frontend

### Local development

```bash
cd frontend
npm install
npm run dev
```

Frontend available at: http://localhost:5173

---

## Database

PostgreSQL 16 — connection details (defaults from `.env.example`):

| Parameter | Value               |
|-----------|---------------------|
| Host      | `localhost`         |
| Port      | `5432`              |
| Database  | `inspection_ai`     |
| User      | `inspection_user`   |
| Password  | `inspection_password` |

### Migrations (Alembic)

```bash
cd backend

# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

---

## Validation

After `docker compose up --build`, verify all services:

```bash
# Backend root
curl http://localhost:8000/
# → {"name":"Inspection AI","status":"running"}

# Health check
curl http://localhost:8000/health
# → {"status":"healthy"}

# Frontend
open http://localhost:5173
# → Shows "Inspection AI / System Online"
```

---

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.
