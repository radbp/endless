"""Shared infrastructure used by every module.

Nothing here knows about jewelry. Modules depend on `platform`; `platform` never
depends on a module.

Landed in F0.1: `settings`, `logging`, `otel` (stub).
Arriving in F0.6: `db`, `events` (in-process bus), `outbox`, `idempotency`, `auth`.
"""
