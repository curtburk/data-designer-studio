# HP Data Designer Studio

An LLM powered tool for generating vertical-specific synthetic datasets on-premises. Wraps NVIDIA's `data-designer` library with a web UI, dual-mode execution (NVIDIA hosted API vs. local vLLM on ZGX Nano), and a six-preset starter library covering healthcare, federal/defense, SLED, manufacturing, maritime, and financial services.

Switch a single toggle, the only difference is where the LLM calls go.

---

## What it does

You pick a vertical (or build a schema from scratch), edit the columns and prompts, click Preview, and get back synthetic records with both deterministic samplers (UUID, age, category, etc.) and LLM-generated text columns (SOAP notes, fraud case summaries, equipment defect reports, etc.). Generation runs end-to-end on the ZGX Nano with no outbound traffic — that's the proof.

The current build supports **dual-model routing**: a single dataset can split LLM columns across multiple models. Healthcare's preset uses this - the rich `history_of_present_illness` column hits Qwen3-32B-AWQ for clinical accuracy, the supporting `assessment_and_plan` column hits Qwen3-14B-AWQ for speed. Both run on the same Nano simultaneously. Buyers see one box, two models, one coherent record per row.

---

## Architecture

```
                        ┌─────────────────────────────────────┐
                        │    Browser at /app/                 │
                        │    (HP-branded React UI)            │
                        └──────────────┬──────────────────────┘
                                       │
                                       ▼
        ┌──────────────────────────────────────────────────────┐
        │  ddstudio container (port 8765)                      │
        │  FastAPI backend + bundled React app                 │
        │  - schema validation, job orchestration              │
        │  - SQLite job DB at /var/lib/ddstudio/ddstudio.db    │
        │  - Datasets at /var/lib/ddstudio/artifacts/          │
        └─────────┬────────────────────────────────┬───────────┘
                  │                                │
        local mode│                                │hosted mode
                  ▼                                ▼
   ┌─────────────────────────────┐    ┌─────────────────────────────┐
   │  ddstudio-vllm (port 8090)  │    │  integrate.api.nvidia.com   │
   │  Qwen/Qwen3-32B-AWQ         │    │  (NVIDIA Build, requires    │
   │  --gpu-memory-utilization   │    │   nvapi-... key)            │
   │     0.55                    │    └─────────────────────────────┘
   └─────────────────────────────┘
   ┌─────────────────────────────┐
   │  ddstudio-vllm-fast (8091)  │   ← optional second container,
   │  Qwen/Qwen3-14B-AWQ         │     enables dual-routing
   │  --gpu-memory-utilization   │
   │     0.35                    │
   └─────────────────────────────┘
```

**Memory budget** on a 119 GB GB10 with both vLLMs running:
- 32B at 0.55 utilization ≈ 65 GB
- 14B at 0.35 utilization ≈ 42 GB
- System headroom ≈ 12 GB

If you only need single-model serving, run `VLLM_FAST_ENABLED=false ./start.sh` and bump `VLLM_GPU_MEM=0.9` to give the 32B all the room.

---

## Hardware

- **HP ZGX Nano AI Station** (NVIDIA GB10 Grace Blackwell, ARM64, 128 GB unified memory, sm_121)
- Wired networking to a LAN where the demo audience can browse to the Nano's IP
- ~50 GB free disk (for the model weights cache under `~/.cache/huggingface`)

Also runs on the HP Z8 Fury G5 Workstation (4× RTX PRO 6000 Blackwell, 384 GB VRAM) for higher-throughput testing.

---

## First-time install

### 1. Software prerequisites

```bash
# Docker + compose plugin (Ubuntu/Debian)
sudo apt update
sudo apt install -y docker.io docker-compose-plugin

# nvidia-container-toolkit (lets containers see the GPU)
# follow https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/

# Confirm everything is wired
docker compose version
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

**Note for DGX OS Nanos:** If `apt install docker.io` fails with a containerd conflict, DGX OS ships with NVIDIA's pinned containerd that conflicts with the standard Docker package. On a Nano with no other GPU workloads running, the fix is to purge and reinstall:

```bash
sudo apt remove -y docker docker-engine docker.io containerd runc
sudo apt autoremove -y
sudo apt install -y docker.io docker-compose-plugin
```

If the Nano is already running other NVIDIA demos, check with whoever maintains that machine before purging — the pinned containerd may be required by other workloads.

### 2. Get the source

```bash
cd ~/Desktop
git clone https://github.com/curtburk/data-designer-studio.git
cd data-designer-studio
```

If the repo is private, ask Curtis to add you as a collaborator on GitHub, or clone using a personal access token:

```bash
git clone https://<your-username>:<your-PAT>@github.com/curtburk/data-designer-studio.git
```

### 3. Configure environment

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Set at minimum:

```
NVIDIA_API_KEY=nvapi-yourkeyhere
LOCAL_VLLM_URL=http://192.168.xx.xxx:8090/v1       # use your Nano's actual IP
LOCAL_VLLM_URL_FAST=http://192.168.xx.xxx:8091/v1  # used by dual-routing presets
```

**Important:** use the Nano's explicit IP, not `host.docker.internal` — that hostname does not resolve from inside containers on Linux Docker. (See Gotchas below.)

### 4. Run

```bash
chmod +x start.sh
./start.sh
```

First start downloads ~30 GB of model weights and takes 15-25 minutes. Subsequent starts are 30-60 seconds because Docker layer cache, vLLM compile cache, and HuggingFace cache all persist.

When you see `Data Designer Studio is up`, open `http://<nano-ip>:8765/app/` in your browser. Click the **Preflight** tab. Five green checks means you're ready.

---

## Daily use

### Start everything

```bash
cd ~/Desktop/data-designer-studio
./start.sh
```

Idempotent. Reuses healthy containers, only rebuilds Studio if source changed.

### Start without the second vLLM (single-model mode)

Healthcare preset's dual-routing won't work, but other presets are unaffected:

```bash
VLLM_FAST_ENABLED=false ./start.sh
```

### Start without any local vLLM (hosted-only mode)

Useful for events with bad network where you don't want to wait for vLLM to load:

```bash
./start.sh --skip-vllm
```

Studio's local-mode preflight will be red. Hosted mode works fine.

### Stop Studio (leave vLLMs running)

```bash
docker compose down
```

vLLMs persist with `--restart unless-stopped`, including across Nano reboots.

### Stop everything

```bash
docker compose down
docker stop ddstudio-vllm ddstudio-vllm-fast
docker rm ddstudio-vllm ddstudio-vllm-fast
```

### Watch logs

```bash
# Studio backend (job lifecycle, request IDs, errors)
docker compose logs -f ddstudio

# vLLM 32B (chat completion requests, throughput stats)
docker logs -f ddstudio-vllm

# vLLM 14B
docker logs -f ddstudio-vllm-fast

# Just the chat completions firing right now (the demo prop)
docker logs -f ddstudio-vllm 2>&1 | grep "chat/completions"
```

---

## Presets

Six verticals ship in `presets/*.json`:

| Preset | Schema | LLM columns | Default model |
|---|---|---|---|
| **Healthcare** | Patient encounters w/ SOAP notes | `history_of_present_illness` (rich), `assessment_and_plan` (fast) | Dual-routing: 32B + 14B |
| **Federal & Defense** | Mission logs, incident reports | Single LLM column | Qwen/Qwen3-14B-AWQ |
| **State, Local & Education** | Student records, permits | Single LLM column | Qwen/Qwen3-14B-AWQ |
| **Manufacturing** | Inspection reports, defect classifications | Single LLM column | Qwen/Qwen3-14B-AWQ |
| **Maritime** | AIS, cargo, surveillance | Single LLM column | Qwen/Qwen3-14B-AWQ |
| **Financial Services** | Transactions, fraud case summaries | Single LLM column | Qwen/Qwen3-14B-AWQ |

Healthcare is the showcase — it demonstrates dual-model routing on one record. The others are deliberately simpler so they generate fast for live demos (typically 30-60 seconds for 10 records).

### Editing a preset

The JSON files are mounted into the container as a read-only volume, so edits are picked up instantly without a rebuild. Just save and refresh the browser.

```bash
nano presets/healthcare.json
# (edit, save)
# refresh browser - new schema renders
```

### Adding a new preset

1. Copy an existing preset:
   ```bash
   cp presets/healthcare.json presets/legal.json
   ```
2. Edit the `display_name`, `tagline`, `icon`, `demo_narrative`, and `schema.*`
3. Refresh the Builder page — the new card appears

The card icon should be a single emoji. The `demo_narrative` shows in italics on the picker card and is your verbal hook for that vertical's compliance pain point.

---

## Multi-model routing

Healthcare's preset is the reference implementation. The relevant section of `presets/healthcare.json`:

```json
"models": [
  {
    "alias": "rich",
    "mode": "local",
    "model_id": "Qwen/Qwen3-32B-AWQ",
    "max_tokens": 600
  },
  {
    "alias": "fast",
    "mode": "local_fast",
    "model_id": "Qwen/Qwen3-14B-AWQ",
    "max_tokens": 400
  }
]
```

Each LLM column references one of these via its `model_alias`:

```json
{
  "kind": "llm_text",
  "name": "history_of_present_illness",
  "model_alias": "rich",
  "max_tokens": 400,
  ...
},
{
  "kind": "llm_text",
  "name": "assessment_and_plan",
  "model_alias": "fast",
  "max_tokens": 300,
  ...
}
```

### How modes map to providers

| `mode` value | Routes to | Default endpoint |
|---|---|---|
| `hosted` | NVIDIA Build | `https://integrate.api.nvidia.com/v1` |
| `local` | Primary vLLM | `LOCAL_VLLM_URL` (port 8090) |
| `local_fast` | Secondary vLLM | `LOCAL_VLLM_URL_FAST` (port 8091) |

You can mix freely — a schema can have a `hosted` model and two `local` models routing different columns. Tell the architectural story that fits your audience.

### Per-column `max_tokens`

Both `ModelChoice` (the model) and `Column` (the column using a model) can declare `max_tokens`. The column-level value wins. This is how you keep short summary columns from generating 1000-token essays:

```json
{
  "kind": "llm_text",
  "name": "one_line_disposition",
  "model_alias": "fast",
  "max_tokens": 80,           // tight budget for a short label
  "prompt": "..."
}
```

---

## Debugging

### Preflight tab

Open `http://<nano-ip>:8765/app/` and click **Preflight**. Five checks:

1. `NVIDIA_API_KEY format` — verifies the env var looks like `nvapi-...`
2. `Hosted endpoint reachable` — tries `GET /v1/models` against integrate.api.nvidia.com
3. `Local vLLM reachable` — tries `GET /v1/models` against `LOCAL_VLLM_URL`
4. `Artifact path writable` — confirms the persistent volume is mounted and writable
5. `Job DB readable` — confirms the SQLite file is intact

Each check has a `detail` line that explains what failed when status is not `ok`. The **Re-check** button re-runs them all without a page reload.

### Request IDs

Every API call gets a `request_id` (12-char hex), surfaced in three places:

- HTTP response header `X-Request-ID`
- Toast messages on errors (e.g., `"500: ... [rid=ee7bd16e7f4a]"`)
- Every backend log line with that request

Grep for the request_id to trace one user action through the entire backend:

```bash
docker compose logs ddstudio | grep ee7bd16e7f4a
```

### Job error inspection

```bash
# Latest 5 jobs with their error fields
curl -s http://localhost:8765/api/jobs?limit=5 | python3 -c "
import json, sys
for j in json.load(sys.stdin)['jobs']:
    print(f'{j[\"id\"]}  {j[\"status\"]:10}  {j.get(\"error\") or \"\"}')"
```

The Jobs tab in the UI also shows a `see error ↓` link on failed rows — hover for the tooltip with the full error text.

### Inspecting a generated dataset

The CSV download endpoint is at `/api/jobs/{job_id}/download?format=csv` (or `parquet`). To examine raw stored records inside the container:

```bash
docker compose exec ddstudio python -c "
import pandas as pd
df = pd.read_parquet('/var/lib/ddstudio/artifacts/job_XXX/dataset.parquet')
print(df.to_string())
"
```

---

## Environment variables

All in `backend/.env` unless noted. Bold = required.

| Variable | Default | Purpose |
|---|---|---|
| **`NVIDIA_API_KEY`** | (none) | Hosted-mode API key. Get from build.nvidia.com. |
| `LOCAL_VLLM_URL` | `http://192.168.xx.xxx:8090/v1` | Primary vLLM endpoint. **Use explicit IP, not `host.docker.internal`.** |
| `LOCAL_VLLM_URL_FAST` | `http://192.168.xx.xxx:8091/v1` | Secondary vLLM endpoint for dual-routing. |
| `LOCAL_VLLM_API_KEY` | `not-needed` | vLLM doesn't authenticate by default. |
| `BACKEND_PORT` | `8765` | Studio HTTP port. |
| `ARTIFACT_PATH` | `/var/lib/ddstudio/artifacts` | Where generated datasets land. |
| `JOB_DB_PATH` | `/var/lib/ddstudio/ddstudio.db` | SQLite job history. |

`start.sh` accepts these as runtime overrides:

| Variable | Default | Purpose |
|---|---|---|
| `VLLM_IMAGE` | `vllm/vllm-openai:latest` | Which vLLM image to run. |
| `VLLM_MODEL` | `Qwen/Qwen3-32B-AWQ` | Primary model. |
| `VLLM_QUANT` | `awq_marlin` | Quantization for primary model. |
| `VLLM_PORT` | `8090` | Primary vLLM host port. |
| `VLLM_GPU_MEM` | `0.55` | GPU memory utilization for primary (lower if running both). |
| `VLLM_FAST_ENABLED` | `true` | Whether to start the second vLLM. |
| `VLLM_FAST_MODEL` | `Qwen/Qwen3-14B-AWQ` | Secondary model. |
| `VLLM_FAST_PORT` | `8091` | Secondary vLLM host port. |
| `VLLM_FAST_GPU_MEM` | `0.35` | GPU memory utilization for secondary. |
| `HF_TOKEN` | (none) | HuggingFace token if downloading gated models. |
| `HF_CACHE` | `~/.cache/huggingface` | Where vLLM caches model weights. |

---

## Gotchas (real bugs from this build, now codified)

These are all addressed in the current code, but documented here because future-you may hit them again on a different deploy.

### `host.docker.internal` does not resolve on Linux Docker

A Docker Desktop convention that Linux installs don't always provide. If `LOCAL_VLLM_URL` uses this hostname, the Studio container will throw "Could not resolve host" errors during preflight. **Always use the Nano's explicit IP.**

If you absolutely need the hostname, add an `extra_hosts` entry to `docker-compose.yml`:

```yaml
services:
  ddstudio:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

### `docker compose restart` does not reload `.env`

After editing `backend/.env`, `restart` keeps the existing process with its old environment. To pick up env changes:

```bash
docker compose down
docker compose up -d
```

### vLLM `--default-chat-template-kwargs '{"enable_thinking": false}'` quoting

Qwen3 is a reasoning model. Without this flag, the model burns its `max_tokens` budget on internal reasoning and returns truncated answers. The flag must be passed with the JSON value as a discrete bash argv element (not via a shell variable that gets re-parsed), or you get `invalid loads value: '\'\'\'{"enable_thinking":'` errors. `start.sh` handles this correctly using bash arrays — copy that pattern if you ever rewrite the launcher.

### `--reasoning-parser qwen3` strips `<think>` blocks but doesn't disable thinking

The two flags are different. Without `enable_thinking: false`, the model still generates reasoning, the parser just routes it to a `reasoning` field instead of `content`. You need both flags for synthetic data use cases.

### GB10 sm_121 vs PyTorch supported range

vLLM startup logs show:

```
UserWarning: Found GPU0 NVIDIA GB10 which is of cuda capability 12.1.
Minimum and Maximum cuda capability supported by this version of PyTorch is (8.0) - (12.0)
```

Benign warning. vLLM JITs kernels at runtime via Marlin and works fine. If you build CUDA code yourself (e.g. whisper.cpp), use `-DCMAKE_CUDA_ARCHITECTURES="121"` and `-Wl,--allow-shlib-undefined` for runtime-injected `libcuda.so.1`.

### Both vLLMs together OOM by default

Default `--gpu-memory-utilization` is 0.9, which means the 32B grabs ~108 GB and there's nothing left for the 14B. `start.sh` caps the primary at `VLLM_GPU_MEM=0.55` and the secondary at `0.35`. If you need different bounds, set those env vars.

### Excel hides multi-line CSV cells

When you open a CSV with multi-line values (HPI, A/P, anything with `\n`), Excel shows only the first line per cell. The data is fine — verify with the formula bar. To display properly: select column → right-click → Column Width 80 → Home → Wrap Text. Or use a different viewer.

### Data Designer 0.3.8 has empty-looking `__init__.py` files

If you introspect `dir(data_designer)` and get empty results, the package uses lazy imports — submodules are only resolved on access. Always import from concrete paths (`data_designer.interface.data_designer.DataDesigner`, not `data_designer.DataDesigner`). The current code does this correctly.

### Reasoning model behavior depends on `enable_thinking`

Qwen3 with thinking ON generates `<think>...</think>` blocks before the answer. With thinking OFF, it skips the reasoning phase and produces a direct answer. For synthetic data generation, always disable thinking. For a chat agent where you want reasoning visible, enable it.

---

## Troubleshooting

### "Local vLLM unreachable" but `curl http://localhost:8090/v1/models` works from host

The Studio container can't resolve or reach the URL the host can. Check:

```bash
docker compose exec ddstudio env | grep LOCAL_VLLM
docker compose exec ddstudio curl -v http://192.168.xx.xxx:8090/v1/models
```

If env shows `host.docker.internal` and curl says "Could not resolve host" — switch to the explicit IP in `.env`, then `docker compose down && docker compose up -d`.

### Job submitted but never appears in Jobs table

Check the toast in the bottom-right when you click Generate. If it's red, the API rejected the request (look at the error). If it's green ("Job started"), the job got into the DB but a background task crashed before reporting status. Find the traceback:

```bash
docker compose logs --tail 100 ddstudio | grep -E "ERROR|Traceback"
```

### Job completes but CSV/Parquet download is empty or missing

The `_persist()` function in `generator.py` reads the dataset back from Data Designer's results object. If the result shape changed in a DD version bump, the read can silently fail. Verify the data exists:

```bash
docker compose exec ddstudio find /var/lib/ddstudio/artifacts/ -name "*.parquet"
```

If files exist but `dataset_path` in the job record is null, the persist step ran but didn't update the DB. Check the `_persist` log line for the `request_id` of that job and trace.

### vLLM crash-loops on startup with arg parse errors

Check `docker logs ddstudio-vllm` for "invalid loads value" or similar. Almost always a quoting bug in `start.sh`'s arg construction. The cure is the bash array pattern (already in current `start.sh`).

### "Engine core initialization failed: out of memory"

Another GPU process is holding memory. Run `nvidia-smi` to see who. Common culprits:

- A leftover `VLLM::EngineCore` process from a previous run that didn't clean up
- A different demo's vLLM container still running

Stop the offending process/container, then re-run `./start.sh`.

### UI is a black screen / white screen

Hard-refresh the browser (Ctrl+Shift+R / Cmd+Shift+R). The browser cached an older `app.js` from before the latest patches. If hard-refresh doesn't fix it, open DevTools → Console tab and look for the JavaScript error.

### Job is "running" forever

The job's `actual_llm_calls` field updates on completion, not during. Check the vLLM log to see if requests are still landing:

```bash
docker logs --tail 5 ddstudio-vllm
```

If `Running: 0 reqs` and `Avg generation throughput: 0 tokens/s` for 60+ seconds, the job is stuck. Most likely cause is a model-name mismatch — vLLM serves `Qwen/Qwen3-32B-AWQ` (with org prefix); presets must use the prefixed form.

---

## Rolling back

`apply-v012.sh` (the multi-model patch script) creates `.v011-backup/` with copies of every file it changed. If a patch breaks something:

```bash
cd ~/Desktop/data-designer-studio
ls .v011-backup/
cp .v011-backup/schema_spec.py.bak backend/app/schema_spec.py
cp .v011-backup/translator.py.bak backend/app/translator.py
# ... etc for whichever files
docker compose up -d --build
```

The frontend has its own backup at `frontend/app.js.bak-multimodel`.

---

## Project layout

```
data-designer-studio/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app, route definitions
│   │   ├── generator.py         DataDesigner orchestration, job runner
│   │   ├── jobs.py              SQLite job persistence
│   │   ├── presets.py           Preset loading from disk
│   │   ├── providers.py         ModelProvider registration
│   │   ├── schema_spec.py       SchemaSpec, Column, ModelChoice (Pydantic)
│   │   ├── translator.py        SchemaSpec → DataDesigner config
│   │   ├── settings.py          Env var parsing
│   │   └── logging_config.py    JSON structured logs with request_id
│   ├── data_designer_home/
│   │   └── model_providers.yaml DD library config (build artifact)
│   ├── .env                     Runtime config (not in git)
│   └── .env.example             Template for .env
├── frontend/
│   ├── index.html               Entry point with CDN imports
│   ├── app.js                   Single-file React app
│   └── logo_HP_Electric_Blue_keyline.png
├── presets/
│   ├── healthcare.json          Dual-model routing showcase
│   ├── federal.json
│   ├── financial_services.json
│   ├── manufacturing.json
│   ├── maritime.json
│   └── sled.json
├── tasks/
│   ├── todo.md                  Active work
│   └── lessons.md               Captured corrections
├── Dockerfile                   Studio image
├── docker-compose.yml           Studio service definition
├── start.sh                     Idempotent launcher (preflight, vLLMs, Studio)
├── apply-v012.sh                Multi-model patch (run once, generates .v011-backup)
└── README.md                    This file
```

---

## Versions

- **v0.1.0** — Initial monolithic build. Single model per schema. Basic Builder + Jobs UI.
- **v0.1.1** — Slimmer plumbing (raw sqlite, structlog → JSON), preflight tab, request_id middleware, per-field validation responses.
- **v0.1.2** — Multi-model routing. `models: [...]` in schema, per-column `max_tokens` overrides, dual-vLLM in `start.sh` with bounded GPU memory budgets, frontend ColumnEditor gains model_alias dropdown. Healthcare preset switched to dual-routing showcase.

---

## Demo script (the one-minute pitch)

When colleagues ask what this is, the answer that lands:

> *Open the UI.* "This is Data Designer Studio. It generates synthetic datasets for vertical demos."
>
> *Click Preflight.* "Five checks. Three for connectivity, two for storage. If all green, the tool works. When something breaks at a customer site, this tab tells me what's wrong before I have to call engineering."
>
> *Click Builder, pick Healthcare.* "Patient records preset. Notice the right side — two models. The HPI runs on Qwen3-32B because clinical text needs precision. The Assessment and Plan runs on Qwen3-14B for speed. Both on this Nano. No cloud."
>
> *Click Preview (10) and tail the vLLM logs.* "Watch the requests land — the 32B handles the rich column, the 14B handles the supporting column. Where does this data go? Right here on this device. Nowhere else. No BAA required, no compliance review, no PHI ever leaves the room."

That's the whole pitch. Compliance by Architecture in three minutes.

---

## Contact

Curtis Burkhalter, Technical Product Marketing Manager — AI Solutions, HP
