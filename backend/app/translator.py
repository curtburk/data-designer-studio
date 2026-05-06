"""Translate SchemaSpec → DataDesigner config objects.

v0.1.2: handles multiple ModelChoices in schema.models, plus per-column
max_tokens overrides via synthesized variant aliases.
"""
from typing import Any

from data_designer.config.column_configs import (
    ExpressionColumnConfig, LLMCodeColumnConfig,
    LLMTextColumnConfig, SamplerColumnConfig,
)
from data_designer.config.column_types import SamplerType as DDSamplerType
from data_designer.config.config_builder import DataDesignerConfigBuilder
from data_designer.config.models import ChatCompletionInferenceParams, ModelConfig
from data_designer.config.sampler_params import (
    BernoulliSamplerParams, CategorySamplerParams, DatetimeSamplerParams,
    GaussianSamplerParams, PersonSamplerParams, PoissonSamplerParams,
    SubcategorySamplerParams, UniformSamplerParams, UUIDSamplerParams,
)

from .schema_spec import Column, ModelChoice, SchemaSpec

_SAMPLER_MAP = {
    "uuid":        (DDSamplerType.UUID,        UUIDSamplerParams),
    "category":    (DDSamplerType.CATEGORY,    CategorySamplerParams),
    "subcategory": (DDSamplerType.SUBCATEGORY, SubcategorySamplerParams),
    "uniform":     (DDSamplerType.UNIFORM,     UniformSamplerParams),
    "gaussian":    (DDSamplerType.GAUSSIAN,    GaussianSamplerParams),
    "person":      (DDSamplerType.PERSON,      PersonSamplerParams),
    "datetime":    (DDSamplerType.DATETIME,    DatetimeSamplerParams),
    "bernoulli":   (DDSamplerType.BERNOULLI,   BernoulliSamplerParams),
    "poisson":     (DDSamplerType.POISSON,     PoissonSamplerParams),
}


def _provider_name(mode: str) -> str:
    if mode == "hosted":
        return "nvidia-hosted"
    if mode == "local_fast":
        return "zgx-local-fast"
    return "zgx-local"


def _build_model_configs(schema: SchemaSpec):
    configs: list[ModelConfig] = []
    column_alias_map: dict[str, str] = {}
    by_alias: dict[str, ModelChoice] = {m.alias: m for m in schema.models}

    for mc in schema.models:
        configs.append(ModelConfig(
            alias=mc.alias, model=mc.model_id, provider=_provider_name(mc.mode),
            inference_parameters=ChatCompletionInferenceParams(
                temperature=mc.temperature, top_p=mc.top_p, max_tokens=mc.max_tokens,
            ),
        ))

    seen_variants: set[str] = set()
    for col in schema.columns:
        if col.kind not in ("llm_text", "llm_code"):
            continue
        base_mc = by_alias.get(col.model_alias)
        if base_mc is None:
            continue
        if col.max_tokens is None or col.max_tokens == base_mc.max_tokens:
            column_alias_map[col.name] = base_mc.alias
            continue
        variant_alias = f"{base_mc.alias}__mt{col.max_tokens}"
        column_alias_map[col.name] = variant_alias
        if variant_alias in seen_variants:
            continue
        seen_variants.add(variant_alias)
        configs.append(ModelConfig(
            alias=variant_alias, model=base_mc.model_id, provider=_provider_name(base_mc.mode),
            inference_parameters=ChatCompletionInferenceParams(
                temperature=base_mc.temperature, top_p=base_mc.top_p, max_tokens=col.max_tokens,
            ),
        ))

    return configs, column_alias_map


def _build_column(col: Column, column_alias_map: dict[str, str]) -> Any:
    if col.kind == "sampler":
        dd_type, params_cls = _SAMPLER_MAP[col.sampler_type]
        kwargs = {
            "name": col.name, "sampler_type": dd_type,
            "params": params_cls(**col.params), "drop": col.drop,
        }
        if col.convert_to:
            kwargs["convert_to"] = col.convert_to
        return SamplerColumnConfig(**kwargs)

    if col.kind == "llm_text":
        eff = column_alias_map.get(col.name, col.model_alias)
        return LLMTextColumnConfig(
            name=col.name, drop=col.drop, model_alias=eff,
            prompt=col.prompt, system_prompt=col.system_prompt,
        )

    if col.kind == "llm_code":
        eff = column_alias_map.get(col.name, col.model_alias)
        return LLMCodeColumnConfig(
            name=col.name, drop=col.drop, model_alias=eff,
            prompt=col.prompt, system_prompt=col.system_prompt,
            code_lang=col.language or "python",
        )

    if col.kind == "expression":
        return ExpressionColumnConfig(name=col.name, drop=col.drop, expr=col.expression)

    raise ValueError(f"unknown column kind: {col.kind}")


def build_config_builder(schema: SchemaSpec) -> DataDesignerConfigBuilder:
    model_configs, column_alias_map = _build_model_configs(schema)
    builder = DataDesignerConfigBuilder(model_configs=model_configs)
    for col in schema.columns:
        builder.add_column(_build_column(col, column_alias_map))
    return builder


def validate_schema(schema: SchemaSpec) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not schema.columns:
        errors.append("schema has no columns")

    import re
    var_pattern = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[}|]")
    defined: set[str] = set()
    for col in schema.columns:
        for ref in (col.prompt, col.system_prompt, col.expression):
            if not ref:
                continue
            for var in var_pattern.findall(ref):
                if var not in defined:
                    errors.append(
                        f"column '{col.name}' references '{{{{ {var} }}}}' "
                        f"which is not defined yet"
                    )
        defined.add(col.name)

    if not errors:
        try:
            build_config_builder(schema)
        except Exception as e:
            errors.append(f"build failed: {e}")

    llm_cols = len(schema.llm_columns())
    if llm_cols > 5:
        warnings.append(f"{llm_cols} LLM columns per record will burn credits quickly")

    for col in schema.llm_columns():
        if col.max_tokens is None:
            base = next((m for m in schema.models if m.alias == col.model_alias), None)
            if base and base.max_tokens >= 1024:
                warnings.append(
                    f"column '{col.name}' has no max_tokens override; uses "
                    f"model default of {base.max_tokens}. Consider tightening."
                )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "total_columns": len(schema.columns),
            "llm_columns": llm_cols,
            "llm_calls_per_record": llm_cols,
            "llm_calls_per_100_records": llm_cols * 100,
            "models_used": sorted({c.model_alias for c in schema.llm_columns() if c.model_alias}),
        },
    }
