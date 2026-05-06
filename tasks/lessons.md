# Implementation lessons — Data Designer Studio

## Things to know about Data Designer's SDK

- `LLMCodeColumnConfig` uses `code_lang=`, not `output_format=`
- `ExpressionColumnConfig` uses `expr=` and `dtype=`, not `expression=`/`type=`
- Both verified by introspecting `model_fields` on the Pydantic class.
  When integrating beta SDKs, always introspect the real class first.

## The managed hosted Data Designer endpoint is preview-only

`https://ai.api.nvidia.com/v1/nemo/dd` cannot run create jobs. We bypass
it entirely and use the library directly against
`https://integrate.api.nvidia.com/v1`. Library handles both preview and
create paths.

## Dual-mode = one DataDesigner instance with both providers

`DataDesigner(model_providers=[...])` accepts a list. Both providers
register together; the schema's `ModelConfig.provider` field decides which
one routes each LLM call. One instance, one config code path. Schema
configs port 1:1 between modes — exactly the demo story.

## Rate limit is per LLM call, not per job

A 100-record job with 4 LLM columns = 400 calls. NVIDIA's 40 RPM means
that job takes 10 minutes minimum even if inference is instant. We show
the LLM call estimate to the user before submission so the pacing is
expected, not a surprise.

## What we cut from v0 and why

**Pre-emptive token bucket → deleted.** Was 60+ lines of async-aware rate
limiting that made every job wait until "credit" was available. For an
internal tool with a few jobs per hour, this was solving a problem that
didn't exist. NVIDIA's 429 response is the rate limit; if we hit it, the
job row records the error and the user sees it. Simpler and more honest.

**SQLAlchemy ORM → stdlib `sqlite3`.** One table, fixed schema. Async
ORM was overkill; `with _lock: _conn.execute(...)` is fast enough and
half the code. Dropped two deps (sqlalchemy, aiosqlite).

**structlog → stdlib `logging` with a JSON formatter.** Same effective
output. One fewer dep. The `request_id` contextvar pattern works with
either — it's just `ContextVar` + factory.

**Five Column subclasses → one Column with conditional validation.** The
class hierarchy gave us nothing the frontend couldn't do with a `kind`
field. The single `Column` model with a `model_validator(mode="after")`
checks per-kind requirements in one readable block.

**`llm_structured` column → deferred.** Required dynamic Pydantic class
synthesis from JSON schema. Forty lines of `create_model()` for a feature
no preset uses. LLM-text columns can produce JSON via prompt for now; the
translator has a clean extension point when we need it back.

**Cost-saved counter → deferred.** Cute exec-audience framing, but it
required a per-model price dictionary (with values that drift) and added
fields to every API response and UI panel. v2 if it earns its place.

## What we added for debuggability

**Request IDs on every response.** A `ContextVar` in `logging_config.py`
plus middleware in `main.py` that sets/reads `X-Request-ID`. Every log
line for a request includes the id; the response header carries it back
to the UI; toasts surface it. User pastes id, we grep, done.

**`/api/health/detailed`.** Five concrete checks: NVIDIA key format,
hosted reachable, local reachable (with the model list), artifact dir
writable, DB readable. Surfaced as a "Preflight" tab in the UI. If
everything is green, the app works. If anything is red, that one row
tells the user exactly what to fix in their `.env`.

**Server-side validation at submit time.** Even though the frontend
calls `/api/schema/validate` continuously, the generate endpoints
re-validate before kicking off Data Designer. A bad schema returns 400
with a list of errors, not a 500 from deep inside DD's prompt rendering.
Errors include "column X references {{ Y }} which isn't defined" — the
exact text the user needs to fix it.

## Logging conventions

All logs go to stdout as JSON when not on a TTY (so `docker logs ...`
gives you parseable lines). Standard fields: `ts`, `level`, `logger`,
`msg`, `request_id`. Anything passed via `extra={...}` becomes a top-level
field. No nested objects, no log levels per module.

## Frontend choices

Single-file React, ESM imports from esm.sh, no bundler. Mounted by FastAPI
at `/app/`. One server to run, one URL for users. Tradeoff: no JSX, so
the code uses `h(...)` helpers. Acceptable cost for "no Vite, no Webpack,
no npm install."

## Deploy script

`deploy.sh` is intentionally not idempotent in the deepest sense — it
doesn't try to detect "was anything changed" or "should I rebuild." It
just always rebuilds. For an internal tool with a 3-minute build, that's
fine and avoids the rabbit hole of caching the wrong thing. The named
docker volume preserves data across rebuilds, which is the actual
"don't lose anything" promise.
