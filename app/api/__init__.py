"""HTTP routers and their request/response DTOs.

One module per bounded context (`catalog.py`, `cart.py`, `checkout.py`, ...),
each exposing an `APIRouter` that `app/main.py` includes. This layer validates
input, calls the owning module's `service.py`, and shapes the response — it
never touches a `repository.py` directly (CLAUDE.md §5.1).

First router arrives with the Catalog module in F1.1.
"""
