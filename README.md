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

- Docker + Docker Compose
- [uv](https://docs.astral.sh/uv/) — only for the hot-reload workflow; it manages Python 3.12 for you

## Quickstart — everything in Docker

Builds the API image and starts it alongside Postgres and Redis. The API waits for both to report healthy before it boots.

```bash
docker compose up --build          # add -d to run detached
```

Check it:

```bash
curl localhost:8080/healthz        # {"status":"ok","service":"endless-api","version":"0.1.0"}
curl localhost:8080/readyz         # {"status":"ok","checks":{"postgres":"ok","redis":"ok"}}
open http://localhost:8080/docs    # interactive Swagger UI
docker compose ps                  # all three should read "healthy"
```

Tear down with `docker compose down` (add `-v` to also drop the Postgres and Redis volumes).

| Service | Port | Notes |
|---|---|---|
| `api` | 8080 | FastAPI, built from `Dockerfile`, runs non-root |
| `worker` | — | Arq worker (same image): drains the outbox, runs scheduled jobs |
| `postgres` | 5432 | Postgres 16 — `endless` / `endless` / db `endless` |
| `redis` | 6379 | Redis 7, append-only on |

> `/readyz` probes Postgres and Redis and returns `503` / `"degraded"` if either
> is unreachable; `/healthz` stays independent of dependency health. The
> idempotency middleware and Entra auth land in **F0.6 Slice B, part 2**.

## Quickstart — hot reload (day-to-day loop)

Dependencies in Docker, API on your host so edits reload instantly:

```bash
uv sync              # install dependencies into .venv
make up              # Postgres + Redis only
make dev             # API at http://localhost:8080, --reload on
```

If `uv` isn't found, add it to your PATH: `export PATH="$HOME/.local/bin:$PATH"`.

## Frontends

Not built yet — they land as their own tickets with their own Dockerfiles and compose services:

- `web/storefront` — Next.js 15 SSR, port 3000 (**F1.11**)
- `web/admin` — Vite + React SPA, port 5173 (**F1.14**)

## Common tasks

```bash
make help            # list every target
make check           # lint + type + contracts + test (what CI runs)
make test            # unit tests — no env vars, no Docker required
make integration     # integration tests (real Postgres/Redis via testcontainers)
make migrate         # apply Alembic migrations up to head
make revision m="…"  # autogenerate a migration from model changes
make worker          # run the Arq worker on the host (outbox drain + jobs)
make build           # build the Docker image
make format          # apply ruff autofixes + formatting
make down            # stop the local stack
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

Phase 0 — foundations. **F0.1** (scaffolding), **F0.6 Slice A**, and **Slice B
part 1** are complete. The app boots, opens pooled async Postgres and Redis
connections, and `/readyz` probes both. The platform ships the async DB layer
(session + single-transaction helper), the in-process event bus, an injectable
clock, an initialized Alembic history, the **transactional outbox** with a
`SKIP LOCKED` drain, the **Arq worker** (advisory-lock-guarded), and **Azure
Monitor** export. Still to come in **Slice B part 2**: the idempotency middleware
and Entra JWT auth. Then CI in **F0.2** and Azure infra in **F0.3**–**F0.5**.

## License

Proprietary — see [`LICENSE`](LICENSE).
