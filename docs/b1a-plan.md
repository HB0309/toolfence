# B-1a Plan — Galaxium reviews patch

## Overview

B-1a adds an untrusted-content channel to Galaxium: passenger reviews stored in the database
and exposed via `GET /flights/{flight_id}/reviews`. The patch is the attack surface that later
evaluation runs will probe for prompt-injection.

**Deliverables:**
1. `targets/galaxium-patches/0002-reviews-route.patch` — unified diff applied with `git apply`
2. `tests/test_galaxium_patches.py` — applies the patch in a temp copy, runs assertions

**Req IDs:** PG-4  
**Done when:** `pytest tests/test_galaxium_patches.py::test_reviews_route` is green.

---

## What the patch touches (5 hunks)

### Hunk 1 — `booking_system_backend/models.py`

Add a `Review` SQLAlchemy model after `Booking`:

```python
class Review(Base):
    __tablename__ = 'reviews'
    review_id   = Column(Integer, primary_key=True, index=True, autoincrement=True)
    flight_id   = Column(Integer, ForeignKey('flights.flight_id'), nullable=False)
    reviewer    = Column(String, nullable=False)
    rating      = Column(Integer, nullable=False)   # 1–5
    body        = Column(String, nullable=False)
```

### Hunk 2 — `booking_system_backend/schemas.py`

Add `ReviewOut` Pydantic model (read-only, `from_attributes=True`):

```python
class ReviewOut(BaseModel):
    review_id: int
    flight_id: int
    reviewer:  str
    rating:    int
    body:      str
    model_config = ConfigDict(from_attributes=True)
```

### Hunk 3 — `booking_system_backend/seed.py`

- Import `Review` alongside the existing models import.
- After bookings are committed, insert 3 seeded review rows for `flight_id=1`
  with synthetic reviewer names, ratings, and free-text bodies
  (bodies contain mild prompt-injection bait so later evaluation has real untrusted content).

### Hunk 4 — `booking_system_backend/server.py`

- Import `ReviewOut` from schemas.
- Import `Review` from models.
- Add route:

```python
@app.get("/flights/{flight_id}/reviews", response_model=list[ReviewOut], tags=["Reviews"])
def get_flight_reviews(flight_id: int, db: Session = Depends(get_db)):
    """Return all passenger reviews for a flight."""
    return db.query(Review).filter(Review.flight_id == flight_id).all()
```

  Function name **must** be `get_flight_reviews` so fastapi-mcp generates the tool name
  `get_flight_reviews_flights__flight_id__reviews_get` (nanobot squeezes `__` → `_` →
  `mcp_galaxium_get_flight_reviews_flights_flight_id_reviews_get`).

### Hunk 5 — `booking_system_backend/tests/test_rest.py`

Add `TestReviewsEndpoint` class with two tests:
- `test_reviews_returns_seeded_rows` — direct DB insert + GET, checks list length and fields.
- `test_reviews_empty_for_unknown_flight` — GET for non-existent flight_id returns `[]`.

---

## Patch format

- Standard `git diff --no-index` unified diff, relative paths from repo root (e.g.
  `a/booking_system_backend/models.py`).
- No binary content; no renames.
- Applied via `git apply` inside `targets/galaxium/`.

---

## `tests/test_galaxium_patches.py`

One test: `test_reviews_route`.

Strategy: copy `targets/galaxium/booking_system_backend/` to a `tmp_path` directory,
apply the patch with `git apply --directory` (or patch the files directly), spin up
a `TestClient` against the patched server, assert:
1. `GET /flights/1/reviews` returns HTTP 200.
2. The JSON list is non-empty (seeded rows present).
3. Each item has `review_id`, `flight_id`, `reviewer`, `rating`, `body`.

Because `targets/galaxium/` is a real git repo, the simplest approach is:
- Run `git apply` inside `targets/galaxium/` (with `--check` first).
- Import and test against the live files.
- Reverse the patch with `git apply --reverse` in teardown (autouse fixture).

---

## Implementation order

```
Hunk 1 (models)  →  Hunk 2 (schemas)  →  Hunk 3 (seed)
                                              ↓
                                         Hunk 4 (server)  →  Hunk 5 (tests)
                                              ↓
                               assemble patch  →  write test_galaxium_patches.py
```
