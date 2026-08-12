<p align="center">
  <img src="brand/molidotrade-logo.svg" alt="MolidoTrade AI" width="360">
</p>

# MolidoTrade AI

Global AI trading intelligence, risk and execution platform.

Built to the *Trade-AI X v5.2 Master Build Prompt* specification. This repository
is currently at **phases 0–6 of 53**: infrastructure, data model,
market-data ingestion, data-quality engine, point-in-time integrity and the
market session calendar. No broker execution code exists yet, by design — per the spec, the
execution engine is only built after the risk brain that authorizes it.

## Core principle

```
Trading AI proposes.
Risk Brain authorizes.
Execution Engine executes.
Position Guardian supervises.
Learning Lab evaluates.
```

No component may bypass hard risk limits.

## Quick start

Docker is the supported dev path (Postgres runs in a container with TimescaleDB).

```bash
cp infra/.env.example infra/.env
docker compose -f infra/docker-compose.yml up -d
```

```bash
cd backend && pip install -e ".[dev]" && alembic upgrade head
```

```bash
cd backend && python -m app.cli seed-holidays && python -m app.cli seed-demo
```

```bash
cd backend && uvicorn app.main:app --reload
```

```bash
cd frontend && npm install && npm run dev
```

To deploy on a server and start accumulating real market history, see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

API docs: http://localhost:8000/docs — Dashboard: http://localhost:3000

> If port 5432 is already taken by a local Postgres install, set `POSTGRES_PORT`
> in `infra/.env` and the matching port in `MOLIDO_DATABASE_URL` in `backend/.env`
> to something free (both files are gitignored).

## Layout

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI modular monolith + workers |
| `frontend/` | Next.js AI Command Center |
| `infra/` | Docker Compose, environment templates |
| `brand/` | Logo and icon sources |
| `docs/` | Architecture, data model, phase plan |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_MODEL.md](docs/DATA_MODEL.md),
[docs/PHASES.md](docs/PHASES.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

Phase reports: [milestone 1](docs/MILESTONE-1-REPORT.md) ·
[phase 6](docs/PHASE-6-REPORT.md).

## Safety

This software does not provide investment advice and makes no guarantee of
profit. Trading involves substantial risk of loss.
