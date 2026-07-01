# CLAUDE.md — Jewelry Ecommerce Platform

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. Read it at the start of every session before doing anything else, and reread `docs/architecture.md` for any task that touches a new module or data store.

---

## 0. Mission

Build a production-ready, single-tenant, Shopify-style jewelry ecommerce platform as a **modular monolith**. Stack: **Python 3.12 + FastAPI** (one deployable + one Arq worker), Next.js storefront, React admin SPA, PostgreSQL, Redis, Azure Container Apps, Stripe, Entra External ID. Full design is in `docs/architecture.md`; the altitude rationale (why a monolith, not microservices) is in `docs/right-sizing.md`. Those are the source of truth, not your training data.

You are working ticket-by-ticket from the backlog in §13. One ticket per session unless a ticket explicitly says otherwise.

---

## 1. Non-Negotiables

These rules are inviolable. If a ticket seems to require breaking one, stop and ask the user.

1. **Module boundaries are real.** A module reaches another module **only through its `service.py` interface** — never by importing its `repository.py`, its `domain.py`, or by touching its tables. No joins across module table-prefixes. This is enforced by an import-linter contract; do not weaken it.
2. **No card data, ever.** Stripe Elements only. The Payment module stores Stripe IDs, last 4, brand — never PAN, CVV, or expiry. No logging of Stripe request/response bodies that could contain card fields.
3. **No secrets in code, env files, or images.** Secrets come from Key Vault via Container Apps managed identity. If a ticket needs a new secret, add it to the Key Vault Bicep with a placeholder and tell the user to set the value.
4. **Checkout is one local transaction, not a saga.** Reserve stock and create the order in a single DB transaction; commit reservation + flip order to paid in a single transaction on the Stripe webhook. Do not introduce saga choreography while everything is in one process (ADR-005).
5. **Reliable async only at the two external edges.** Stripe and email use the **transactional outbox** drained by the worker. Everything else is an in-process call or in-process event. Do not add a message broker.
6. **All mutating endpoints accept `Idempotency-Key`.** Use the shared `app/platform/idempotency`. Stripe webhooks dedupe on the upstream `event.id`.
7. **Async on every I/O path.** Every function doing I/O is `async def`. Never block the event loop (no sync DB/HTTP calls in request handlers).
8. **Typed exceptions, never bare `except`.** Raise domain exceptions; the FastAPI handler maps them to the error envelope (§5.3).
9. **No `datetime.now()` in `domain`/`service`.** Inject a `Clock`. Non-negotiable for testability.
10. **No import-time side effects** beyond router/registry registration. All wiring happens in `app/main.py` lifespan.

---

## 2. Required Reading on Session Start

Before writing any code:

1. Read this file end-to-end.
2. Read `docs/architecture.md` if the ticket touches a module or store you haven't worked on recently. Skim `docs/right-sizing.md` once so you understand what we deliberately did **not** build.
3. Read the target module's most recent code and any ADR notes.
4. Run `git log --oneline -20` to see recent changes.
5. Run `git status` to confirm a clean working tree. If dirty, ask the user before proceeding.

If `docs/architecture.md` or this file disagrees with what you "remember" about Python, Azure, or any library — trust the docs, not your priors. Search if uncertain.

---

## 3. Workflow

Every ticket follows the same loop. Do not skip steps.

### 3.1 Plan

1. Read the ticket's acceptance criteria.
2. Use `TodoWrite` to break the work into 3–8 concrete sub-tasks.
3. State your plan in 5–10 lines: what files you'll create or change, what tests you'll write, what you'll defer. If anything is ambiguous, ask now — not after coding.
4. Wait for confirmation only if the ticket is marked **`requires plan approval`** or you're touching > 10 files. Otherwise proceed.

### 3.2 Work

- Implement in small increments. Commit logically grouped changes (§3.4).
- Run tests after each meaningful change, not just at the end.
- If the ticket needs more than ~6 hours of agent work or > 1500 lines, stop and ask whether to split it.
- If you hit a decision not covered by `docs/architecture.md`, write a one-paragraph ADR draft, ask the user, then implement.

### 3.3 Test

Before considering a ticket done, the following must pass:

- `make lint` — `ruff check` + `ruff format --check`, clean.
- `make type` — `mypy` (strict) clean.
- `make test` — `pytest` unit tests pass; coverage on touched packages ≥ 75%.
- `make integration` (if the module has integration tests) — runs against testcontainers Postgres/Redis.
- `make build` — the Docker image builds.

For frontend tickets: `pnpm lint && pnpm typecheck && pnpm test && pnpm build` must pass.

### 3.4 Commit

- Conventional Commits: `feat(catalog): add product variants endpoint`, `fix(payment): handle webhook retry idempotently`, `chore(infra): resize container app`.
- One logical change per commit. A ticket usually produces 3–10 commits.
- Body explains *why*, not *what*.
- Reference the ticket ID: `Closes F1.4`.

### 3.5 Hand-off

When the ticket is done, write a short chat summary:

- What you built (3–5 bullets).
- What you skipped or deferred and why.
- Anything to verify manually (Stripe test mode, Azure portal config, etc.).
- Any new ADRs.
- Confirmation that all checks pass.

---

## 4. Repo Layout

```
.
├── CLAUDE.md                       # this file
├── docs/
│   ├── architecture.md             # source of truth
│   ├── right-sizing.md             # why a monolith, not microservices
│   └── runbooks/
├── app/                            # the FastAPI modular monolith
│   ├── main.py                     # app, lifespan, DI wiring, router includes
│   ├── api/                        # HTTP routers + request/response DTOs
│   ├── modules/                    # bounded contexts (the 8 domains)
│   │   ├── catalog/
│   │   ├── inventory/
│   │   ├── cart/
│   │   ├── order/
│   │   ├── payment/
│   │   ├── identity/
│   │   ├── search/
│   │   └── notification/
│   ├── platform/                   # shared infra: db, events, outbox, idempotency, otel, auth, settings
│   ├── worker/                     # Arq worker entrypoint + jobs
│   └── db/migrations/              # Alembic
├── web/
│   ├── storefront/                 # Next.js 15 SSR (+ thin BFF routes)
│   └── admin/                      # Vite + React SPA
├── infra/                          # Bicep modules + per-env params
│   ├── modules/
│   ├── envs/{dev,staging,prod}/
│   └── main.bicep
├── tools/                          # dev scripts, k6 load tests
├── pyproject.toml                  # uv project, ruff/mypy/pytest config
└── Makefile
```

Each module follows §17.2 of `docs/architecture.md`.

---

## 5. Code Standards

### 5.1 Python

- Python 3.12, managed with **uv**. `ruff` (lint + format) and `mypy --strict` configured in `pyproject.toml`.
- Library standard: `fastapi`, `pydantic` v2, `sqlalchemy` 2.0 async + `asyncpg`, `alembic`, `redis` (async), `arq`, `pydantic-settings`, `structlog`, `opentelemetry-*`, `httpx`, `pytest` + `pytest-asyncio` + `testcontainers`, `stripe` (Payment only), `azure-communication-email` (Notification only).
- Layering: `api → service → domain`, with `repository` behind interfaces the service owns. `api` never touches `repository` directly.
- One module never imports another module's `repository`, `domain`, or tables — only its `service`.
- Errors: raise typed domain exceptions (`app/modules/<m>/errors.py`); a global handler maps them to the envelope. No bare `except:`. No swallowing exceptions.
- Logging: `structlog`, JSON, one log = one line. Include `trace_id`, `module`, `event` keys.
- Time: `datetime.now()` is never called in `domain`/`service` — inject a `Clock`. Non-negotiable for testability.
- Typing: full annotations; `mypy --strict` must pass. No `Any` without a `# type: ignore[...]` and a reason.

### 5.2 SQL / persistence

- SQLAlchemy 2.0 async models; **Alembic** migrations in `app/db/migrations/`, one linear history.
- Tables are **prefix-namespaced by module**: `catalog_products`, `order_orders`, `inventory_reservations`, etc. A module's `repository.py` touches only its own prefix.
- Money columns: `BIGINT` storing minor units (cents). Never `FLOAT` or `NUMERIC` for amounts.
- IDs: `TEXT` primary keys with prefixed ULIDs (`prd_01H...`, `ord_01H...`). Never bare integers, never unprefixed UUIDs.
- Every table has `created_at`, `updated_at` (`TIMESTAMPTZ`). Most have `version INT NOT NULL DEFAULT 0` for optimistic locking.
- Indexes on all foreign keys and any column used in `WHERE`.
- No raw SQL string concatenation; use SQLAlchemy constructs or parameterized text.

### 5.3 HTTP APIs

- FastAPI generates the OpenAPI spec from routers + Pydantic models. The storefront/admin TypeScript client is generated from `/openapi.json`.
- JSON: `snake_case` fields. ISO 8601 timestamps with timezone. Amounts as integer minor units + currency code.
- Error envelope: `{"error": {"code": "string", "message": "string", "details": {}}}`. Status reflects semantics (400 validation, 404 missing, 409 conflict, 422 business rule, 500 unhandled).
- Pagination: cursor-based with `next_cursor`. No offset pagination.
- Versioning: URL prefix `/v1/...`. Breaking changes require `/v2/...` and a deprecation window.

### 5.4 Frontend

- Next.js 15 App Router for storefront. Server Components by default; `"use client"` only where interactivity is required.
- Vite + React 18 for admin.
- TypeScript strict mode. No `any` without an eslint-disable and a reason.
- State: TanStack Query for server state. No Redux. Local UI state with `useState` / `useReducer`.
- Forms: React Hook Form + Zod.
- Styling: Tailwind. shadcn/ui where appropriate.
- All user-facing strings in an i18n layer from day 1 (`next-intl` or equivalent), even if only `en-US` ships in MVP.

### 5.5 Bicep

- One module per logical resource group of components (`modules/containerapps.bicep`, `modules/postgres.bicep`).
- Parameters typed strictly. No shapeless `object` params.
- All resources tagged: `environment`, `app`, `owner`, `cost-center`.
- No hardcoded names. Use `uniqueString(resourceGroup().id)` patterns.

---

## 6. Testing Standards

- **Unit tests** live next to code: `foo.py` + `test_foo.py` (or `tests/` per module). Coverage ≥ 75% on packages you touch. Pure domain has no I/O and tests fast.
- **Integration tests** spin **real Postgres + Redis via testcontainers** — never SQLite-as-Postgres-substitute. Marked `@pytest.mark.integration`.
- **Contract tests** for events: each event payload is a Pydantic model with a round-trip test; subscribers test against it.
- **E2E tests** only for critical journeys (checkout, refund). Playwright for the storefront.
- **Load tests** in `tools/k6/` for checkout and search. Run in staging only.
- **No flaky tests tolerated.** Quarantine and fix within 48h or delete.
- `pytest` (unit subset) must pass with no env vars set.

---

## 7. Definition of Done

A ticket is done when all of the following are true:

- [ ] All acceptance criteria met.
- [ ] All commits follow Conventional Commits.
- [ ] `make lint type test build` passes locally and in CI.
- [ ] Integration tests pass if the module has them.
- [ ] Alembic migration added if the schema changed (and it's reversible).
- [ ] Bicep updated if infra changed.
- [ ] README or runbook updated if operations changed.
- [ ] ADR added for any consequential decision not covered by `docs/architecture.md`.
- [ ] No new secrets in code; Key Vault Bicep updated if a new secret was added.
- [ ] No cross-module imports of another module's internals (import-linter clean).
- [ ] No `TODO` without a ticket reference (`# TODO(F2.7): ...`).

---

## 8. When to Ask the User

Ask before proceeding when:

- The ticket conflicts with `docs/architecture.md`.
- You would add a new external dependency (new SaaS, new Azure service, new top-level library).
- You would make a breaking schema change to a module already deployed.
- A test failure suggests a real bug in code you didn't touch.
- You would need credentials, API keys, or access you don't have.
- The work exceeds ~1500 LOC or ~6 hours of agent work.
- A ticket seems to want a saga, a message broker, or a service extraction (these are deliberately deferred — confirm first).

Otherwise, proceed and explain in the hand-off.

---

## 9. What NOT to Do

- Do not extract a module into a standalone service, add a service mesh, add a second message broker, or introduce saga choreography. The design defers all of this until a module earns it (ADR-002). If a ticket seems to need it, ask.
- Do not invent Azure resource names, SDK functions, or API endpoints. Search docs or ask.
- Do not "improve" code outside the ticket's scope. Note opportunities in a follow-up ticket instead.
- Do not run `az deployment ... create`, `az containerapp update`, or any apply-style command against any environment without explicit user confirmation in the current session. CI and the user run those.
- Do not create new branches without asking. Work on the branch the user is on.
- Do not delete or rewrite Alembic migrations that have been applied to any environment.
- Do not disable tests to make a build green. Fix them or ask.
- Do not add fields to an event without bumping its version (`ProductUpdatedV1` → `V2`).
- Do not reach into another module's tables or internals to "save a call." Use its `service.py`.
- Do not write blocking/sync I/O on the request path.

---

## 10. Tooling Quick Reference

```bash
# At the repo root
make help                           # list available targets
make dev                            # run API + worker against docker-compose Postgres/Redis
make lint                           # ruff check + format --check
make type                           # mypy --strict
make test                           # pytest unit tests
make integration                    # pytest integration (testcontainers)
make build                          # build Docker image

uv sync                             # install/resolve dependencies
uv run uvicorn app.main:app --reload    # run the API locally
uv run arq app.worker.main.WorkerSettings   # run the worker locally
uv run alembic revision --autogenerate -m "add catalog_products"
uv run alembic upgrade head
uv run pytest path/to/test_x.py::test_name   # run a single test

# Infra (never run against an env without confirmation; CI does this)
cd infra && az deployment group what-if ...

# Frontend (cd web/<app>)
pnpm dev / lint / typecheck / test / build
```

---

## 11. Glossary

- **Module** — a bounded context (Catalog, Order, …) living as a package under `app/modules/`, exposing a `service.py` interface and owning its tables. The unit of decoupling — *not* a separate deployable.
- **BFF** — Backend For Frontend. The thin Next.js server layer that holds auth tokens for the storefront. The admin has none (it calls the API directly).
- **Outbox** — a table where a module writes an outgoing external action (Stripe call, email) in the same transaction as business state; the worker drains it.
- **In-process event bus** — synchronous publish/subscribe within the app for cross-module facts. No network, no broker.
- **Worker** — the Arq process (same codebase) that drains the outbox, runs the reservation sweep, and handles abandoned-cart jobs.
- **PE / Private Endpoint** — Azure private networking for PaaS, no public access.

---

## 12. Roadmap Overview

Complete a phase before starting the next unless told otherwise.

| Phase | Theme | Tickets |
|---|---|---|
| 0 | Foundations: app skeleton, `app/platform/`, infra, CI | F0.1–F0.7 |
| 1 | Catalog + Search + Storefront browse | F1.1–F1.15 |
| 2 | Identity + Cart + Storefront account | F2.1–F2.10 |
| 3 | Inventory + Order skeleton + Checkout UI | F3.1–F3.9 |
| 4 | Payment + Notification + Checkout end-to-end | F4.1–F4.10 |
| 5 | Admin operational features | F5.1–F5.7 |
| 6 | Hardening: load, failure drills, security review | F6.1–F6.4 |

---

## 13. Feature Backlog

Every ticket has: **ID**, **Title**, **Depends on**, **Acceptance criteria**, **Size** (S ≤ 4h, M ≤ 1 day, L ≤ 2 days of agent work). Tickets marked `requires plan approval` need the plan confirmed before coding.

---

### Phase 0 — Foundations

#### F0.1 — App + repo scaffolding `requires plan approval` `M`

**Acceptance:**
- Repo layout matches §4. `pyproject.toml` with uv, ruff, mypy (strict), pytest config.
- `app/main.py` FastAPI app with lifespan, `/healthz`, `/readyz`, structured logging, OpenTelemetry stub.
- Root `Makefile` with `help`, `dev`, `lint`, `type`, `test`, `integration`, `build`.
- `docker-compose.yml` for local Postgres + Redis. `Dockerfile` per §17.3.
- `.editorconfig`, `.gitignore`, `.gitattributes`, `LICENSE`, root `README.md`.
- Pre-commit hooks: ruff (lint+format), mypy, conventional-commit message check.
- Renovate/Dependabot for uv, npm, GitHub Actions, Bicep.

#### F0.2 — CI pipeline `S` *(depends: F0.1)*

**Acceptance:**
- One GitHub Actions workflow: ruff → mypy → pytest (with Postgres/Redis service containers) → build image → Trivy scan → push to ACR on `main`.
- Reusable workflow steps for the frontends (lint/typecheck/test/build).
- Bicep workflow: `what-if` on PR, deploy on tag.
- Status badges in root README.

#### F0.3 — Bicep landing zone `M` *(depends: F0.1)*

**Acceptance:**
- `infra/modules/network.bicep`: VNet per env, `pe-subnet`, Container Apps subnet.
- `infra/modules/containerapps.bicep`: Container Apps environment (VNet-integrated, internal), App Insights + Log Analytics wired.
- `infra/modules/acr.bicep`, `infra/modules/keyvault.bicep` (RBAC, soft-delete + purge protection, private endpoint).
- Private DNS zones for Postgres, Key Vault, Redis, Blob.
- `infra/envs/dev/main.bicep` deploys with `what-if` clean.

#### F0.4 — Bicep data tier `M` *(depends: F0.3)*

**Acceptance:**
- `infra/modules/postgres.bicep`: Flexible Server, zone-redundant HA for prod, 35-day geo-redundant backups, private endpoint only.
- `infra/modules/redis.bicep`: Azure Cache for Redis Standard C1, private endpoint.
- `infra/modules/blob.bicep`: storage account, RA-GRS, soft-delete + versioning.
- All resources reachable only from the Container Apps subnet.

#### F0.5 — Bicep edge tier `M` *(depends: F0.3)*

**Acceptance:**
- `infra/modules/frontdoor.bicep`: Front Door Premium, WAF policy (OWASP CRS), rate limits for `/auth/*` and `/checkout/*`, bot rules, origin = Container Apps ingress.
- CDN behavior for `/media/*` (Blob origin).

#### F0.6 — `app/platform/` shared modules `L` `requires plan approval` *(depends: F0.1)*

**Acceptance:**
- `platform/settings.py`: pydantic-settings, 12-factor env.
- `platform/db.py`: async engine, session-per-request dependency, transaction helper.
- `platform/events.py`: in-process event bus (typed publish/subscribe, sync within request).
- `platform/outbox.py`: outbox table model + drain helper used by the worker.
- `platform/idempotency.py`: Redis-backed middleware/decorator storing `(key, request_hash, response)` 24h TTL; cached response on duplicate, 409 on key reuse with different body.
- `platform/otel.py`: bootstrap traces/metrics/logs → App Insights; graceful shutdown.
- `platform/auth.py`: JWT validation dependency (Entra), role-check helpers.
- `app/worker/main.py`: Arq `WorkerSettings` wiring outbox drain + scheduled jobs.
- ≥ 85% test coverage on `platform/`; docstrings on every public symbol.

#### F0.7 — Observability baseline `S` *(depends: F0.3, F0.6)*

**Acceptance:**
- OpenTelemetry auto-instrumentation live for FastAPI, SQLAlchemy, redis, httpx → App Insights.
- Dashboards: app health, golden signals, business-KPI placeholders.
- Alert rules: SLO budget burn, outbox dead-letter depth, worker-not-draining, image pull failure.
- `docs/runbooks/observability.md` stub: how to debug a slow request.

---

### Phase 1 — Catalog + Search + Storefront browse

#### F1.1 — Catalog module skeleton `M` `requires plan approval` *(depends: F0.6)*

**Acceptance:**
- `app/modules/catalog/` with `domain.py`, `service.py`, `repository.py`, `events.py` (documented stubs); `app/api/catalog.py` router mounted.
- `platform`-based db, otel, idempotency, auth wired.
- Import-linter contract added asserting no other module imports catalog internals.
- One smoke test: `GET /healthz → 200` and the catalog router is reachable.

#### F1.2 — Catalog domain model `S` *(depends: F1.1)*

**Acceptance:**
- Domain types: `Product`, `Variant`, `Category`, `Collection`, `Media`, `Price` (minor units + currency).
- Value objects: `SKU`, `Slug`, `MetalType`, `Gemstone`, `RingSize`.
- Aggregate root `Product` owns its variants and media metadata.
- Unit tests for invariants (no variant without parent, price ≥ 0, slug uniqueness within scope). Pure domain, no DB.

#### F1.3 — Catalog schema + migration `S` *(depends: F1.2)*

**Acceptance:**
- Alembic migration creates `catalog_products`, `catalog_variants`, `catalog_categories`, `catalog_collections`, `catalog_media`, `catalog_outbox`.
- Tables follow §5.2 (ULID IDs, money BIGINT, version column, TIMESTAMPTZ).
- Reversible migration; `repository.py` reads/writes via SQLAlchemy.

#### F1.4 — Catalog CRUD APIs `M` *(depends: F1.3)*

**Acceptance:**
- Routes: create/get/update/archive product, list with filters, manage variants, media metadata, categories, collections.
- Pydantic request/response models; validation at the edge.
- Optimistic concurrency via `version`.
- Unit tests (fake repo) + integration tests (testcontainers).
- Authz: admin role required (JWT claim verified by `platform/auth`).

#### F1.5 — Catalog event publishing `S` *(depends: F1.4)*

**Acceptance:**
- `ProductCreatedV1`, `ProductUpdatedV1`, `ProductArchivedV1` published on the in-process bus.
- Round-trip contract tests for each payload.
- Integration test asserts an event fires when a product is created.

#### F1.6 — Catalog Blob upload via SAS `S` *(depends: F1.1)*

**Acceptance:**
- `POST /v1/media/upload-url` returns a short-lived SAS URL for direct browser upload.
- Catalog stores media metadata (URL, dimensions, alt text), not bytes.
- Front Door CDN serves from the Blob endpoint.
- Allowed MIME types and max size enforced via SAS policy.

#### F1.7 — Search module skeleton `S` *(depends: F0.6)*

**Acceptance:** Same skeleton pattern as F1.1; import-linter contract; smoke test passes. No business logic yet.

#### F1.8 — Search index schema `S` *(depends: F1.7)*

**Acceptance:**
- Index definition (Postgres FTS columns/`tsvector` for MVP, abstracted so an AI Search swap is local): searchable (name, description, materials), facetable (metal, gemstone, category, price bucket), sortable, suggester for autocomplete.
- Scoring boosts in-stock and recent products.
- Bootstrap routine builds/updates the index on startup.

#### F1.9 — Search event consumer `M` *(depends: F1.5, F1.8)*

**Acceptance:**
- Search subscribes to `ProductCreated/Updated/Archived` on the in-process bus and projects into the index.
- Idempotent: re-applying an event yields the same index state.
- Integration test: publish event → document appears/updates in index.

#### F1.10 — Search query API `M` *(depends: F1.8)*

**Acceptance:**
- `GET /v1/search?q=&filter=&facet=&sort=&cursor=` returns products, facets, total, next cursor.
- `GET /v1/search/suggest?q=` returns autocomplete suggestions.
- P95 < 300ms in dev for queries returning < 50 results.
- Unit tests on query construction; integration tests against real Postgres FTS.

#### F1.11 — Storefront Next.js scaffolding `M` `requires plan approval` *(depends: F0.2)*

**Acceptance:**
- `web/storefront/` Next.js 15 App Router, TS strict, Tailwind, shadcn/ui.
- Layout (header, footer, nav). i18n configured (`en-US`), no raw strings.
- Lighthouse CI baseline in PR checks.
- Deployable as a Container App.

#### F1.12 — Storefront PLP `M` *(depends: F1.10, F1.11)*

**Acceptance:**
- `/[category]` renders products from Search.
- Filters (metal, gemstone, price, in-stock), sort, cursor pagination.
- SSR with structured data (`ItemList`, `Product` JSON-LD).
- Mobile-first, route JS < 80 KB. Lighthouse ≥ 90 Performance + SEO.

#### F1.13 — Storefront PDP `M` *(depends: F1.12)*

**Acceptance:**
- `/products/[slug]` SSR with full product data.
- Image gallery with zoom (no JS for first paint).
- Variant selector (metal/karat/size/stone), client-side price update.
- Engraving input with counter + live preview (no submit yet — F2.8 wires cart).
- Size guide modal; "notify when back in stock" stub. Structured data (`Product`, `Offer`).

#### F1.14 — Admin SPA scaffolding `M` `requires plan approval` *(depends: F0.2)*

**Acceptance:**
- `web/admin/` Vite + React 18 + TS strict + Tailwind + shadcn/ui.
- Router, layout (sidebar + topbar), placeholder dashboard/settings/products/orders/customers.
- Auth gate placeholder redirecting to Entra ID (wired in F5.1). Deployable.

#### F1.15 — Admin product management UI `M` *(depends: F1.4, F1.14)*

**Acceptance:**
- Product list with search/filter/pagination.
- Create/edit form: name, rich-text description, category, collection, variant matrix, media upload (direct to Blob via SAS), price.
- Archive (soft delete). Optimistic concurrency surfaced (409 → reload). CSV import stub (UI only).

---

### Phase 2 — Identity + Cart + Account

#### F2.1 — Entra External ID setup `S` `requires plan approval`

**Acceptance:**
- External ID tenant created (manual; documented in runbook).
- User flows: sign-up/sign-in with email + Google + Apple; password reset.
- App registrations for storefront BFF (confidential client) and the API (resource server).
- Bicep updated with tenant ID / client IDs (secret in Key Vault).

#### F2.2 — Identity module + schema `S` *(depends: F0.6)*

**Acceptance:**
- Entities `Customer`, `Address`, `Preferences`. Migration for `identity_customers`, `identity_addresses`, `identity_preferences`.
- `identity_customers.external_id` references the External ID `oid` claim — the join key, never email.

#### F2.3 — Identity APIs `M` *(depends: F2.2)*

**Acceptance:**
- `GET /v1/customers/me`, `PATCH /v1/customers/me`, address CRUD.
- JIT provisioning: on first authenticated request, create the local `Customer` from JWT claims.
- Emits `CustomerRegisteredV1`, `CustomerUpdatedV1`.

#### F2.4 — Storefront BFF scaffolding `M` `requires plan approval` *(depends: F0.2)*

**Acceptance:**
- Thin BFF inside `web/storefront/` (Next.js route handlers): health, structured logging, OTel.
- Generates a TS client from the API's `/openapi.json` on build.
- Its only job is auth-token custody + request proxying; no business logic.

#### F2.5 — Storefront auth flow `M` *(depends: F2.1, F2.4)*

**Acceptance:**
- OAuth2 code + PKCE: BFF starts the flow, handles callback, exchanges code for tokens.
- Refresh tokens in httpOnly+secure+sameSite=lax cookies — never in browser JS.
- Access token attached server-side on storefront → API calls. Sign-out clears cookies and revokes the refresh token.
- Integration test simulates the full flow.

#### F2.6 — Cart module + Redis storage `M` *(depends: F0.6)*

**Acceptance:**
- Domain `Cart`, `LineItem`, `AppliedDiscount`, `CustomAttribute` (engraving).
- Redis storage with 30-day TTL, key `cart:{cartId}`. Postgres `cart_converted` for converted-cart audit only.
- Optimistic concurrency on Redis writes (`WATCH`/Lua).

#### F2.7 — Cart APIs `M` *(depends: F2.6)*

**Acceptance:**
- `POST /v1/carts` (anonymous), `GET /v1/carts/{id}`, add/patch/delete items, `POST /v1/carts/{id}/merge` (anonymous → customer on sign-in).
- Pricing snapshot stored per line item — no recalculation from Catalog on read.
- Idempotency on add and merge.

#### F2.8 — Cart engraving + custom attributes `S` *(depends: F2.7)*

**Acceptance:**
- `custom_attributes` on line items, typed by product configuration.
- Server-side validation against the variant's allowed attributes; engraving char limit + allowed charset enforced.

#### F2.9 — Storefront cart UI `M` *(depends: F2.7, F1.13)*

**Acceptance:**
- Mini-cart drawer (line items, subtotal, checkout CTA). Cart page with quantity edit, remove, promo placeholder.
- Cart persists across reload via a `cart_id` cookie. "Sign in to save your cart" prompt for anonymous carts.

#### F2.10 — Storefront account pages `M` *(depends: F2.3, F2.5)*

**Acceptance:**
- `/account` dashboard: recent orders (stub — wired in F4.x), saved addresses, preferences.
- Address CRUD UI (Azure Maps autocomplete). Profile edit (name, email, marketing opt-in).

---

### Phase 3 — Inventory + Order skeleton + Checkout UI

#### F3.1 — Inventory module + domain `S` *(depends: F0.6)*

**Acceptance:**
- Skeleton + domain: `StockItem` (variant + location), `Reservation`, `Movement` (audit).
- Invariants: available = on_hand − reserved; cannot reserve more than available. Import-linter contract.

#### F3.2 — Inventory schema with SKIP LOCKED `M` *(depends: F3.1)*

**Acceptance:**
- Tables `inventory_stock_items`, `inventory_reservations`, `inventory_movements`.
- Reservation claim uses `SELECT … FOR UPDATE SKIP LOCKED`.
- Integration test: concurrent reservations — no oversell, no deadlock.

#### F3.3 — Inventory service API `S` *(depends: F3.2)*

**Acceptance:**
- `service.py` exposes `reserve(reservation_id, items, ttl)`, `commit(reservation_id)`, `release(reservation_id)` — called in-process by Order, idempotent on `reservation_id`, 15-min default TTL.
- `GET /v1/stock/{variantId}` returns available; `POST /v1/movements` (admin: receive/adjust/write-off).
- Emits `StockReservedV1`, `StockReleasedV1`, `StockUpdatedV1`, `LowStockReachedV1`.

#### F3.4 — Inventory expiry sweep `S` *(depends: F3.3)*

**Acceptance:**
- Arq job runs every 30s, releases reservations past `expires_at`, emits `StockReleasedV1` (reason `expired`).
- Guarded by a Postgres advisory lock so only one worker sweeps.

#### F3.5 — Order module + state machine `M` *(depends: F0.6)*

**Acceptance:**
- States: `pending`, `awaiting_payment`, `paid`, `fulfilling`, `shipped`, `delivered`, `cancelled`, `payment_failed`, `refunded`, `partially_refunded`.
- Explicit transition table in `states.py`; invalid transitions raise `InvalidTransitionError`.
- Unit tests for every valid and invalid transition.

#### F3.6 — Order schema + outbox `S` *(depends: F3.5)*

**Acceptance:** `order_orders`, `order_line_items`, `order_outbox` tables per §5.2; outbox wired to the worker drain.

#### F3.7 — Order creation API `M` *(depends: F3.3, F3.6)*

**Acceptance:**
- `POST /v1/orders` accepts cart snapshot + customer + shipping address + method.
- **Single transaction**: calls `inventory.reserve(...)` and inserts the order in `pending` in the same DB transaction; on any failure, nothing is reserved.
- Returns `order_id` + reservation expiry. Idempotency on the endpoint.

#### F3.8 — Order events `S` *(depends: F3.7)*

**Acceptance:** `OrderCreatedV1` and the transition events (`OrderPaid`, `OrderShipped`, …; most wired in Phase 4) defined as Pydantic payloads with contract tests.

#### F3.9 — Storefront checkout page (no payment) `M` *(depends: F3.7, F2.9)*

**Acceptance:**
- `/checkout` SSR: address selector, shipping method, order summary. Server-side validation, inline errors.
- "Continue to payment" creates the order and shows a placeholder payment panel.

---

### Phase 4 — Payment + Notification + Checkout end-to-end

#### F4.1 — Payment module skeleton `S` *(depends: F0.6)*

**Acceptance:** Standard skeleton + import-linter contract. Only this module imports `stripe`. `payment_*` tables stubbed.

#### F4.2 — Payment intent creation `M` *(depends: F4.1, F3.7)*

**Acceptance:**
- `POST /v1/payment-intents` accepts order ID, returns `client_secret`.
- Stripe customer created/reused from local customer. Idempotency key passed to Stripe.
- Persists `payment_intents` row tying Stripe ID to order ID.

#### F4.3 — Payment webhook handler `L` `requires plan approval` *(depends: F4.2)*

**Acceptance:**
- `POST /webhooks/stripe` validates `Stripe-Signature` against the Key Vault signing secret.
- Dedupes on `event.id` via Redis (24h TTL).
- Handles `payment_intent.succeeded`, `payment_intent.payment_failed`, `charge.refunded`.
- On success: **one transaction** commits the reservation, flips the order to `paid`, and writes the email outbox row; returns 200 only after commit.
- Out-of-order events handled gracefully. Integration test fires real webhooks via Stripe CLI.

#### F4.4 — Payment refund API `M` *(depends: F4.3)*

**Acceptance:**
- `POST /v1/refunds` (payment intent ID + amount + reason), calls Stripe Refunds idempotently.
- Emits `RefundProcessedV1` on the `charge.refunded` webhook, not on the API response. Partial + full-remaining refunds correct.

#### F4.5 — Checkout end-to-end `L` *(depends: F4.3, F3.3)*

**Acceptance:**
- Happy path: webhook → commit reservation → order `paid` → `OrderPaidV1` → email.
- Failure path: `payment_failed` webhook → release reservation → order `payment_failed`.
- Expiry path: sweep releases reservation → still-`pending` order is cancelled.
- E2E integration test covers all three.

#### F4.6 — Notification module + templates `S` *(depends: F0.6)*

**Acceptance:**
- Skeleton; Jinja2 templates (HTML + text) in `app/modules/notification/templates/`; hot-reload in dev.
- Each template has a Pydantic input model.

#### F4.7 — Notification ACS integration `M` *(depends: F4.6)*

**Acceptance:**
- Sends via Azure Communication Services Email. Logs send + delivery status; ingests delivery reports.
- Bounce/complaint marks the customer undeliverable in Identity (via event, eventual consistency).

#### F4.8 — Notification event/worker consumer `M` *(depends: F4.7, F4.5)*

**Acceptance:**
- Worker handles `OrderCreated`, `OrderPaid`, `OrderShipped`, `OrderRefunded`, `CartAbandoned` (via outbox/events): renders the right template and sends.
- Idempotent — replay does not double-send.

#### F4.9 — Storefront Stripe Elements `M` *(depends: F4.2, F3.9)*

**Acceptance:**
- Stripe Elements on `/checkout/payment`; 3DS handled. On success, poll Order for `paid` then redirect to `/checkout/confirmation`.
- On failure, surface the error and allow retry. Apple Pay + Google Pay enabled.

#### F4.10 — Abandoned cart scheduling `S` *(depends: F4.8)*

**Acceptance:**
- On cart update, enqueue a delayed Arq job (`defer_by = 1h`).
- Worker checks cart status before sending — skips if converted. Cancellation on `CartConvertedV1`.

---

### Phase 5 — Admin operational

#### F5.1 — Admin auth (Entra ID workforce) `M` *(depends: F1.14)*

**Acceptance:**
- OIDC against the Entra ID workforce tenant; admin SPA calls the API directly with its token.
- Role mapping from group membership: `admin`, `staff`, `fulfillment`. Conditional Access compatible (MFA enforced).

#### F5.2 — Admin order list + detail `M` *(depends: F4.5, F1.15)*

**Acceptance:**
- List with filters (status, date range, customer search, amount).
- Detail with full timeline (transitions + payment events + notifications). Packing slip + invoice PDF (server-side).

#### F5.3 — Admin order status updates `S` *(depends: F5.2)*

**Acceptance:** Mark shipped (tracking per carrier), delivered, cancel (with reason). Each requires `fulfillment` or `admin`.

#### F5.4 — Admin refunds `S` *(depends: F5.2, F4.4)*

**Acceptance:** Refund modal (full/partial, reason, notes), requires `admin`, audit log entry on every refund.

#### F5.5 — Admin customer management `S` *(depends: F2.3)*

**Acceptance:** Customer list (LTV, order count, last order); detail (history, addresses, internal notes); anonymize (GDPR) replacing PII while keeping order records.

#### F5.6 — Admin sales dashboard `M` *(depends: F5.2)*

**Acceptance:** KPIs (revenue today/7d/30d, orders, AOV, refund rate); charts (orders over time, revenue by category, top products). Sourced from a read model populated by event subscriptions, not cross-module table reads.

#### F5.7 — Discount codes (simple) `M` *(depends: F2.7)*

**Acceptance:**
- Admin creates codes: percentage or fixed, min order value, usage cap, expiry, scope (all/category/product).
- `POST /v1/carts/{id}/discounts` applies a code, validates rules, attaches to cart. Storefront shows the applied discount.
- (Full Pricing & Promotion is v2 — this is the minimal version.)

---

### Phase 6 — Hardening

#### F6.1 — k6 load tests `M`

**Acceptance:** Scenarios for PLP, PDP, search, full checkout (Stripe test mode). Runs in CI against staging on tag. Pass criteria: SLOs (architecture §11) met at target load (e.g. 50 concurrent checkouts).

#### F6.2 — Failure drills `M`

**Acceptance:** Documented drills: replica kill (API, worker), Postgres failover, Stripe webhook delay, reservation-expiry race. Each has a runbook in `docs/runbooks/`. Run quarterly (`tools/chaos/`).

#### F6.3 — Security review `M` `requires plan approval`

**Acceptance:** SAQ A walkthrough (no card data anywhere); secret scan over git history (gitleaks); dependency audit (`pip-audit`, `npm audit`, Trivy); network review (private endpoints, no public PaaS); threat model in `docs/security/threat-model.md`.

#### F6.4 — Operational runbooks `S`

**Acceptance:** Runbooks for stuck refund, webhook replay, oversold-inventory recovery, GDPR data export, incident response. Each: symptoms, diagnosis, remediation, escalation.

---

## 14. Out of Scope for MVP

Explicit non-goals. Do not start them; redirect to v2 planning.

- Reviews/ratings, recommendations/personalization, loyalty/rewards, subscriptions
- B2B/wholesale, multi-currency/multi-region, marketplace/multi-vendor
- AR try-on, bridal ring builder
- CMS for editorial content (use a headless CMS if needed, do not build)
- Mobile native apps
- **Any service extraction, service mesh, second message broker, or saga** — deferred until a module earns it (ADR-002).

---

## 15. When You're Stuck

In priority order:

1. Reread `docs/architecture.md` and this file.
2. Search the codebase: `git grep`, `rg`.
3. Search the relevant official docs (Azure, Stripe, FastAPI/SQLAlchemy/library docs).
4. If still stuck after ~20 minutes, summarize what you tried and the blocker, and ask the user.
