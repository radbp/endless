"""Endless — a single-tenant jewelry ecommerce platform.

A modular monolith: one FastAPI deployable plus one Arq worker, internally
decomposed into bounded-context modules under `app/modules/`. See
`docs/architecture.md` for the design and `docs/right-sizing.md` for why this is
not a set of microservices.
"""
