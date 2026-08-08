# Inspection AI — Architecture

## Project Overview

Inspection AI is an industrial inspection system designed for production lines.
It identifies products, validates weight, reads barcodes, counts items, and
approves or rejects them — generating dashboards and managing production lines.

---

## Directory Structure

```
inspection-ai/
├── backend/          # FastAPI REST API
├── frontend/         # React + TypeScript UI (Vite)
├── vision/           # Computer vision pipeline (future)
├── hardware/         # Firmware for physical devices (future)
├── shared/           # Shared contracts and utilities (future)
├── docs/             # Project documentation
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Module Responsibilities

### `backend/`
- REST API built with FastAPI (Python 3.12)
- Central business logic orchestration
- Database access via SQLAlchemy 2.0 (async-ready)
- Schema validation via Pydantic v2
- Database migrations via Alembic
- Structured as Clean Architecture layers:
  - `api/` — HTTP routes and request/response handling
  - `core/` — Configuration and cross-cutting concerns
  - `database/` — Engine, session, and base model
  - `models/` — SQLAlchemy ORM models
  - `schemas/` — Pydantic request/response schemas
  - `services/` — Business logic (future)
  - `repositories/` — Data access layer (future)

### `frontend/`
- React 18 application with TypeScript
- Bundled and served by Vite
- Structured for scale:
  - `components/` — Reusable UI components
  - `pages/` — Route-level page components
  - `services/` — API client functions
  - `hooks/` — Custom React hooks
  - `types/` — TypeScript interfaces and types

### `vision/`
- Future home of all computer vision logic
- Will integrate cameras, detection models, and barcode readers
- Sub-modules: `capture`, `detection`, `weight`, `barcode`, `workers`

### `hardware/`
- Future ESP32 firmware and load cell drivers
- Sub-modules: `esp32`, `loadcell`

### `shared/`
- Cross-module contracts, utility functions, and constants
- Prevents code duplication between backend, vision, and frontend

### `docs/`
- Architecture and design decisions
- API documentation (future: OpenAPI export)
- Operational runbooks

---

## Service Communication

```
[Browser]
    │  HTTP
    ▼
[Frontend :5173]   ──(future: REST/WS)──►  [Backend :8000]
                                                  │
                                            [PostgreSQL :5432]

[Vision Workers]  ──(future: HTTP/queue)──►  [Backend :8000]

[ESP32 Hardware]  ──(future: MQTT/HTTP)──►  [Backend :8000]
```

All services run on a dedicated Docker network (`inspection-network`).

---

## Conventions

| Convention          | Rule                                                        |
|---------------------|-------------------------------------------------------------|
| Python style        | Black formatter, Ruff linter                                |
| Python typing       | Strict type hints throughout                                |
| API versioning      | `/api/v1/` prefix for all versioned endpoints               |
| Environment vars    | Always via `.env` file, never hard-coded                    |
| Database migrations | Alembic — never modify schema directly                      |
| Branching           | `main` (stable), `develop` (integration), `feature/*`      |
| Commit messages     | Conventional Commits (`feat:`, `fix:`, `chore:`, etc.)     |

---

## Growth Strategy

Each sprint adds a vertical slice without breaking existing contracts:

| Sprint | Focus                                      |
|--------|--------------------------------------------|
| 1      | ✅ Foundation — infra, Docker, base API     |
| 2      | Domain models, CRUD endpoints, DB schema   |
| 3      | Vision pipeline — camera capture           |
| 4      | Detection — product identification         |
| 5      | Barcode reading, weight validation         |
| 6      | Dashboard, production line management      |
| 7      | Hardware integration (ESP32, load cells)   |
| 8      | AI model training loop, reporting          |

New services must not be added to `docker-compose.yml` without a Sprint ticket.
New Python dependencies must be justified and pinned in `requirements.txt`.
