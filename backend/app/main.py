"""FastAPI entrypoint.

Two debugging-focused features make this enterprise-credible without paranoia:
1. request_id middleware: every error response includes an X-Request-ID
   header. Logs include the same id. User pastes id, we grep, we know.
2. /api/health/detailed: tells the user EXACTLY what is misconfigured
   before they hit Generate. Half the "told me it'd work" complaints come
   from a missing env var nobody noticed.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import jobs
from .generator import kick_create, run_preview
from .logging_config import log, request_id_var, setup_logging
from .presets import list_presets, load_preset
from .providers import (
    check_hosted_health, check_local_health,
    discover_local_models, hosted_models,
)
from .schema_spec import SchemaSpec
from .settings import settings
from .translator import validate_schema

setup_logging()

app = FastAPI(title="Data Designer Studio", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://localhost:3000",
        "http://127.0.0.1:5173", "http://127.0.0.1:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- request_id middleware: the debugging spine ----
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
    except Exception as e:
        log.exception("unhandled error", extra={"path": request.url.path})
        response = JSONResponse(
            status_code=500,
            content={"error": str(e), "request_id": rid},
        )
    response.headers["X-Request-ID"] = rid
    request_id_var.reset(token)
    return response


# ---- health ----
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "backend": "healthy",
        "hosted": await check_hosted_health(),
        "local": await check_local_health(),
    }


@app.get("/api/health/detailed")
async def health_detailed() -> dict[str, Any]:
    """Pre-flight: every common cause of 'it doesn't work' is checked here.
    If everything below shows ok, the app will work. If something shows
    error, that's exactly what to fix."""
    checks: list[dict[str, Any]] = []

    # NVIDIA key configured
    if settings.nvidia_api_key.startswith("nvapi-"):
        checks.append({"name": "NVIDIA_API_KEY format", "status": "ok"})
    elif settings.nvidia_api_key:
        checks.append({
            "name": "NVIDIA_API_KEY format", "status": "warn",
            "detail": "Set but does not start with 'nvapi-' - may be invalid",
        })
    else:
        checks.append({
            "name": "NVIDIA_API_KEY format", "status": "missing",
            "detail": "Hosted mode unavailable. Set NVIDIA_API_KEY in .env to enable.",
        })

    # Hosted reachable
    hosted = await check_hosted_health()
    checks.append({
        "name": f"Hosted endpoint reachable ({settings.nvidia_endpoint})",
        "status": "ok" if hosted["status"] == "healthy" else "error",
        "detail": hosted.get("reason", ""),
    })

    # Local reachable
    local = await check_local_health()
    checks.append({
        "name": f"Local vLLM reachable ({settings.local_vllm_url})",
        "status": "ok" if local["status"] == "healthy" else "error",
        "detail": local.get("reason", ""),
        "models_loaded": local.get("models_loaded", []),
    })

    # Artifact dir writable
    try:
        test = settings.artifact_path / ".write_test"
        test.write_text("ok")
        test.unlink()
        checks.append({"name": f"Artifact path writable ({settings.artifact_path})", "status": "ok"})
    except Exception as e:
        checks.append({
            "name": f"Artifact path writable ({settings.artifact_path})",
            "status": "error", "detail": str(e),
        })

    # DB reachable
    try:
        jobs.recent(1)
        checks.append({"name": "Job DB readable", "status": "ok"})
    except Exception as e:
        checks.append({"name": "Job DB readable", "status": "error", "detail": str(e)})

    overall = "ok" if all(c["status"] == "ok" for c in checks) else (
        "warn" if any(c["status"] == "warn" for c in checks)
                  and not any(c["status"] == "error" for c in checks)
        else "error"
    )
    return {"overall": overall, "checks": checks}


# ---- model + preset discovery ----
@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    return {
        "hosted": hosted_models(),
        "local": await discover_local_models(),
    }


@app.get("/api/presets")
async def get_presets() -> dict[str, Any]:
    return {"presets": list_presets()}


@app.get("/api/presets/{preset_id}")
async def get_preset(preset_id: str) -> dict[str, Any]:
    try:
        return load_preset(preset_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ---- schema validation ----
@app.post("/api/schema/validate")
async def validate(schema: SchemaSpec) -> dict[str, Any]:
    return validate_schema(schema)


# ---- generation ----
@app.post("/api/generate/preview")
async def gen_preview(
    schema: SchemaSpec,
    num_records: int = Query(default=10, ge=1, le=10),
) -> dict[str, Any]:
    # Re-run validation server-side so a bad schema returns 400 with field errors,
    # not a 500 from deep inside DD.
    v = validate_schema(schema)
    if not v["valid"]:
        raise HTTPException(status_code=400, detail={
            "message": "schema validation failed", "errors": v["errors"],
        })
    return await run_preview(schema, num_records)


@app.post("/api/generate/create")
async def gen_create(
    schema: SchemaSpec,
    num_records: int = Query(default=100, ge=1, le=100),
) -> dict[str, Any]:
    v = validate_schema(schema)
    if not v["valid"]:
        raise HTTPException(status_code=400, detail={
            "message": "schema validation failed", "errors": v["errors"],
        })
    job_id = kick_create(schema, num_records)
    return {
        "job_id": job_id, "num_records": num_records,
        "est_llm_calls": schema.estimate_llm_calls(num_records),
        "status": "running",
    }


# ---- jobs ----
@app.get("/api/jobs")
async def list_jobs(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    return {"jobs": jobs.recent(limit)}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    return job


@app.get("/api/jobs/{job_id}/download")
async def download_job(
    job_id: str,
    format: str = Query(default="csv", pattern="^(csv|parquet|json)$"),
) -> FileResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    if job["status"] != "complete":
        raise HTTPException(status_code=409, detail=f"job status is '{job['status']}'")
    if not job["dataset_path"]:
        raise HTTPException(status_code=404, detail="no dataset for this job")

    base = Path(job["dataset_path"])
    if format == "csv":
        path, media = base / "dataset.csv", "text/csv"
    elif format == "parquet":
        path, media = base / "dataset.parquet", "application/octet-stream"
    else:  # json - derive from parquet on demand
        import pandas as pd
        json_path = base / "dataset.json"
        if not json_path.exists():
            pd.read_parquet(base / "dataset.parquet").to_json(
                json_path, orient="records", indent=2,
            )
        path, media = json_path, "application/json"

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"file missing: {path.name}")
    return FileResponse(
        path=path, media_type=media,
        filename=f"{job['schema_name']}_{job_id}.{format}",
    )


# ---- budget (now without the token bucket) ----
@app.get("/api/budget")
async def budget(mode: str = Query(default="hosted", pattern="^(hosted|local)$")) -> dict[str, Any]:
    """Simplified: today's usage + an LLM-call estimate. No pre-emptive limits."""
    s = jobs.stats_today(mode)
    return {
        "mode": mode,
        "jobs_today": s["jobs_today"],
        "llm_calls_today": s["llm_calls_today"],
        # Reference numbers (what NVIDIA says, what we configure for local):
        "hosted_rpm_reference": 40 if mode == "hosted" else None,
        "note": (
            "NVIDIA Build default is 40 req/min. If a job hits 429, the error "
            "appears in the job history immediately."
            if mode == "hosted" else
            "Local mode pacing is bounded only by your vLLM throughput."
        ),
    }


# ---- debug ----
@app.get("/api/debug/recent-errors")
async def recent_errors() -> dict[str, Any]:
    return {"errors": jobs.recent_errors()}


# ---- root + frontend ----
@app.get("/")
async def root() -> dict[str, Any]:
    return {"service": "Data Designer Studio", "version": "0.1.0", "ui": "/app/", "docs": "/docs"}


_FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
if not _FRONTEND.exists():
    # Container layout: /app/app/main.py -> /app/frontend
    _FRONTEND = Path("/app/frontend")
if _FRONTEND.exists():
    app.mount("/app", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")


def main() -> None:
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
