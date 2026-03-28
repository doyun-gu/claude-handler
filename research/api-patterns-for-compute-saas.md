# API Design Patterns for Compute-Heavy SaaS

Research compiled from Stripe, Anthropic, OpenAI, Supabase, Vercel, GitHub, Twilio, SimScale, and others.
Targeted at DPSpice: a power system simulation SaaS (1-60s compute per request).

---

## 1. Async Job Pattern

**Who does it well:** Stripe (payments), Vercel (builds), SimScale (simulations), OpenAI (batch API)

### The Pattern: Submit -> Poll/Stream -> Retrieve

Every compute-heavy SaaS follows this three-phase pattern:

```
Client                          Server
  |                               |
  |-- POST /simulations --------->|  (submit job)
  |<-- 202 Accepted + job_id ----|  (immediate response)
  |                               |  [worker picks up job]
  |-- GET /simulations/{id} ----->|  (poll status)
  |<-- 200 { status: "running" } -|
  |                               |
  |-- GET /simulations/{id} ----->|  (poll again)
  |<-- 200 { status: "completed", result_url: "..." } --|
  |                               |
  |-- GET /results/{id} -------->|  (fetch results)
  |<-- 200 { data: {...} } ------|
```

### Submit Response (HTTP 202)

```json
POST /api/v1/simulations
Content-Type: application/json

{
  "model_id": "grid-ieee-118",
  "analysis_type": "power_flow",
  "parameters": {
    "max_iterations": 100,
    "tolerance": 1e-6
  }
}
```

```json
HTTP/1.1 202 Accepted
Location: /api/v1/simulations/sim_abc123
Retry-After: 2

{
  "id": "sim_abc123",
  "status": "queued",
  "created_at": "2026-03-28T10:00:00Z",
  "estimated_duration_seconds": 15,
  "links": {
    "self": "/api/v1/simulations/sim_abc123",
    "cancel": "/api/v1/simulations/sim_abc123/cancel",
    "results": "/api/v1/simulations/sim_abc123/results"
  }
}
```

### Status Object Schema

```json
{
  "id": "sim_abc123",
  "status": "running",          // queued | running | completed | failed | cancelled
  "progress": 0.65,             // 0.0 to 1.0
  "current_step": "Newton-Raphson iteration 4/8",
  "created_at": "2026-03-28T10:00:00Z",
  "started_at": "2026-03-28T10:00:02Z",
  "completed_at": null,
  "estimated_remaining_seconds": 5,
  "links": {
    "self": "/api/v1/simulations/sim_abc123",
    "results": "/api/v1/simulations/sim_abc123/results",
    "cancel": "/api/v1/simulations/sim_abc123/cancel"
  }
}
```

### Completion: HTTP 303 Redirect (Optional)

Some APIs (per RFC 7231) return 303 See Other when polling a completed job, redirecting to the result resource:

```
HTTP/1.1 303 See Other
Location: /api/v1/simulations/sim_abc123/results
```

### SimScale's Actual Workflow

SimScale's SDK reveals the exact pipeline for engineering simulation SaaS:

1. `import_geometry()` -- upload model
2. `create_mesh_operation()` + `start_mesh_operation()` -- mesh the geometry
3. `create_simulation()` + `check_simulation_setup()` -- configure and validate
4. `create_simulation_run()` + `start_simulation_run()` -- execute
5. `get_simulation_run()` -- poll for status (loop until done)
6. `get_simulation_run_results()` -- fetch results
7. `create_export()` + `get_export()` -- export for download

Each step is a separate API call. Status polling is done via `get_simulation_run()` in a loop.

### Webhook Alternative

For B2B/enterprise clients, offer webhook callbacks alongside polling:

```json
POST /api/v1/simulations
{
  "model_id": "grid-ieee-118",
  "analysis_type": "power_flow",
  "webhook_url": "https://customer.com/hooks/dpspice",
  "webhook_secret": "whsec_..."
}
```

Webhook payload on completion:

```json
POST https://customer.com/hooks/dpspice
X-DPSpice-Signature: sha256=abc123...

{
  "event": "simulation.completed",
  "simulation_id": "sim_abc123",
  "status": "completed",
  "completed_at": "2026-03-28T10:00:17Z",
  "result_url": "https://api.dpspice.com/v1/simulations/sim_abc123/results"
}
```

**Retry policy:** Exponential backoff (1s, 2s, 4s, 8s, ...) with 3-day retry window (Stripe's pattern).

### DPSpice Recommendation

For 1-60s simulations:
- **< 5s:** Synchronous response is acceptable. Return results directly.
- **5-15s:** HTTP long-poll or SSE stream (see section 5).
- **15-60s:** Full async job pattern with 202 + polling.
- **> 60s:** Async + webhook notification.

---

## 2. Multi-Tenant API Design

**Who does it well:** Supabase (RLS), Vercel (team isolation), PlanetScale (database branching)

### The Winner: Shared Database + Tenant Column + Row-Level Security

This is the pattern used by nearly every modern SaaS at launch. Separate databases per tenant is for enterprise-tier only.

### Schema Design

```sql
-- Every table gets a tenant_id column
CREATE TABLE simulations (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  model_id      UUID NOT NULL REFERENCES models(id),
  analysis_type TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'queued',
  parameters    JSONB NOT NULL DEFAULT '{}',
  results       JSONB,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at    TIMESTAMPTZ,
  completed_at  TIMESTAMPTZ,

  -- Index for tenant queries (ALWAYS index tenant_id)
  INDEX idx_simulations_tenant (tenant_id),
  INDEX idx_simulations_tenant_status (tenant_id, status)
);

CREATE TABLE models (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id),
  name        TEXT NOT NULL,
  data        JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

  INDEX idx_models_tenant (tenant_id)
);
```

### Supabase RLS Pattern (PostgreSQL)

```sql
-- Enable RLS on every table
ALTER TABLE simulations ENABLE ROW LEVEL SECURITY;

-- Read: users see only their tenant's data
CREATE POLICY "tenant_isolation_select" ON simulations
  FOR SELECT
  TO authenticated
  USING (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);

-- Write: users can only create in their tenant
CREATE POLICY "tenant_isolation_insert" ON simulations
  FOR INSERT
  TO authenticated
  WITH CHECK (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);

-- Update: users can only modify their tenant's data
CREATE POLICY "tenant_isolation_update" ON simulations
  FOR UPDATE
  TO authenticated
  USING (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid)
  WITH CHECK (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);

-- Delete: users can only delete their tenant's data
CREATE POLICY "tenant_isolation_delete" ON simulations
  FOR DELETE
  TO authenticated
  USING (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);
```

### API-Level Enforcement (Belt + Suspenders)

RLS is the database-level safety net. The API layer ALSO enforces tenant isolation:

```python
# FastAPI middleware -- inject tenant_id from JWT into every request
@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    payload = verify_jwt(token)
    request.state.tenant_id = payload["tenant_id"]
    return await call_next(request)

# Every query includes tenant_id
@app.get("/api/v1/simulations")
async def list_simulations(request: Request, db: AsyncSession = Depends(get_db)):
    tenant_id = request.state.tenant_id
    result = await db.execute(
        select(Simulation).where(Simulation.tenant_id == tenant_id)
    )
    return result.scalars().all()
```

### Three-Tier Multi-Tenancy Strategy

| Approach | When to use | Cost |
|---|---|---|
| Shared DB + tenant column + RLS | Default for all tenants | $ |
| Shared DB + separate schemas | Mid-tier (custom fields needed) | $$ |
| Separate database per tenant | Enterprise (compliance, data residency) | $$$$ |

**Recommendation for DPSpice:** Start with shared DB + tenant column + RLS. Offer dedicated database as an enterprise add-on later. This is what Supabase, Neon, and Clerk all recommend.

---

## 3. Rate Limiting and Queuing

**Who does it well:** Anthropic (token bucket + rich headers), OpenAI (tiered limits), Stripe (per-key limits)

### Algorithm: Token Bucket

Anthropic and most production APIs use the **token bucket algorithm**:
- Bucket fills continuously at a fixed rate (e.g., 10 requests/second)
- Bucket has a max capacity (e.g., 100 requests)
- Each request consumes one token
- If bucket is empty, request is rejected with 429
- Allows bursts up to capacity, then enforces average rate

This is better than fixed-window counters because it prevents the "boundary burst" problem (double the rate at window edges).

### Implementation with Redis

```python
# Lua script for atomic token bucket in Redis
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])        -- max tokens (e.g., 100)
local refill_rate = tonumber(ARGV[2])     -- tokens per second (e.g., 10)
local now = tonumber(ARGV[3])             -- current timestamp
local requested = tonumber(ARGV[4])       -- tokens to consume (usually 1)

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1]) or capacity
local last_refill = tonumber(bucket[2]) or now

-- Refill tokens based on elapsed time
local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, math.ceil(capacity / refill_rate) * 2)
    return {1, tokens}  -- allowed, remaining
else
    return {0, tokens}  -- denied, remaining
end
"""
```

### Rate Limit Response Headers

**Anthropic's headers** (the gold standard -- most detailed):

```
anthropic-ratelimit-requests-limit: 4000
anthropic-ratelimit-requests-remaining: 3999
anthropic-ratelimit-requests-reset: 2026-03-28T10:00:30Z
anthropic-ratelimit-input-tokens-limit: 2000000
anthropic-ratelimit-input-tokens-remaining: 1998000
anthropic-ratelimit-input-tokens-reset: 2026-03-28T10:00:30Z
anthropic-ratelimit-output-tokens-limit: 400000
anthropic-ratelimit-output-tokens-remaining: 399000
anthropic-ratelimit-output-tokens-reset: 2026-03-28T10:00:30Z
```

**OpenAI's headers:**

```
x-ratelimit-limit-requests: 10000
x-ratelimit-remaining-requests: 9999
x-ratelimit-reset-requests: 6ms
x-ratelimit-limit-tokens: 200000
x-ratelimit-remaining-tokens: 199000
x-ratelimit-reset-tokens: 50ms
```

### 429 Response Format

```json
HTTP/1.1 429 Too Many Requests
Retry-After: 5

{
  "error": {
    "type": "rate_limit_error",
    "message": "You have exceeded your simulation quota. Rate limit: 20 simulations per minute. Please retry after 5 seconds.",
    "retry_after_seconds": 5
  }
}
```

### DPSpice Rate Limit Headers

```python
# FastAPI response headers for rate limiting
from fastapi import Response

@app.post("/api/v1/simulations")
async def create_simulation(request: Request, response: Response):
    tenant_id = request.state.tenant_id

    # Check rate limit
    allowed, remaining = check_rate_limit(tenant_id, "simulations")

    # Always set headers (even on success)
    response.headers["X-RateLimit-Limit"] = "20"
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = "2026-03-28T10:01:00Z"

    if not allowed:
        return JSONResponse(
            status_code=429,
            headers={
                "Retry-After": "5",
                "X-RateLimit-Limit": "20",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "2026-03-28T10:01:00Z",
            },
            content={
                "error": {
                    "type": "rate_limit_error",
                    "code": "DP-API002-W",
                    "message": "Rate limit exceeded: 20 simulations per minute.",
                    "retry_after_seconds": 5
                }
            }
        )

    # Process simulation...
```

### Per-Tier Rate Limits (following Anthropic/OpenAI pattern)

| Tier | Simulations/min | Concurrent jobs | Max grid size (buses) | Monthly spend |
|---|---|---|---|---|
| Free | 5 | 1 | 30 | $0 |
| Starter | 20 | 3 | 500 | $29/mo |
| Pro | 60 | 10 | 5,000 | $99/mo |
| Enterprise | Custom | Custom | Unlimited | Custom |

---

## 4. API Versioning

**Who does it well:** Stripe (date-based), GitHub (date-based header), Twilio (URL path)

### Stripe's Date-Based Versioning (Recommended)

Stripe's approach is the industry gold standard. Here is how it works:

1. Versions are **dates**: `2026-03-28`, `2026-06-15`, etc.
2. New accounts are **auto-pinned** to the latest version on first API call
3. Clients can override per-request via `Stripe-Version` header
4. Stripe maintains **backward compatibility for all pinned versions**

### The Version Change Module Pattern (Stripe's Internal Architecture)

```python
# Each breaking change is a self-contained module
class VersionChange_2026_06_15:
    """Rename 'bus_data' to 'buses' in simulation results."""

    description = "Renamed bus_data field to buses in simulation results"
    affected_resources = ["Simulation"]

    def transform_response(self, response: dict) -> dict:
        """Transform from current format to this version's format."""
        if "buses" in response:
            response["bus_data"] = response.pop("buses")
        return response

# Response pipeline: start with current version, walk backward
def apply_version_transforms(response, target_version):
    """Walk backward through version changes to match client's pinned version."""
    changes = get_changes_after(target_version)  # chronologically sorted
    for change in reversed(changes):
        response = change.transform_response(response)
    return response
```

### How the Version Header Works

```
# Client pinned to 2026-03-28 (automatic on first request)
GET /v1/simulations/sim_abc123
# -> Returns response in 2026-03-28 format

# Client explicitly requests newer version
GET /v1/simulations/sim_abc123
DPSpice-Version: 2026-06-15
# -> Returns response in 2026-06-15 format

# No header = use account's pinned version
```

### GitHub's Approach (Similar but Header-Only)

```
GET /repos/owner/repo/pulls
X-GitHub-Api-Version: 2022-11-28
```

- Breaking changes = new date version
- Non-breaking changes = available across all versions automatically
- Previous version supported for at least 24 months
- Default version if no header sent: `2022-11-28`

### Twilio's Approach (URL Path)

```
https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json
```

Major version in URL path. Simpler, but harder to sunset.

### DPSpice Recommendation

Use **Stripe's approach** (date-based + header override):

```
# Base URL stays stable
https://api.dpspice.com/v1/simulations

# Version control via header
DPSpice-Version: 2026-03-28

# Account gets auto-pinned on first request
# Dashboard shows current pinned version with upgrade button
```

Why this over URL-based (`/v2/`):
- No need for clients to change URLs when upgrading
- Incremental changes, not monolithic version bumps
- Can maintain dozens of versions without dozens of URL prefixes
- Automatic changelog generation from version modules

---

## 5. Real-Time Results Streaming

**Who does it well:** OpenAI (SSE for token streaming), Anthropic (SSE), Vercel (SSE for build logs)

### SSE (Server-Sent Events) -- The Right Choice for Simulation Streaming

SSE is the dominant pattern for streaming computation results in 2025-2026. It won over WebSockets for these use cases because:

- **Unidirectional** (server to client) -- which is exactly what simulation progress needs
- **HTTP-based** -- works through proxies, CDNs, load balancers without special config
- **Auto-reconnect** built into the browser EventSource API
- **Simpler** than WebSocket -- no connection upgrade, no framing protocol

### FastAPI SSE Implementation for DPSpice

```python
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent
from collections.abc import AsyncIterable

app = FastAPI()

@app.get("/api/v1/simulations/{sim_id}/stream", response_class=EventSourceResponse)
async def stream_simulation(sim_id: str) -> AsyncIterable[ServerSentEvent]:
    """Stream simulation progress and partial results via SSE."""

    # Initial event: simulation started
    yield ServerSentEvent(
        data={"status": "running", "progress": 0.0, "message": "Initializing solver..."},
        event="progress",
        id="0"
    )

    # Poll internal job queue for updates
    async for update in simulation_engine.subscribe(sim_id):
        if update.type == "iteration":
            yield ServerSentEvent(
                data={
                    "status": "running",
                    "progress": update.progress,
                    "iteration": update.iteration,
                    "max_mismatch": update.mismatch,
                    "message": f"Newton-Raphson iteration {update.iteration}/{update.max_iter}"
                },
                event="progress",
                id=str(update.iteration)
            )

        elif update.type == "partial_result":
            # Stream partial bus voltages as they converge
            yield ServerSentEvent(
                data={
                    "converged_buses": update.bus_voltages,
                    "iteration": update.iteration
                },
                event="partial_result",
                id=str(update.sequence)
            )

        elif update.type == "completed":
            yield ServerSentEvent(
                data={
                    "status": "completed",
                    "progress": 1.0,
                    "result_url": f"/api/v1/simulations/{sim_id}/results",
                    "summary": {
                        "total_iterations": update.iterations,
                        "converged": True,
                        "max_mismatch": update.final_mismatch,
                        "solve_time_ms": update.duration_ms
                    }
                },
                event="completed",
                id="final"
            )
            return  # Close stream

        elif update.type == "failed":
            yield ServerSentEvent(
                data={
                    "status": "failed",
                    "error": {
                        "code": update.error_code,
                        "message": update.error_message
                    }
                },
                event="error",
                id="error"
            )
            return
```

### Client-Side SSE Consumption

```javascript
const eventSource = new EventSource('/api/v1/simulations/sim_abc123/stream');

eventSource.addEventListener('progress', (e) => {
  const data = JSON.parse(e.data);
  updateProgressBar(data.progress);
  updateStatusMessage(data.message);
});

eventSource.addEventListener('partial_result', (e) => {
  const data = JSON.parse(e.data);
  updateBusVoltageDisplay(data.converged_buses);
});

eventSource.addEventListener('completed', (e) => {
  const data = JSON.parse(e.data);
  showCompletionSummary(data.summary);
  eventSource.close();
});

eventSource.addEventListener('error', (e) => {
  // EventSource auto-reconnects on network errors
  // Custom error events from server need manual handling
  if (e.data) {
    const data = JSON.parse(e.data);
    showError(data.error.message);
    eventSource.close();
  }
});
```

### SSE Wire Format (What Goes Over the Wire)

```
event: progress
id: 0
data: {"status":"running","progress":0.0,"message":"Initializing solver..."}

event: progress
id: 3
data: {"status":"running","progress":0.45,"iteration":3,"max_mismatch":0.0023}

event: partial_result
id: 1
data: {"converged_buses":[{"id":1,"v_mag":1.06,"v_ang":0.0}],"iteration":3}

event: completed
id: final
data: {"status":"completed","progress":1.0,"result_url":"/api/v1/simulations/sim_abc123/results"}

```

### When to Use What

| Duration | Pattern | Why |
|---|---|---|
| < 5s | Synchronous response | Simple, no overhead |
| 5-30s | SSE stream | User sees progress, partial results |
| 30s-5min | SSE stream + async job | SSE for live users, polling for API clients |
| > 5min | Async job + webhook | Too long for HTTP connection |

### FastAPI Built-In SSE Features

FastAPI's SSE automatically handles:
- Keep-alive pings every 15 seconds (prevents proxy timeouts)
- `Cache-Control: no-cache` header
- `X-Accel-Buffering: no` header (prevents Nginx buffering)
- Resume with `Last-Event-ID` header

---

## 6. Error Handling Patterns

**Who does it well:** Stripe (most comprehensive), Twilio (simple + doc links)

### Stripe's Error Response Structure

```json
HTTP/1.1 402 Payment Required

{
  "error": {
    "type": "invalid_request_error",
    "code": "parameter_missing",
    "message": "The 'analysis_type' parameter is required.",
    "param": "analysis_type",
    "doc_url": "https://docs.dpspice.com/errors/parameter_missing"
  }
}
```

**Stripe's error fields:**

| Field | Type | Description |
|---|---|---|
| `type` | enum | Category: `api_error`, `invalid_request_error`, `authentication_error`, `rate_limit_error`, `simulation_error` |
| `code` | string | Machine-readable: `parameter_missing`, `model_not_found`, `solver_diverged` |
| `message` | string | Human-readable explanation |
| `param` | string | Which parameter caused the error (if applicable) |
| `doc_url` | string | Link to documentation about this error |

**Stripe's HTTP status mapping:**

| Code | Meaning | Error Type |
|---|---|---|
| 400 | Bad Request | `invalid_request_error` |
| 401 | Unauthorized | `authentication_error` |
| 402 | Request Failed | Simulation-specific failure |
| 403 | Forbidden | Permission denied |
| 404 | Not Found | Resource missing |
| 409 | Conflict | `idempotency_error` |
| 429 | Too Many Requests | `rate_limit_error` |
| 500 | Server Error | `api_error` |

### Twilio's Error Response Structure (Simpler)

```json
HTTP/1.1 400 Bad Request

{
  "status": 400,
  "code": 21201,
  "message": "No model_id is specified",
  "more_info": "https://docs.dpspice.com/errors/21201"
}
```

Twilio's key innovation: the `more_info` URL links to a page with full troubleshooting steps.

### DPSpice Error Design (Hybrid: Stripe Structure + DPSpice Error Codes)

```json
HTTP/1.1 422 Unprocessable Entity

{
  "error": {
    "type": "simulation_error",
    "code": "DP-ENG001-E",
    "message": "Power flow solver did not converge within 100 iterations. Maximum bus mismatch: 0.15 p.u. at bus 47.",
    "details": {
      "solver": "newton_raphson",
      "iterations_completed": 100,
      "max_mismatch": 0.15,
      "divergent_bus": 47
    },
    "suggestions": [
      "Try increasing max_iterations to 200",
      "Check reactive power limits at bus 47",
      "Use a flat start voltage profile"
    ],
    "doc_url": "https://docs.dpspice.com/errors/DP-ENG001-E",
    "request_id": "req_xyz789"
  }
}
```

### Error Taxonomy for DPSpice

```
Type                       | HTTP Code | When
---------------------------|-----------|------
invalid_request_error      | 400       | Bad parameters, missing fields
authentication_error       | 401       | Invalid/expired API key
authorization_error        | 403       | No access to this resource
not_found_error            | 404       | Model/simulation doesn't exist
idempotency_error          | 409       | Conflicting idempotency key
rate_limit_error           | 429       | Too many requests
simulation_error           | 422       | Solver failed (divergence, bad model)
api_error                  | 500       | Internal server error
```

### Request ID in Every Response

Every response (success or error) includes a unique request ID for debugging:

```
HTTP/1.1 200 OK
X-Request-Id: req_xyz789
```

---

## 7. Idempotency

**Who does it well:** Stripe (the original, best documented)

### Stripe's Pattern

- Client sends `Idempotency-Key` header with a UUID
- Server stores the key + response for 24 hours
- Retries with the same key return the cached response
- Retries with same key but different parameters = 409 Conflict

### Database Schema (from Brandur/Stripe's Rocket Rides)

```sql
CREATE TABLE idempotency_keys (
    id              BIGSERIAL   PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key TEXT        NOT NULL CHECK (char_length(idempotency_key) <= 100),
    last_run_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at       TIMESTAMPTZ DEFAULT now(),

    -- Original request details (for parameter validation)
    request_method  TEXT        NOT NULL CHECK (char_length(request_method) <= 10),
    request_params  JSONB       NOT NULL,
    request_path    TEXT        NOT NULL CHECK (char_length(request_path) <= 100),

    -- Cached response
    response_code   INT         NULL,
    response_body   JSONB       NULL,

    -- State machine
    recovery_point  TEXT        NOT NULL CHECK (char_length(recovery_point) <= 50),

    user_id         BIGINT      NOT NULL
);

-- One key per user (different users can use the same key string)
CREATE UNIQUE INDEX idx_idempotency_keys_user_key
    ON idempotency_keys (user_id, idempotency_key);
```

### Recovery Point State Machine

The request progresses through phases, each wrapped in an ACID transaction:

```
started --> simulation_queued --> simulation_completed --> finished
    |                                                        |
    +-- (crash at any point) --> resume from last phase -----+
```

Concrete phases for DPSpice:

| Recovery Point | What happened | What to do on retry |
|---|---|---|
| `started` | Key created, nothing else | Run full operation |
| `simulation_queued` | Job submitted to worker queue | Skip submission, poll for results |
| `simulation_completed` | Results stored | Skip to response generation |
| `finished` | Response cached | Return cached response |

### Implementation

```python
@app.post("/api/v1/simulations")
async def create_simulation(
    request: Request,
    body: SimulationRequest,
    db: AsyncSession = Depends(get_db),
):
    idempotency_key = request.headers.get("Idempotency-Key")
    tenant_id = request.state.tenant_id

    if idempotency_key:
        # Check for existing key
        existing = await db.execute(
            select(IdempotencyKey)
            .where(
                IdempotencyKey.user_id == tenant_id,
                IdempotencyKey.idempotency_key == idempotency_key,
            )
            .with_for_update()  # Lock the row
        )
        key_record = existing.scalar_one_or_none()

        if key_record:
            # Validate parameters match
            if key_record.request_params != body.dict():
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": {
                            "type": "idempotency_error",
                            "message": "Idempotency key already used with different parameters."
                        }
                    }
                )

            # If finished, return cached response
            if key_record.recovery_point == "finished":
                return JSONResponse(
                    status_code=key_record.response_code,
                    content=key_record.response_body,
                )

            # If not finished, resume from last recovery point
            return await resume_simulation(key_record, db)

        # New key -- create it
        key_record = IdempotencyKey(
            idempotency_key=idempotency_key,
            user_id=tenant_id,
            request_method="POST",
            request_path="/api/v1/simulations",
            request_params=body.dict(),
            recovery_point="started",
        )
        db.add(key_record)
        await db.commit()

    # Normal simulation creation flow...
    simulation = await create_and_queue_simulation(body, tenant_id, db)

    response_body = {
        "id": str(simulation.id),
        "status": "queued",
        "created_at": simulation.created_at.isoformat(),
    }

    # Update idempotency key to finished
    if idempotency_key and key_record:
        key_record.recovery_point = "finished"
        key_record.response_code = 202
        key_record.response_body = response_body
        await db.commit()

    return JSONResponse(status_code=202, content=response_body)
```

### Client Usage

```bash
# First attempt
curl -X POST https://api.dpspice.com/v1/simulations \
  -H "Authorization: Bearer sk_live_..." \
  -H "Idempotency-Key: idem_550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{"model_id": "grid-ieee-118", "analysis_type": "power_flow"}'

# Network error, retry with SAME key -- safe
curl -X POST https://api.dpspice.com/v1/simulations \
  -H "Authorization: Bearer sk_live_..." \
  -H "Idempotency-Key: idem_550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{"model_id": "grid-ieee-118", "analysis_type": "power_flow"}'
# Returns same 202 response, does NOT create duplicate simulation
```

### Key Design Decisions

- Keys expire after **24 hours** (Stripe's policy)
- Keys are scoped to **(user_id, key)** -- different users can use the same key string
- Only required for **POST** (mutating) requests, not GET
- Retries with different params return **409 Conflict**
- `locked_at` timestamp prevents concurrent processing of the same key (use `SELECT ... FOR UPDATE`)
- SERIALIZABLE isolation level for the critical sections

---

## Summary: What to Build First for DPSpice API

### Phase 1 (MVP)
1. Async job pattern (POST 202 + polling)
2. Tenant isolation (tenant_id column + API middleware)
3. Basic rate limiting (per-tenant, fixed limits)
4. Stripe-style error responses
5. Request IDs in every response

### Phase 2 (Growth)
6. SSE streaming for simulation progress
7. Idempotency keys for POST endpoints
8. Date-based API versioning (DPSpice-Version header)
9. Tiered rate limits (Free/Starter/Pro/Enterprise)
10. Webhook notifications for completed simulations

### Phase 3 (Enterprise)
11. RLS policies in PostgreSQL
12. Per-tenant database option
13. Webhook delivery with retry + exponential backoff
14. Rate limit dashboard in admin UI
15. API version upgrade assistant

---

## Sources

### Async Job Pattern
- [Asynchronous Operations in REST APIs -- Zuplo](https://zuplo.com/learning-center/asynchronous-operations-in-rest-apis-managing-long-running-tasks)
- [SimScale Python SDK Documentation](https://simscalegmbh.github.io/simscale-python-sdk/)
- [SimScale API Integration](https://www.simscale.com/product/api/)
- [Stripe Webhooks Documentation](https://docs.stripe.com/webhooks)
- [Vercel Workflow](https://vercel.com/docs/workflow)
- [Vercel Long-Running Background Functions -- Inngest](https://www.inngest.com/blog/vercel-long-running-background-functions)

### Multi-Tenant Design
- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Multi-Tenant Database Architecture Patterns -- Bytebase](https://www.bytebase.com/blog/multi-tenant-database-architecture-patterns-explained/)
- [Multi-Tenant RLS on Supabase -- AntStack](https://www.antstack.com/blog/multi-tenant-applications-with-rls-on-supabase-postgress/)
- [RLS Deep Dive: LockIn Architecture -- DEV Community](https://dev.to/blackie360/-enforcing-row-level-security-in-supabase-a-deep-dive-into-lockins-multi-tenant-architecture-4hd2)

### Rate Limiting
- [Anthropic Rate Limits Documentation](https://platform.claude.com/docs/en/api/rate-limits)
- [OpenAI Rate Limits](https://platform.openai.com/docs/guides/rate-limits)
- [OpenAI Cookbook: How to Handle Rate Limits](https://developers.openai.com/cookbook/examples/how_to_handle_rate_limits)
- [Build 5 Rate Limiters with Redis -- Redis.io](https://redis.io/tutorials/howtos/ratelimiting/)
- [Token Bucket to Sliding Window -- API7.ai](https://api7.ai/blog/rate-limiting-guide-algorithms-best-practices)

### API Versioning
- [Stripe API Versioning Blog Post](https://stripe.com/blog/api-versioning)
- [Stripe Versioning Documentation](https://docs.stripe.com/api/versioning)
- [GitHub API Versioning Blog Post](https://github.blog/developer-skills/github/to-infinity-and-beyond-enabling-the-future-of-githubs-rest-api-with-api-versioning/)
- [GitHub API Versions Documentation](https://docs.github.com/en/rest/about-the-rest-api/api-versions)
- [Stripe's API Never Breaks -- Medium](https://medium.com/@asyukesh/why-stripes-api-never-breaks-a-deep-dive-into-date-based-versioning-a9925dd8af42)

### Real-Time Streaming
- [FastAPI Server-Sent Events Tutorial](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- [SSE's Comeback in 2025 -- portalZINE](https://portalzine.de/sses-glorious-comeback-why-2025-is-the-year-of-server-sent-events/)
- [Streaming AI Responses with SSE -- Medium](https://akanuragkumar.medium.com/streaming-ai-agents-responses-with-server-sent-events-sse-a-technical-case-study-f3ac855d0755)

### Error Handling
- [Stripe API Errors Documentation](https://docs.stripe.com/api/errors)
- [Twilio API Responses](https://www.twilio.com/docs/usage/twilios-response)
- [Twilio Error Dictionary](https://www.twilio.com/docs/api/errors)

### Idempotency
- [Stripe Idempotency Blog Post](https://stripe.com/blog/idempotency)
- [Implementing Stripe-like Idempotency Keys in Postgres -- Brandur](https://brandur.org/idempotency-keys)
- [How Stripe Prevents Double Payment -- System Design Newsletter](https://newsletter.systemdesign.one/p/idempotent-api)
- [Stripe Idempotent Requests API Reference](https://docs.stripe.com/api/idempotent_requests)
