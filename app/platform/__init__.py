"""Shared infrastructure used by every module.

Nothing here knows about jewelry. Modules depend on `platform`; `platform` never
depends on a module.

Landed in F0.1: `settings`, `logging`.
Landed in F0.6 Slice A: `db` (engine/session/transaction + declarative base),
`redis`, `clock` (injectable time), `events` (in-process bus).
Landed in F0.6 Slice B: `outbox` (transactional outbox + drain), real `otel`
export (Azure Monitor), plus `Database.advisory_lock` for singleton jobs.
Arriving next in F0.6 Slice B: `idempotency`, `auth`.
"""
