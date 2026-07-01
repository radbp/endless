# Right-Sizing Note — Modular Monolith vs. 8-Service Distributed

**Status:** Decision aid (read alongside `docs/architecture.md`)
**Question:** Is the distributed AKS design the right altitude for a store doing ~100 orders/day and ~10k SKUs?
**Short answer:** No. Build a **modular monolith in Python/FastAPI**. Keep every domain boundary the architecture already defines; drop the operational machinery that only pays off at 10–100× this volume. Extract a service the day a module actually needs it — not before.

---

## 1. The mismatch in one table

The current design's own driver (`architecture.md` §2) says *"Don't over-engineer for FAANG scale. ~100 orders/day, ~10k SKUs is the target."* The rest of the document then builds for FAANG scale anyway. Concretely:

| Capability in current design | What it's for | Needed at 100 orders/day? |
|---|---|---|
| 8 independently deployed services | Independent scaling & team ownership | No — one team, uniform load |
| AKS + 3 node pools | Bin-packing many services | No — a few containers |
| Linkerd service mesh (mTLS, retries) | Securing/observing many service-to-service hops | No — almost no in-process→network hops if it's one process |
| Service Bus **and** Event Grid | Distinct command/event semantics across services | No — one in-process event bus + one durable queue covers it |
| Saga + compensations for checkout | Coordinating a transaction across service boundaries | No — checkout is a single DB transaction in a monolith |
| Transactional outbox per service | Reliable publish across a network boundary | Rarely — only at the two real external edges (Stripe, email) |
| CQRS read model in Azure AI Search | Decouple read load from write services | Partially — keep search, but it's an index, not an architecture |
| 8 CI/CD pipelines + GitOps/Flux | Many deployables, many release cadences | No — one pipeline, one deploy |
| APIM + per-channel BFFs | Many backends to aggregate & govern | No — the app *is* the backend |

The thing that costs you isn't writing the services. It's **operating eight of them**: eight pipelines, eight Helm charts, a mesh, dual messaging, saga choreography to debug, and read models to keep eventually-consistent — all carried 24/7 to serve a few hundred requests a day.

---

## 2. What the modular monolith keeps

**Everything that creates value; nothing that creates distribution.**

You keep the *exact* domain decomposition from `architecture.md` §5 — Catalog, Inventory, Cart, Order, Payment, Identity, Search, Notification — as **internal modules (packages)** behind clean interfaces, not as network services. The boundaries survive; the wires disappear.

```
endless/
├── app/
│   ├── main.py                     # FastAPI app, lifespan, DI wiring, routers
│   ├── api/                        # HTTP routers (one per module) + DTOs
│   │   ├── catalog.py
│   │   ├── cart.py
│   │   ├── checkout.py
│   │   └── ...
│   ├── modules/                    # the 8 domains — each a self-contained package
│   │   ├── catalog/
│   │   │   ├── domain.py           # entities, value objects, invariants
│   │   │   ├── service.py          # use cases (the module's public interface)
│   │   │   ├── repository.py       # Postgres access (this module's tables only)
│   │   │   └── events.py           # domain events this module emits
│   │   ├── inventory/
│   │   ├── cart/
│   │   ├── order/
│   │   ├── payment/                # only module that imports stripe
│   │   ├── identity/
│   │   ├── search/                 # owns the AI Search / Postgres FTS index
│   │   └── notification/           # only module that sends email
│   ├── platform/                   # shared infra (the old pkg/)
│   │   ├── db.py                   # one engine, one session-per-request
│   │   ├── events.py               # in-process event bus + durable outbox
│   │   ├── idempotency.py          # decorator/middleware, Redis-backed
│   │   ├── otel.py                 # tracing/metrics/logs bootstrap
│   │   └── settings.py             # pydantic-settings, 12-factor env
│   └── db/
│       ├── migrations/             # Alembic — one schema, module-prefixed tables
│       └── ...
├── web/                            # storefront (Next.js) + admin (React) — UNCHANGED
└── docs/
```

**Module isolation discipline (the rule that makes later extraction free):**
- A module talks to another module **only through its `service.py` interface** — never by importing its `repository.py` or touching its tables. This is the in-process equivalent of "no cross-schema queries," and a lint/import check enforces it (e.g. `import-linter` contracts).
- Modules communicate via the **in-process event bus** for facts (`ProductUpdated`, `OrderPaid`) and **direct service calls** for commands (`inventory.reserve(...)`). Same shape as the distributed design, minus the network.
- Each module owns its tables (`catalog_*`, `order_*`, …) in the single Postgres database. No joins across module prefixes.

If you hold that discipline, extracting `inventory` into its own service later is a mechanical change: swap the in-process `inventory.reserve()` call for an HTTP/gRPC client, move its tables to their own DB. The domain code doesn't move.

---

## 3. What changes per concern

| Concern | Current (distributed) | Modular monolith | Why it's fine here |
|---|---|---|---|
| **Runtime** | 8 services on AKS | 1 FastAPI app (run 2–3 replicas for HA) | One deployable, trivial to reason about |
| **Hosting** | AKS + node pools + mesh | **Azure Container Apps** (or App Service) | No cluster to operate; scale-to-N built in |
| **Inter-module** | mTLS HTTP / gRPC + Service Bus + Event Grid | In-process calls + in-process event bus | No network = no mesh, no dual brokers |
| **Checkout** | Saga across Order/Inventory/Payment with compensations | **One DB transaction**: reserve + create order atomically; commit on Stripe webhook | Local ACID beats choreographed eventual consistency |
| **Reliable async** | Outbox in every service | Outbox table **only** at external edges (publish to Stripe is sync; sending email is the one durable handoff) | Two edges, not eight |
| **Background work** | Per-service goroutine workers | **Arq** or **Celery** workers (Redis-backed) for email send, reservation sweep, abandoned-cart | One worker process, same code repo |
| **Reservation hot path** | gRPC + `SELECT … FOR UPDATE SKIP LOCKED` + sweeper goroutine | Same SQL (`FOR UPDATE SKIP LOCKED`) as an in-process call; sweeper is a scheduled worker job | The SQL was always the real mechanism — gRPC was incidental |
| **Search** | Separate service consuming events into AI Search | `search` module subscribes to the in-process bus; index in AI Search **or Postgres FTS** for MVP | Postgres FTS handles 10k SKUs comfortably; AI Search when facets/relevance demand it |
| **Auth** | APIM JWT validation + BFF token handling | FastAPI dependency validates Entra External ID JWT; same httpOnly-cookie BFF pattern in Next.js | No APIM tier to run |
| **Secrets** | Key Vault + CSI driver in cluster | Key Vault via Container Apps managed identity | Same vault, simpler mount |
| **DB** | Schema-per-service, one server | Table-prefix-per-module, one server | Identical isolation guarantee, less ceremony |
| **CI/CD** | 8 pipelines + GitOps/Flux | One pipeline: test → build image → deploy | One thing to release |
| **Frontends** | Next.js storefront + React admin | **Unchanged** | The web tier was right-sized already |

---

## 4. Python stack (mirrors `architecture.md` §17, Python-native)

| Concern | Library | Replaces (Go) |
|---|---|---|
| Web framework | **FastAPI** + Uvicorn | chi |
| Validation/DTOs | **Pydantic v2** | validator/v10 |
| DB access | **SQLAlchemy 2.0** (async) + **asyncpg** | pgx/sqlc |
| Migrations | **Alembic** | goose |
| Cache / idempotency / queues | **redis-py** (async) | go-redis |
| Background jobs | **Arq** (lean) or **Celery** (mature) | goroutine workers |
| Config | **pydantic-settings** | viper |
| Logging | **structlog** → JSON, one line per log | slog |
| Tracing/metrics | **opentelemetry-python** → App Insights | otel-go |
| Stripe | **stripe** (official) — `payment` module only | stripe-go |
| Email | **azure-communication-email** | ACS Go SDK |
| Search | **azure-search-documents** *or* Postgres FTS | azsearch |
| Testing | **pytest** + **testcontainers** (real Postgres/Redis) | testify |
| Lint/format | **ruff** + **mypy** (strict) | golangci-lint |
| Packaging | **uv** | go modules |
| Container | python:3.12-slim multi-stage (~80–120MB) | distroless (~15MB) |

The one honest tradeoff: container images are ~80–120MB vs Go's ~15MB, and you carry a runtime. At 2–3 replicas this is noise.

---

## 5. The backlog barely changes

The Phase 0–6 backlog in `CLAUDE.md` §13 maps almost 1:1 — the domain tickets (F1.2 catalog model, F3.3 reservation, F3.8 order state machine, F4.3 webhook handler, …) are **identical work**; only their packaging changes. What collapses or drops:

- **F0.3–F0.8 (Bicep network/AKS/mesh/Flux):** replaced by one much smaller `infra/` — Container Apps env, Postgres, Redis, Key Vault, Blob, Front Door. Roughly a third of the infra surface.
- **F0.9 (`pkg/` shared modules):** becomes `app/platform/` — same five concerns (logging, otel, idempotency, events, outbox), one package, no semver/tagging dance.
- **Saga tickets (F4.5):** shrink from "choreograph across services + compensations + reservation-expiry race" to "one transaction + a webhook handler + a scheduled sweep."
- **Dual messaging (Service Bus + Event Grid wiring across F1.5, F1.9, F4.9, F4.11):** becomes in-process bus subscriptions + one durable queue for email/abandoned-cart.
- **BFF tickets (F2.5, F5.1):** the FastAPI app *is* the backend; storefront keeps the thin BFF only for the auth-cookie pattern, admin can call the API directly.

Net: same product, materially less Phase 0, simpler Phase 4. An agent working ticket-by-ticket has *one* codebase, one test suite, one `make dev` — a much better fit for the CLAUDE.md workflow loop.

---

## 6. When to extract a service (the off-ramp)

You are not locked in. Promote a module to a standalone service the moment **one** of these is true for it — and only it:

- It needs a different scaling profile (e.g. Search gets hammered while everything else is idle).
- It needs a different release cadence or a separate team owns it.
- It needs a different datastore/RPO that the shared Postgres can't give.
- Its load genuinely threatens the rest of the process.

Because modules already talk only through `service.py` interfaces and own their tables, extraction is: wrap the interface in an HTTP/gRPC client, move the tables, stand up a deploy. The domain logic is untouched. **This is exactly the optionality `architecture.md` §1 wants — achieved by discipline instead of by paying the distribution tax up front.**

---

## 7. Recommendation

1. **Build a modular monolith in Python/FastAPI**, preserving the 8-domain decomposition as enforced internal modules.
2. **Host on Azure Container Apps**, not AKS.
3. **Keep:** the domain models, the state machine, `FOR UPDATE SKIP LOCKED` reservation, idempotency, the storefront/admin frontends, Postgres/Redis/Stripe/Entra/ACS choices.
4. **Defer until a module earns it:** independent services, service mesh, dual messaging, sagas, GitOps/Flux, APIM.
5. **Enforce the boundary discipline** (import-linter contracts + table-prefix ownership) from day one — that's what keeps the off-ramp free.

If we go this way, the next step is to rewrite `CLAUDE.md` and `docs/architecture.md` to this altitude (or fork them as v2) and reshape Phase 0 accordingly. Say the word and I'll do that.
