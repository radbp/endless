"""Shared infrastructure used by every module.

Nothing here knows about jewelry. Modules depend on `platform`; `platform` never
depends on a module.

Landed in F0.1: `settings`, `logging`, `otel` (stub).
Landed in F0.6 Slice A: `db` (engine/session/transaction + declarative base),
`redis`, `clock` (injectable time), `events` (in-process bus).
Arriving in F0.6 Slice B: `outbox`, `idempotency`, `auth`, real `otel` export.
"""
