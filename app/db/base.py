"""Single import surface for Alembic autogenerate.

Alembic compares ``Base.metadata`` against the live database. A model contributes
to that metadata only once its module is imported, so every module's models must
be imported *here* for autogenerate to see their tables. Application code never
imports this module — it exists purely so migrations are complete.
"""

from app.platform.db import Base

# Import each module's ORM models below as they land, so their tables register on
# Base.metadata and Alembic autogenerate picks them up. For example, F1.3 will add
# an import of app.modules.catalog.models here (with an F401 "unused" suppression,
# since the import exists only for its registration side effect).

__all__ = ["Base"]
