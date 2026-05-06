"""Run preview() and create() against Data Designer.

When NVIDIA returns 429 or vLLM is unreachable, that error propagates to the
user with the original message. No pre-emptive throttling - we'd rather see
the real failure than mask it.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from data_designer.interface.data_designer import DataDesigner

from . import jobs
from .providers import build_providers
from .schema_spec import SchemaSpec
from .settings import settings
from .translator import build_config_builder

log = logging.getLogger("ddstudio.generator")

# One DataDesigner instance for the lifetime of the process. Both providers
# are registered on it; the schema's ModelConfig.provider routes each call.
_dd: DataDesigner | None = None


def _designer() -> DataDesigner:
    global _dd
    if _dd is None:
        _dd = DataDesigner(
            artifact_path=settings.artifact_path,
            model_providers=build_providers(),
        )
        log.info("DataDesigner initialized", extra={
            "artifact_path": str(settings.artifact_path),
        })
    return _dd


async def run_preview(schema: SchemaSpec, num_records: int = 10) -> dict[str, Any]:
    """Synchronous-ish preview, capped at 10 records."""
    num_records = min(num_records, 10)
    job_id = jobs.new_job_id("preview")
    est_calls = schema.estimate_llm_calls(num_records)

    jobs.record_start(
        job_id=job_id, kind="preview", mode=schema.models[0].mode, model=schema.models[0].model_id, schema_hash=schema.hash(),
        schema_name=schema.name, num_records=num_records,
        est_llm_calls=est_calls,
    )

    try:
        builder = build_config_builder(schema)
        result = await asyncio.to_thread(_designer().preview, builder, num_records=num_records)
        df = result.dataset
        records = df.to_dict(orient="records") if df is not None else []
        jobs.record_finish(job_id=job_id, status="complete", actual_llm_calls=est_calls)
        return {
            "job_id": job_id,
            "records": records,
            "columns": list(df.columns) if df is not None else [],
            "num_records": len(records),
            "est_llm_calls": est_calls,
        }
    except Exception as e:
        log.exception("preview failed", extra={"job_id": job_id})
        jobs.record_finish(job_id=job_id, status="failed", error=str(e))
        raise


def kick_create(schema: SchemaSpec, num_records: int) -> str:
    """Schedule a background create job. Returns job_id immediately."""
    job_id = jobs.new_job_id("create")
    asyncio.create_task(_run_create(schema, num_records, job_id))
    return job_id


async def _run_create(schema: SchemaSpec, num_records: int, job_id: str) -> None:
    est_calls = schema.estimate_llm_calls(num_records)
    jobs.record_start(
        job_id=job_id, kind="create", mode=schema.models[0].mode, model=schema.models[0].model_id, schema_hash=schema.hash(),
        schema_name=schema.name, num_records=num_records,
        est_llm_calls=est_calls,
    )
    try:
        builder = build_config_builder(schema)
        result = await asyncio.to_thread(
            _designer().create, builder,
            num_records=num_records,
            dataset_name=f"{schema.name}_{job_id}",
        )
        path = _persist(job_id, result)
        jobs.record_finish(
            job_id=job_id, status="complete",
            actual_llm_calls=est_calls,
            dataset_path=str(path) if path else None,
        )
    except Exception as e:
        log.exception("create failed", extra={"job_id": job_id})
        jobs.record_finish(job_id=job_id, status="failed", error=str(e))


def _persist(job_id: str, result: Any) -> Path | None:
    # DatasetCreationResults exposes data via load_dataset(), not a `dataset` field.
    # PreviewResults uses .dataset directly, so keep that fallback.
    df = None
    if hasattr(result, "load_dataset"):
        df = result.load_dataset()
    elif hasattr(result, "dataset"):
        df = result.dataset
    if df is None:
        log.warning("persist: result has no dataset", extra={"job_id": job_id})
        return None
    base = settings.artifact_path / job_id
    base.mkdir(parents=True, exist_ok=True)
    df.to_csv(base / "dataset.csv", index=False)
    df.to_parquet(base / "dataset.parquet", index=False)
    log.info("artifacts written", extra={"job_id": job_id, "rows": len(df), "path": str(base)})
    return base
