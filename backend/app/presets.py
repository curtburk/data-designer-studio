"""Vertical presets: JSON files in ../../presets, loaded on demand."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PRESETS_DIR = Path(__file__).resolve().parent.parent.parent / "presets"
if not PRESETS_DIR.exists():
    # Container layout: /app/app/presets.py -> /app/presets
    PRESETS_DIR = Path("/app/presets")


def list_presets() -> list[dict[str, Any]]:
    if not PRESETS_DIR.exists():
        return []
    out = []
    for f in sorted(PRESETS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            out.append({
                "id": f.stem,
                "name": data.get("display_name", f.stem),
                "tagline": data.get("tagline", ""),
                "demo_narrative": data.get("demo_narrative", ""),
                "icon": data.get("icon", "📄"),
                "column_count": len(data.get("schema", {}).get("columns", [])),
            })
        except Exception:
            continue
    return out


def load_preset(preset_id: str) -> dict[str, Any]:
    path = PRESETS_DIR / f"{preset_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"preset '{preset_id}' not found")
    return json.loads(path.read_text())
