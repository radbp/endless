# Endless

A single-tenant, Shopify-style jewelry ecommerce platform, built as a **modular monolith**: one FastAPI deployable plus one Arq worker, internally decomposed into eight bounded-context modules.

- **Design:** [`docs/architecture.md`](docs/architecture.md) — the source of truth.
- **Why a monolith, not microservices:** [`docs/right-sizing.md`](docs/right-sizing.md).
- **Working agreements & backlog:** [`CLAUDE.md`](CLAUDE.md).

## Stack

| Layer | Choice |
|---|---|
| API + worker | Python 3.12, FastAPI, Arq |
| Data | PostgreSQL (single database, module-prefixed tables), Redis |
| Storefront | Next.js 15 (SSR) — *F1.11* |
| Admin | Vite + React 18 SPA — *F1.14* |
| Hosting | Azure Container Apps, Front Door (CDN + WAF) |
| Payments | Stripe (Elements; no card data touches us) |
| Auth | Entra External ID (customers), Entra ID (admin) |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 for you)
- Docker + Docker Compose (local Postgres and Redis)

## Quickstart

```bash
uv sync              # install dependencies into .venv
make up              # start Postgres + Redis
make dev             # run the API at http://localhost:8080
```

Check it:

```bash
curl localhost:8080/healthz   # {"status":"ok",...}
curl localhost:8080/readyz
open http://localhost:8080/docs
```

## Common tasks

```bash
make help            # list every target
make check           # lint + type + contracts + test (what CI runs)
make test            # unit tests — no env vars, no Docker required
make integration     # integration tests (real Postgres/Redis via testcontainers)
make build           # build the Docker image
make format          # apply ruff autofixes + formatting
```

Run a single test:

```bash
uv run pytest tests/test_main.py::test_healthz_reports_ok
```

## Layout

```
app/
├── main.py        # FastAPI app, lifespan, DI wiring, router includes
├── api/           # HTTP routers + DTOs (one per module)
├── modules/       # the eight bounded contexts
├── platform/      # shared infra: settings, logging, otel, db, events, outbox
├── worker/        # Arq worker: outbox drain, sweeps, scheduled jobs
└── db/migrations/ # Alembic
```

The rule that holds it together: a module reaches another **only** through that module's `service.py` — never its repository, its domain, or its tables. `make contracts` enforces it.

## Status

Phase 0 — foundations. Ticket **F0.1** (scaffolding) is complete; the app boots and serves `/healthz` and `/readyz`. Persistence, the event bus, the outbox, idempotency, and auth arrive in **F0.6**; CI in **F0.2**; Azure infra in **F0.3**–**F0.5**.

## License

Proprietary — see [`LICENSE`](LICENSE).
