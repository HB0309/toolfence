Source: targets/galaxium, 2026-10-08

## 1. What the app does

- Galaxium Travels is a demo interplanetary flight-booking website [`README.md:1`](../../targets/galaxium/README.md:1)
- Travellers register, search flights (Earth ↔ Mars/Moon/Venus/Jupiter/Europa/Pluto), and book in economy, business, or Galaxium class [`README.md:7-9`](../../targets/galaxium/README.md:7-9)
- A Java microservice handles a time-limited seat-hold workflow: quote → hold → confirm or release; holds auto-expire after 15 minutes [`README.md:10`](../../targets/galaxium/README.md:10)
- The Python FastAPI backend is the source of truth for users, flights, and bookings; the Java service calls it back at `/internal/bookings/from-hold` to commit a booking [`README.md:35-36`](../../targets/galaxium/README.md:35-36)
- Every REST route is also exposed as an MCP tool via `fastapi_mcp`, so AI agents can interact natively — including internal routes [`server.py:336-337`](../../targets/galaxium/booking_system_backend/server.py:336)

---

## 2. How to start on Windows PowerShell

The repo's [`start.sh`](../../targets/galaxium/start.sh) and [`README.md:82`](../../targets/galaxium/README.md:82) only give bash/sh commands. Translating to PowerShell:

**Backend (port 8001):**
```powershell
cd targets\galaxium\booking_system_backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server.py
```
[`README.md:89-93`](../../targets/galaxium/README.md:89)

**Frontend (port 5173, new terminal):**
```powershell
cd targets\galaxium\booking_system_frontend
npm install
npm run dev
```
[`README.md:96-99`](../../targets/galaxium/README.md:96)

**Java hold service (port 8080, optional, new terminal):**
```powershell
cd targets\galaxium\booking_system_inventory_hold_service
mvn spring-boot:run
```
[`README.md:102-103`](../../targets/galaxium/README.md:102)

---

## 3. Backend routes

| Method | Path | What it reads / changes | User / booking identifier |
|--------|------|------------------------|--------------------------|
| `GET` | `/` | Reads nothing — health check | none |
| `GET` | `/flights` | Reads flights table (many optional filters) | none |
| `POST` | `/register` | Creates a `User` row | body: `name`, `email` |
| `GET` | `/user` | Reads a `User` row | query: `name` + `email` |
| `POST` | `/book` | Creates a `Booking`, decrements seat counter | body: `user_id`, `name`, `flight_id` |
| `GET` | `/bookings/{user_id}` | Reads all bookings for a user | path: `user_id` |
| `POST` | `/cancel/{booking_id}` | Sets booking status = `cancelled`, restores seat | path: `booking_id` |
| `POST` | `/internal/bookings/from-hold` | Creates a `Booking` (called by Java) | body dict: `travelerId`, `travelerName`, `flightId` |
| `POST` | `/quotes` | Proxies to Java `POST /api/v1/quotes` | body passed through |
| `GET` | `/quotes/{quote_id}` | Proxies to Java `GET /api/v1/quotes/{id}` | path: `quote_id` |
| `POST` | `/quotes/{quote_id}/holds` | Proxies to Java — creates a hold | path: `quote_id` |
| `GET` | `/holds/{hold_id}` | Proxies to Java — reads a hold | path: `hold_id` |
| `POST` | `/holds/{hold_id}/confirm` | Proxies to Java — confirms hold → triggers booking | path: `hold_id` |
| `POST` | `/holds/{hold_id}/release` | Proxies to Java — releases hold | path: `hold_id` |

Sources: [`server.py:64-331`](../../targets/galaxium/booking_system_backend/server.py:64)

---

## 4. MCP: how it's created, what it exposes, what's excluded

- **Creation:** [`server.py:336`](../../targets/galaxium/booking_system_backend/server.py:336) — `mcp = FastApiMCP(app)` followed by `mcp.mount_http()` on line 337. `FastApiMCP` wraps the already-constructed `FastAPI` app with no filters or exclusions passed.
- **What it exposes:** every route registered on `app` before `FastApiMCP(app)` is called — that means all 14 routes in the table above, including `/internal/bookings/from-hold`. [`README.md:174-185`](../../targets/galaxium/README.md:174) lists only six "MCP tools" by friendly name, but this is the documented subset; the `/internal/` and proxy routes are also present as tools because no `include_operations` or `exclude_operations` argument is passed.
- **Nothing is excluded:** no argument to `FastApiMCP(app)` restricts which routes become tools. [`server.py:336`](../../targets/galaxium/booking_system_backend/server.py:336)

---

## 5. Identity and ownership

- **Where the current user comes from:** there is no authentication middleware. The caller supplies `user_id` (an integer) directly in the request body (`POST /book`) or in the path (`GET /bookings/{user_id}`, `POST /cancel/{booking_id}`). [`server.py:152-185`](../../targets/galaxium/booking_system_backend/server.py:152), [`schemas.py:51-55`](../../targets/galaxium/booking_system_backend/schemas.py:51)
- **`POST /book` validates `user_id` + `name` match:** [`services/booking.py:51`](../../targets/galaxium/booking_system_backend/services/booking.py:51) queries `User.user_id == user_id AND User.name == name`. A name mismatch returns an error. This is the only ownership-like check.
- **`POST /cancel/{booking_id}` has no ownership check:** [`services/booking.py:93-123`](../../targets/galaxium/booking_system_backend/services/booking.py:93) cancels any booking by `booking_id` with no check that the booking belongs to the caller. Any caller who knows or can guess a `booking_id` can cancel it.
- **`GET /bookings/{user_id}` has no ownership check:** returns any user's bookings given their `user_id`. [`services/booking.py:126-129`](../../targets/galaxium/booking_system_backend/services/booking.py:126)

---

## 6. Data models

Source: [`models.py:14-40`](../../targets/galaxium/booking_system_backend/models.py:14)

| Table | Key fields |
|-------|-----------|
| `users` | `user_id` (PK, autoincrement), `name` (not null), `email` (unique, not null) |
| `flights` | `flight_id` (PK), `origin`, `destination`, `departure_time`, `arrival_time`, `base_price` (economy, 1×), `economy_seats_available`, `business_seats_available`, `galaxium_seats_available` |
| `bookings` | `booking_id` (PK), `user_id` (FK → users), `flight_id` (FK → flights), `status` (booked/cancelled/completed), `booking_time`, `seat_class`, `price_paid` |

- Holds and quotes have no SQLAlchemy model in the Python backend — they live entirely in the Java service's own SQLite DB. The Python side only receives a callback at `/internal/bookings/from-hold`. [`README.md:29-35`](../../targets/galaxium/README.md:29)

---

## 7. Reviews

- **No reviews feature exists anywhere in the application code.** Searching all `.py` files under `booking_system_backend/` (excluding `.venv`) for `review`, `Review`, `backlog`, or `#38` returned zero matches in application code — every hit was in third-party packages inside `.venv`.
- **Backlog item #38** is referenced in `docs/IDEA.md` but **no `DEMO_BACKLOG.md` file exists** in `targets/galaxium/`. [`booking_system_frontend/README.md:256`](../../targets/galaxium/booking_system_frontend/README.md:256) mentions `../DEMO_BACKLOG.md` but that file is not found in the repo at the pinned commit.
- **Where it would fit:**
  - New `Review` SQLAlchemy model in [`models.py`](../../targets/galaxium/booking_system_backend/models.py) with fields: `review_id`, `flight_id` (FK), `author` (or `user_id`), `body`, `created_at`
  - New `GET /flights/{flight_id}/reviews` route in [`server.py`](../../targets/galaxium/booking_system_backend/server.py) — a read-only endpoint that `fastapi_mcp` would auto-expose as a tool (no separate MCP registration needed, per [`README.md:287`](../../targets/galaxium/README.md:287): "add a REST handler and a matching MCP tool")
  - Seeded synthetic review rows in [`seed.py`](../../targets/galaxium/booking_system_backend/seed.py)

---

## 8. Existing tests

**Location:**
- [`booking_system_backend/tests/test_rest.py`](../../targets/galaxium/booking_system_backend/tests/test_rest.py) — REST endpoint tests (TestClient, covers flights, register, user, book, bookings, cancel, health)
- [`booking_system_backend/tests/test_services.py`](../../targets/galaxium/booking_system_backend/tests/test_services.py) — service-layer unit tests
- [`booking_system_backend/tests/conftest.py`](../../targets/galaxium/booking_system_backend/tests/conftest.py) — in-memory SQLite fixtures, `StaticPool`, seed disabled
- [`e2e/test_smoke.py`](../../targets/galaxium/e2e/test_smoke.py) — black-box smoke tests (health, flights, booking happy/sad path)
- [`e2e/test_holds.py`](../../targets/galaxium/e2e/test_holds.py) — end-to-end quote → hold → confirm flow

**How to run (PowerShell):**
```powershell
# Backend unit tests
cd targets\galaxium\booking_system_backend
pytest          # all tests
pytest -v       # verbose
pytest tests\test_services.py   # service layer only
pytest tests\test_rest.py       # REST only
```
[`README.md:191-196`](../../targets/galaxium/README.md:191)

```powershell
# E2e (against an already-running stack)
$env:E2E_BASE_URL="http://localhost:8001"
cd targets\galaxium\e2e
python -m pytest   # run-native.sh is bash only; invoke pytest directly on Windows
```
[`README.md:211-218`](../../targets/galaxium/README.md:211) — `run-native.sh` and `run.sh` are bash; on Windows, invoke `pytest` directly with `E2E_BASE_URL` set and the backend already running.
