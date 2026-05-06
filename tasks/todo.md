# Data Designer Frontend — Architecture & Implementation Plan

## Goal

Internal tool for generating demo datasets for vertical-specific demo/POC work. Freeform schema builder with vertical presets that pre-populate suggested fields and prompts. Dual-mode toggle (NVIDIA hosted vs local ZGX Nano) to support the "Compliance by Architecture" demo narrative in-UI.

## Critical findings from documentation

### The architecture question just got simpler

Data Designer has two deployment modes:
1. **Open-source library** (`pip install data-designer`) — points at ANY OpenAI-compatible endpoint (NVIDIA, OpenAI, vLLM, TGI, Ollama, etc.) via a `ModelProvider` config
2. **NeMo Microservice** — REST API wrapper around the library, requires Docker Compose deployment

The decision flowchart in the docs points us at **the library**, not the microservice. Library + multiple providers is literally the documented pattern for what we want. Local mode is not a reimplementation — it's the same library, same configs, same column types, pointed at vLLM on the Nano. This means:

- One Python backend, not two
- Same `DataDesignerConfigBuilder` code path for both modes
- "Mode toggle" = swap which `ModelProvider` we register, nothing else
- Schema configs are portable between modes (huge for the demo story: "same schema, same output, but watch where the data goes")

### Hosted service constraints (confirmed)

- **Managed hosted Data Designer at `https://ai.api.nvidia.com/v1/nemo/dd`**: preview-only, cannot run long-running jobs — this is a constraint of the managed SDG orchestrator
- **Per-job cap**: 10 records default, 100 records max per job
- **Underlying NVIDIA Build API rate limit**: 40 requests/minute per developer account (can request increase to higher tiers)
- **Credits**: 1,000 on signup, up to 5,000 on request, deducted per inference call. Each Data Designer record is multiple LLM calls (one per LLM column), so credit burn is schema-dependent
- **Trial terms prohibit production use** (internal testing/eval is fine — matches our use case)

### Rate limit surface we need to expose in UI

1. **Jobs remaining today** — we track this client-side (NVIDIA doesn't expose a "credits remaining" endpoint reliably per the forum threads)
2. **Requests per minute budget** — 40 RPM default; since each record requires N LLM calls (one per LLM column), a 100-record job with 4 LLM columns = 400 calls. We have to rate-limit *our* submission pace to stay under 40/min, or we'll get 429s
3. **Estimated credits per job** — compute from schema before submission so user sees cost before running
4. **Soft warnings at 75% budget, hard block at 100%**

### Column types available (eleven)

Sampler, LLM-Text, LLM-Code, LLM-Structured, LLM-Judge, Image, Embedding, Expression, Validation, Seed-Dataset, Custom. For v1 internal tool, we support the core five that drive 95% of demos:

- **Sampler** (UUID, Category, Subcategory, Uniform, Gaussian, Person, Datetime) — the "free" columns, no LLM calls
- **LLM-Text** — freeform text generation with Jinja prompts
- **LLM-Structured** — Pydantic schema JSON output
- **LLM-Code** — code gen (pick language from dropdown)
- **Expression** — Jinja transforms, no LLM

LLM-Judge, Image, Embedding, Validation, Seed-Dataset, Custom = v2 scope. Explicitly flag as "coming soon" in UI so scope is visible.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Browser (React + Tailwind + shadcn/ui)                        │
│                                                                 │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │ Vertical      │  │ Schema       │  │ Mode toggle      │    │
│  │ preset picker │→ │ builder      │  │ [Hosted|Local]   │    │
│  │               │  │ (columns)    │  │ + model dropdown │    │
│  └───────────────┘  └──────────────┘  └──────────────────┘    │
│                            ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Budget panel:  jobs today  •  RPM  •  credit estimate   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Generate → preview (fast) or create (full run)          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Results: table view, record drill-down, export CSV/JSON │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────────┬───────────────────────────────────┘
                             │ HTTP/SSE
                             ↓
┌────────────────────────────────────────────────────────────────┐
│  FastAPI backend (Python 3.11)                                  │
│                                                                 │
│  POST /api/schema/presets/{vertical}  → preset JSON             │
│  POST /api/schema/validate            → dry-run config check    │
│  POST /api/generate/preview           → 10 records, streams SSE │
│  POST /api/generate/create            → N records, job tracking │
│  GET  /api/jobs/{id}                  → status/progress         │
│  GET  /api/jobs/{id}/download         → CSV/JSON/Parquet        │
│  GET  /api/budget                     → remaining jobs/RPM/cred │
│  GET  /api/models                     → models available per mode│
│  GET  /api/health                     → both providers' status  │
└────────────────────────────┬───────────────────────────────────┘
                             │
          ┌──────────────────┴────────────────────┐
          ↓                                       ↓
┌──────────────────────┐              ┌───────────────────────────┐
│ HOSTED MODE          │              │ LOCAL MODE                │
│ ModelProvider:       │              │ ModelProvider:            │
│   endpoint=          │              │   endpoint=               │
│   integrate.api.     │              │   http://ZGX:8090/v1      │
│   nvidia.com/v1      │              │                           │
│   api_key=NVIDIA_KEY │              │ vLLM serving Qwen3-32B    │
│                      │              │ or qwen3-coder etc.       │
│ Available models:    │              │ Available models:         │
│  nvidia/nemotron-3-  │              │  whatever is loaded on    │
│  nano-30b-a3b        │              │  the Nano                 │
│  ... (7 total)       │              │                           │
└──────────────────────┘              └───────────────────────────┘

Both paths use the SAME data_designer library and SAME config objects.
```

### Why FastAPI (not calling Data Designer SDK from JS)

Data Designer is Python-only. The SDK must run in Python. Frontend sends a JSON "schema spec" (our format, which maps 1:1 to column configs), backend translates to `DataDesignerConfigBuilder`, executes, streams results back. This also lets us enforce rate limiting and budget tracking server-side, which would be trivially bypassable if we let the browser call NVIDIA directly.

### Vertical presets

Presets are **JSON config files** on the backend at `presets/{vertical}.json`, not hardcoded. Picking a preset pre-fills the schema builder; user can then add/remove/edit columns freely. Initial verticals:

- `healthcare` — patient records (person sampler for demographics, ICD-10 category sampler, chief complaint LLM-text, SOAP note LLM-structured)
- `federal` — clearance levels, mission codes, incident reports
- `sled` — school district / state/local gov records
- `manufacturing` — part numbers, defect categories, inspection notes
- `maritime` — vessel tracking, cargo manifests, OPSEC-sensitive patterns
- `financial_services` — transactions, fraud indicators (regulated buyer language)

Each preset includes a "demo narrative" field — the opening line that anchors the demo (e.g., "Where does this patient data go? Right here. Nowhere else.").

### Budget tracking (concrete approach)

Server-side SQLite table:
```
jobs(id, user, mode, model, schema_hash, num_records,
     est_llm_calls, actual_llm_calls, started_at, finished_at, status)
```

Per-user budget derived from the table:
- `jobs_today` = count where `started_at` >= today 00:00
- `rpm_window` = sum of llm_calls in last 60s across all jobs
- `credit_estimate` = actual_llm_calls × per-call estimate (surface, don't gate)

Client polls `/api/budget` every 5s while active. UI badges turn yellow at 75%, red at 100%. On 100%, submit button is disabled with tooltip explaining why.

Rate limiting uses token-bucket per provider: hosted bucket = 40 tokens, refills at 40/60s; local bucket = configurable (much higher, default 120 RPM since Nano can handle it). Submitter blocks until token available rather than submitting and getting 429'd.

### Local mode specifics

- vLLM serving on ZGX Nano, existing pattern (`awq_marlin`, sm_121)
- Default model: Qwen3-32B-AWQ (matches enterprise demo quality band Curtis uses)
- Backend detects available local models by hitting `/v1/models` on the local endpoint — same OpenAI-compatible convention Data Designer already uses
- Config env var: `LOCAL_VLLM_URL=http://192.168.10.123:8090/v1`
- Health check pings both endpoints; UI shows green/yellow/red per mode

### Model selection UX

Single dropdown, grouped by mode:

```
─── NVIDIA Hosted (cloud) ───
  nvidia/nemotron-3-nano-30b-a3b      [default, fast]
  nvidia/nvidia-nemotron-nano-9b-v2   [fastest]
  nvidia/llama-3.3-nemotron-super-49b-v1.5  [highest quality]
  mistralai/mistral-small-24b-instruct
  openai/gpt-oss-20b
  openai/gpt-oss-120b                 [slow, premium]
  meta/llama-4-scout-17b-16e-instruct

─── Local on ZGX Nano ───
  Qwen3-32B-AWQ                       [default]
  qwen3-coder                         [code columns]
  (auto-detected from /v1/models)
```

Mode toggle sets which group is selectable. Switching modes resets model to that mode's default.

## Implementation plan

### Phase 1: Backend skeleton (Day 1)

- FastAPI app, Python 3.11, `uv` for deps per Data Designer's documented preference
- Install `data-designer` from PyPI
- `/api/health` wired to both providers
- `/api/models` returning mode-grouped list
- Config loading: `.env` for `NVIDIA_API_KEY`, `LOCAL_VLLM_URL`
- Budget tracking: SQLite + SQLAlchemy, token-bucket limiter class
- Dockerfile, docker-compose.yml (backend + optional local vLLM compose profile)

### Phase 2: Schema translation layer (Day 1-2)

- Define our JSON schema spec format (frontend-friendly, flat, serializable)
- `spec_to_config_builder()` function: converts our spec → `DataDesignerConfigBuilder`
- `/api/schema/validate` endpoint: accepts spec, returns validation errors + estimated LLM calls per record
- Unit tests for each column type supported in v1

### Phase 3: Generation endpoints (Day 2)

- `/api/generate/preview` — wraps `data_designer.preview()`, returns 10 records synchronously
- `/api/generate/create` — wraps `data_designer.create()`, tracks as job, returns job_id immediately, streams progress via SSE
- `/api/jobs/{id}` — status polling fallback
- `/api/jobs/{id}/download` — serves CSV/JSON/Parquet from completed jobs

### Phase 4: Frontend (Day 3-4)

- React + Vite + Tailwind + shadcn/ui per your existing dashboard pattern
- Pages:
  - **Builder** — vertical picker, schema canvas (add/remove/reorder columns), model dropdown, mode toggle, budget panel, preview/create buttons
  - **Results** — table view with sticky headers, per-record drill-down, export buttons
  - **Jobs** — history of previous runs with schema hash, allow re-run
- State management: Zustand (lightweight, matches your other projects)
- SSE consumer for streaming previews

### Phase 5: Presets (Day 4)

- Six vertical preset JSON files
- Each includes: display name, tagline, demo narrative opener, 5-8 starter columns
- Preset picker shows cards with vertical icon + tagline
- "Start from blank" option always available

### Phase 6: Observability (Day 4-5)

- Structured logging from day one (Curtis's "observability first" principle)
- Every generation request logged with: mode, model, schema hash, num_records, duration, LLM call count, success/failure
- `/api/debug/recent-errors` endpoint (last 50 errors with stack traces) — saves future debugging time
- Frontend: toast notifications for rate limit hits, budget warnings, and errors with error codes

### Phase 7: Polish for internal demo (Day 5)

- Seed the SQLite DB with a few historical "successful run" records so the UI doesn't look empty on first load
- README with quickstart (uv install, env vars, docker-compose up)
- `tasks/lessons.md` seeded — will accumulate during build

## Open decisions for Curtis before I start coding

1. **Auth** — any internal SSO needed or is "on the corp network = trusted" fine for v1? My default: no auth for v1, bind to localhost or internal network only
2. **Persistence of generated datasets** — keep all outputs forever in SQLite+filesystem, or TTL them (e.g. 30 days)? My default: keep forever, small footprint
3. **Deployment target** — run the backend on the ZGX Nano itself (so local mode has zero network hop) or on a workstation that connects to the Nano for local mode? My default: on the Nano — tighter integration, one less machine
4. **Rate limit on local mode** — cap it to match hosted (40 RPM) so demos show identical pacing, or let it rip at the Nano's real throughput (100+ RPM) to show a speed advantage? My default: let it rip, the speed difference IS part of the Compliance by Architecture story
5. **"Cost saved" counter** — your boss wanted a token counter for the voice agent for cloud-cost-savings framing. Same treatment here? Show running "$ saved by running local" counter based on cumulative LLM calls × per-call cost estimate? My default: yes, this is an easy win for exec-audience framing

## Risks / things to watch

- **Schema drift**: Data Designer is marked beta and API may change. Pin the version and track upgrades deliberately
- **Preview-only hosted mode**: The managed NVIDIA hosted Data Designer endpoint (`ai.api.nvidia.com/v1/nemo/dd`) is preview-only. We should bypass it and use the library directly, pointing at `integrate.api.nvidia.com/v1`. This gives us full create jobs, not just previews. Decision: use library + direct NVIDIA provider, not the managed hosted Data Designer orchestrator
- **Rate limit opacity**: NVIDIA doesn't expose a "credits remaining" API reliably (per the forum threads). Our budget display is a best-effort estimate, not a guarantee. UI copy should say "estimated" not "remaining"
- **Jinja template injection**: Security docs flag that user-supplied Jinja is a code-execution concern. v1 is internal-only so risk is low, but flag it in lessons.md and default to `JinjaRenderingEngine.SECURE`
