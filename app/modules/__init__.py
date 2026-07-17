"""Bounded contexts — the unit of decoupling.

Each module is a package with `domain.py` (pure), `service.py` (its public
interface), `repository.py` (its own prefix-namespaced tables only), and
`events.py`. A module reaches another **only** through that module's
`service.py` — never its repository, its domain, or its tables (CLAUDE.md §1.1).
That rule is what makes a later service extraction mechanical (ADR-002).

The eight MVP modules and the tickets that create them:
    catalog (F1.1) · search (F1.7) · identity (F2.2) · cart (F2.6)
    inventory (F3.1) · order (F3.5) · payment (F4.1) · notification (F4.6)
"""
