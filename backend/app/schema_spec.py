"""Schema spec - what the frontend sends.

v0.1.2: models is now a list, columns gain per-column max_tokens override.
Legacy `model: {...}` shape is auto-promoted to `models: [{...}]`.
"""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ColumnKind = Literal["sampler", "llm_text", "llm_code", "expression"]
SamplerType = Literal[
    "uuid", "category", "subcategory", "uniform", "gaussian",
    "person", "datetime", "bernoulli", "poisson",
]


class Column(BaseModel):
    name: str
    kind: ColumnKind
    drop: bool = False

    sampler_type: SamplerType | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    convert_to: str | None = None

    model_alias: str | None = None
    prompt: str | None = None
    system_prompt: str | None = None
    language: str | None = "python"
    # Per-column max_tokens override. None = use model default.
    max_tokens: int | None = None

    expression: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not v or not v.replace("_", "").isalnum():
            raise ValueError("name must be alphanumeric/underscore")
        if v.endswith("__trace") or v.endswith("__reasoning_content"):
            raise ValueError("name uses a reserved Data Designer suffix")
        return v

    @model_validator(mode="after")
    def _kind_requirements(self) -> "Column":
        if self.kind == "sampler":
            if not self.sampler_type:
                raise ValueError(f"sampler column '{self.name}' missing sampler_type")
        elif self.kind in ("llm_text", "llm_code"):
            if not self.prompt:
                raise ValueError(f"LLM column '{self.name}' missing prompt")
            if not self.model_alias:
                raise ValueError(f"LLM column '{self.name}' missing model_alias")
        elif self.kind == "expression":
            if not self.expression:
                raise ValueError(f"expression column '{self.name}' missing expression")
        return self


class ModelChoice(BaseModel):
    mode: Literal["hosted", "local", "local_fast"]
    model_id: str
    alias: str = "primary"
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)
    max_tokens: int = Field(default=1024, ge=1, le=32768)


class SchemaSpec(BaseModel):
    name: str = Field(default="untitled_dataset", min_length=1, max_length=128)
    description: str = ""
    vertical: str | None = None
    models: list[ModelChoice] = Field(default_factory=list)
    columns: list[Column] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_model_field(cls, data: Any) -> Any:
        if isinstance(data, dict) and "model" in data and "models" not in data:
            data = dict(data)
            single = data.pop("model")
            data["models"] = [single] if single is not None else []
        return data

    @model_validator(mode="after")
    def _validate_models_and_aliases(self) -> "SchemaSpec":
        if not self.models:
            raise ValueError("schema must define at least one model in `models`")
        aliases = [m.alias for m in self.models]
        if len(aliases) != len(set(aliases)):
            dupes = sorted({a for a in aliases if aliases.count(a) > 1})
            raise ValueError(f"duplicate model aliases: {dupes}")
        valid = set(aliases)
        for col in self.columns:
            if col.kind in ("llm_text", "llm_code") and col.model_alias not in valid:
                raise ValueError(
                    f"column '{col.name}' references model_alias "
                    f"'{col.model_alias}' but only {sorted(valid)} are defined"
                )
        return self

    @field_validator("columns")
    @classmethod
    def _unique_names(cls, v: list[Column]) -> list[Column]:
        names = [c.name for c in v]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"duplicate column names: {dupes}")
        return v

    def llm_columns(self) -> list[Column]:
        return [c for c in self.columns if c.kind in ("llm_text", "llm_code")]

    def estimate_llm_calls(self, num_records: int) -> int:
        return num_records * len(self.llm_columns())

    def hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]
