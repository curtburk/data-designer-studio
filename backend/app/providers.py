"""Provider registration and discovery.

Both providers register with one DataDesigner instance. The schema's
ModelConfig.provider field selects which provider routes each LLM call.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from data_designer.config.models import ModelProvider

from .settings import settings

log = logging.getLogger("ddstudio.providers")

# Hosted models per NVIDIA Build catalog. Source: build.nvidia.com.
HOSTED_MODELS: list[dict[str, Any]] = [
    {"id": "nvidia/nemotron-3-nano-30b-a3b",            "label": "Nemotron 3 Nano 30B (A3B)",      "tags": ["default", "fast"],          "notes": "Hybrid Mamba MoE. Good default."},
    {"id": "nvidia/nvidia-nemotron-nano-9b-v2",         "label": "Nemotron Nano 9B v2",            "tags": ["fastest", "cheap"],         "notes": "Cheapest. Lowest latency."},
    {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5",  "label": "Llama 3.3 Nemotron Super 49B",   "tags": ["highest-quality"],          "notes": "Best output quality. Burns credits."},
    {"id": "mistralai/mistral-small-24b-instruct",      "label": "Mistral Small 24B Instruct",     "tags": ["balanced"],                 "notes": "Apache 2.0 generations."},
    {"id": "openai/gpt-oss-20b",                        "label": "GPT-OSS 20B",                    "tags": ["balanced"],                 "notes": "Open-weight GPT-OSS."},
    {"id": "openai/gpt-oss-120b",                       "label": "GPT-OSS 120B",                   "tags": ["slow", "premium"],          "notes": "Highest hosted capability."},
    {"id": "meta/llama-4-scout-17b-16e-instruct",       "label": "Llama 4 Scout 17B (16E MoE)",    "tags": ["balanced"],                 "notes": "Llama 4 Community License."},
]


def build_providers() -> list[ModelProvider]:
    """Both providers, registered unconditionally. Health check surfaces dead ones."""
    return [
        ModelProvider(
            name="nvidia-hosted",
            endpoint=settings.nvidia_endpoint,
            provider_type="openai",
            api_key=settings.nvidia_api_key or "NOT_SET",
        ),
        ModelProvider(
            name="zgx-local",
            endpoint=settings.local_vllm_url,
            provider_type="openai",
            api_key=settings.local_vllm_api_key,
        ),
        ModelProvider(
            name="zgx-local-fast",
            endpoint=getattr(settings, "local_vllm_url_fast", settings.local_vllm_url),
            provider_type="openai",
            api_key=settings.local_vllm_api_key,
        ),
    ]


def hosted_models() -> list[dict[str, Any]]:
    return [{**m, "mode": "hosted"} for m in HOSTED_MODELS]


async def discover_local_models() -> list[dict[str, Any]]:
    """Hit /v1/models on the local vLLM. Empty list if unreachable - the UI
    treats that as 'local mode unavailable' without crashing the page."""
    url = settings.local_vllm_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {settings.local_vllm_api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("local model discovery failed", extra={"url": url, "error": str(e)})
        return []
    return [
        {
            "id": m["id"],
            "label": m["id"].split("/")[-1],
            "mode": "local",
            "tags": ["local", "on-prem"],
            "notes": "Served by vLLM. Data does not leave the device.",
        }
        for m in data.get("data", []) if m.get("id")
    ]


async def check_hosted_health() -> dict[str, Any]:
    if not settings.nvidia_api_key:
        return {"status": "unconfigured", "reason": "NVIDIA_API_KEY not set in .env"}
    url = settings.nvidia_endpoint.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {settings.nvidia_api_key}"})
            if resp.status_code == 401:
                return {"status": "error", "reason": "API key rejected (401)"}
            resp.raise_for_status()
            return {"status": "healthy", "endpoint": settings.nvidia_endpoint}
    except Exception as e:
        return {"status": "unreachable", "reason": str(e)}


async def check_local_health() -> dict[str, Any]:
    models = await discover_local_models()
    if not models:
        return {
            "status": "unreachable",
            "reason": f"No models from {settings.local_vllm_url}/models. Is vLLM running?",
        }
    return {
        "status": "healthy",
        "endpoint": settings.local_vllm_url,
        "models_loaded": [m["id"] for m in models],
    }
