import React, { useState, useEffect, useCallback, useMemo } from "react";
import { createRoot } from "react-dom/client";

const h = React.createElement;

// Backend URL is same-origin when served from FastAPI, localhost:8765 in dev.
const API = window.location.port === "8765" ? "" : "http://localhost:8765";

// One API helper. Surfaces request_id from response headers/body so toast
// messages can include it - that's the debugging spine.
async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const rid = res.headers.get("X-Request-ID");
  if (!res.ok) {
    let body;
    try { body = await res.json(); } catch { body = { error: await res.text() }; }
    const detail = typeof body?.detail === "string" ? body.detail :
                   body?.detail?.message ? body.detail.message :
                   body?.error || res.statusText;
    const errs = body?.detail?.errors;
    const err = new Error(`${res.status}: ${detail}${rid ? ` [rid=${rid}]` : ""}`);
    err.status = res.status;
    err.requestId = rid;
    err.fieldErrors = errs;
    throw err;
  }
  return res.json();
}

// ---------- presentational helpers ----------
function Badge({ children, tone = "default" }) {
  const tones = {
    default: "bg-hp-graphite text-hp-mute border-hp-line",
    ok: "bg-hp-accent-dim/20 text-hp-accent border-hp-accent/40",
    warn: "bg-hp-warn/20 text-hp-warn border-hp-warn/40",
    danger: "bg-hp-danger/20 text-hp-danger border-hp-danger/40",
    hosted: "bg-blue-500/15 text-blue-400 border-blue-500/30",
    local: "bg-hp-accent-dim/20 text-hp-accent border-hp-accent/40",
  };
  return h("span", {
    className: `inline-flex items-center px-2 py-0.5 rounded border text-[11px] mono uppercase tracking-wider ${tones[tone] || tones.default}`,
  }, children);
}

function Button({ children, onClick, disabled, variant = "default", size = "md", title }) {
  const variants = {
    default: "bg-hp-graphite hover:bg-hp-line text-white border-hp-line",
    primary: "bg-hp-accent hover:bg-hp-accent/90 text-black border-hp-accent font-semibold",
    ghost: "bg-transparent hover:bg-hp-graphite text-hp-mute hover:text-white border-transparent",
    danger: "bg-transparent hover:bg-hp-danger/10 text-hp-danger border-hp-danger/40",
  };
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-1.5 text-sm", lg: "px-5 py-2.5 text-sm" };
  return h("button", {
    onClick, disabled, title,
    className: `inline-flex items-center justify-center rounded border transition-colors ${variants[variant]} ${sizes[size]} ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`,
  }, children);
}

function Field({ label, hint, children }) {
  return h("label", { className: "block" },
    h("div", { className: "flex items-baseline justify-between mb-1" },
      h("span", { className: "text-[11px] uppercase tracking-wider text-hp-mute mono" }, label),
      hint && h("span", { className: "text-[10px] text-hp-mute" }, hint),
    ),
    children,
  );
}

function Input(props) {
  return h("input", {
    ...props,
    className: `w-full bg-hp-charcoal border border-hp-line rounded px-2.5 py-1.5 text-sm focus:outline-none focus:border-hp-accent ${props.className || ""}`,
  });
}

function Textarea(props) {
  return h("textarea", {
    ...props,
    className: `w-full bg-hp-charcoal border border-hp-line rounded px-2.5 py-1.5 text-sm focus:outline-none focus:border-hp-accent mono ${props.className || ""}`,
  });
}

function Select({ value, onChange, options, className }) {
  return h("select", {
    value, onChange,
    className: `w-full bg-hp-charcoal border border-hp-line rounded px-2.5 py-1.5 text-sm focus:outline-none focus:border-hp-accent ${className || ""}`,
  }, options.map(o => h("option", { key: o.value, value: o.value }, o.label)));
}

// ---------- Toast ----------
const ToastContext = React.createContext(null);
function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((message, tone = "default", durationMs = 8000) => {
    const id = Math.random().toString(36).slice(2);
    setToasts(ts => [...ts, { id, message, tone }]);
    setTimeout(() => setToasts(ts => ts.filter(t => t.id !== id)), durationMs);
  }, []);
  return h(ToastContext.Provider, { value: push },
    children,
    h("div", { className: "fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-md" },
      toasts.map(t => h("div", {
        key: t.id,
        className: `px-4 py-2.5 rounded border text-sm shadow-lg whitespace-pre-line ${
          t.tone === "error" ? "bg-hp-danger/15 border-hp-danger/50 text-hp-danger" :
          t.tone === "warn"  ? "bg-hp-warn/15 border-hp-warn/50 text-hp-warn" :
          t.tone === "ok"    ? "bg-hp-accent-dim/20 border-hp-accent/50 text-hp-accent" :
          "bg-hp-graphite border-hp-line text-white"
        }`,
      }, t.message)),
    ),
  );
}
const useToast = () => React.useContext(ToastContext);

// ---------- Header ----------
function Header({ page, setPage, health }) {
  const tone = (s) => s === "healthy" ? "ok" : s === "unconfigured" ? "warn" : "danger";
  return h("header", { className: "border-b border-hp-line bg-hp-charcoal sticky top-0 z-40" },
    h("div", { className: "max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-6" },
      h("div", { className: "flex items-center gap-3" },
        h("img", {
          src: "logo_HP_Electric_Blue_keyline.png",
          alt: "HP",
          className: "h-8 w-auto",
        }),
        h("div", {},
          h("div", { className: "text-sm font-semibold tracking-tight" }, "Data Designer Studio"),
          h("div", { className: "text-[10px] text-hp-mute mono uppercase tracking-wider" }, "HP AI SOLUTIONS"),
        ),
      ),
      h("nav", { className: "flex items-center gap-1" },
        ["builder", "jobs", "preflight"].map(p => h("button", {
          key: p, onClick: () => setPage(p),
          className: `px-3 py-1.5 text-sm rounded transition-colors ${
            page === p ? "bg-hp-graphite text-white" : "text-hp-mute hover:text-white"
          }`,
        }, p.charAt(0).toUpperCase() + p.slice(1))),
      ),
      h("div", { className: "ml-auto flex items-center gap-3 text-[11px]" },
        h("span", { className: "text-hp-mute mono" }, "HOSTED"),
        h(Badge, { tone: tone(health?.hosted?.status) }, health?.hosted?.status || "…"),
        h("span", { className: "text-hp-mute mono ml-2" }, "LOCAL"),
        h(Badge, { tone: tone(health?.local?.status) }, health?.local?.status || "…"),
      ),
    ),
  );
}

// ---------- Budget panel (slimmer) ----------
function BudgetPanel({ mode, estCalls }) {
  const [snap, setSnap] = useState(null);
  useEffect(() => {
    let alive = true;
    const fetchIt = async () => {
      try {
        const data = await api(`/api/budget?mode=${mode}`);
        if (alive) setSnap(data);
      } catch {}
    };
    fetchIt();
    const iv = setInterval(fetchIt, 5000);
    return () => { alive = false; clearInterval(iv); };
  }, [mode]);

  if (!snap) return h("div", { className: "text-xs text-hp-mute mono" }, "loading…");

  return h("div", { className: "bg-hp-charcoal border border-hp-line rounded p-4 space-y-2" },
    h("div", { className: "text-[11px] uppercase tracking-wider text-hp-mute mono" }, "Today · " + mode),
    h("div", { className: "flex justify-between text-sm mono" },
      h("span", { className: "text-hp-mute" }, "Jobs run"),
      h("span", {}, snap.jobs_today),
    ),
    h("div", { className: "flex justify-between text-sm mono" },
      h("span", { className: "text-hp-mute" }, "LLM calls"),
      h("span", {}, snap.llm_calls_today),
    ),
    estCalls > 0 && h("div", { className: "pt-2 border-t border-hp-line text-[11px] mono space-y-1" },
      h("div", { className: "flex justify-between" },
        h("span", { className: "text-hp-mute" }, "THIS RUN (EST.)"),
        h("span", {}, `${estCalls} calls`),
      ),
      mode === "hosted" && estCalls > 40 && h("div", { className: "text-hp-warn" },
        `⚠ Exceeds NVIDIA's 40 RPM. Will pace ~${Math.ceil(estCalls / 40)} min.`,
      ),
    ),
    h("div", { className: "pt-2 border-t border-hp-line text-[10px] text-hp-mute italic" }, snap.note),
  );
}

// ---------- Column editor ----------
const SAMPLER_TYPES = [
  { value: "uuid", label: "UUID" },
  { value: "category", label: "Category (enum)" },
  { value: "uniform", label: "Uniform (range)" },
  { value: "gaussian", label: "Gaussian" },
  { value: "datetime", label: "Datetime range" },
  { value: "bernoulli", label: "Bernoulli (boolean)" },
  { value: "poisson", label: "Poisson (count)" },
  { value: "person", label: "Person (synthetic identity)" },
];

function ColumnEditor({ col, onChange, onDelete }) {
  const update = (patch) => onChange({ ...col, ...patch });
  const kindBadge = {
    sampler: { label: "SAMPLER", tone: "default" },
    llm_text: { label: "LLM · TEXT", tone: "hosted" },
    llm_code: { label: "LLM · CODE", tone: "hosted" },
    expression: { label: "EXPRESSION", tone: "default" },
  }[col.kind];

  return h("div", { className: "bg-hp-charcoal border border-hp-line rounded p-3 space-y-2" },
    h("div", { className: "flex items-center gap-2" },
      h(Badge, { tone: kindBadge.tone }, kindBadge.label),
      h(Input, {
        value: col.name,
        onChange: e => update({ name: e.target.value }),
        className: "mono flex-1",
      }),
      h(Button, { variant: "danger", size: "sm", onClick: onDelete }, "×"),
    ),
    col.kind === "sampler" && h("div", { className: "grid grid-cols-2 gap-2" },
      h(Field, { label: "Sampler type" },
        h(Select, {
          value: col.sampler_type,
          onChange: e => update({ sampler_type: e.target.value, params: {} }),
          options: SAMPLER_TYPES,
        }),
      ),
      h(Field, { label: "Params (JSON)" },
        h(Input, {
          value: JSON.stringify(col.params || {}),
          onChange: e => { try { update({ params: JSON.parse(e.target.value) }); } catch {} },
          className: "mono text-xs",
        }),
      ),
    ),
    (col.kind === "llm_text" || col.kind === "llm_code") && h(React.Fragment, {},
      // Model alias dropdown - lets users route this column to a specific model
      h("div", { className: "grid grid-cols-2 gap-2" },
        h(Field, { label: "Model alias", hint: "which model handles this column" },
          h(Select, {
            value: col.model_alias || "",
            onChange: e => update({ model_alias: e.target.value }),
            options: (window.__schemaModels || []).map(m => ({
              value: m.alias,
              label: `${m.alias} (${m.model_id?.split("/").pop() || m.model_id})`,
            })),
          }),
        ),
        h(Field, { label: "Max tokens override", hint: "blank = use model default" },
          h(Input, {
            type: "number", min: "0", step: "64",
            value: col.max_tokens ?? "",
            placeholder: "use model default",
            onChange: e => update({ max_tokens: e.target.value ? parseInt(e.target.value) : null }),
            className: "mono text-xs",
          }),
        ),
      ),
      h(Field, { label: "Prompt (Jinja)", hint: "Reference earlier columns as {{ column_name }}" },
        h(Textarea, { value: col.prompt || "", onChange: e => update({ prompt: e.target.value }), rows: 3 }),
      ),
      h(Field, { label: "System prompt", hint: "optional" },
        h(Textarea, {
          value: col.system_prompt || "",
          onChange: e => update({ system_prompt: e.target.value || null }), rows: 2,
        }),
      ),
      col.kind === "llm_code" && h(Field, { label: "Language" },
        h(Select, {
          value: col.language || "python",
          onChange: e => update({ language: e.target.value }),
          options: ["python", "javascript", "typescript", "sql", "bash", "go", "rust", "java"].map(l => ({ value: l, label: l })),
        }),
      ),
    ),
    col.kind === "expression" && h(Field, { label: "Jinja expression" },
      h(Input, {
        value: col.expression || "",
        onChange: e => update({ expression: e.target.value }),
        className: "mono",
        placeholder: "{{ first_name }} {{ last_name }}",
      }),
    ),
  );
}

// ---------- Preset picker ----------
function VerticalPicker({ onPick }) {
  const [presets, setPresets] = useState([]);
  useEffect(() => { api("/api/presets").then(r => setPresets(r.presets)).catch(() => {}); }, []);
  return h("div", { className: "space-y-4" },
    h("div", {},
      h("h2", { className: "text-xl font-semibold tracking-tight mb-1" }, "Start from a vertical preset"),
      h("p", { className: "text-sm text-hp-mute" }, "Pick a vertical to pre-populate the schema. Every field is editable."),
    ),
    h("div", { className: "grid grid-cols-2 lg:grid-cols-3 gap-3" },
      presets.map(p => h("button", {
        key: p.id, onClick: () => onPick(p.id),
        className: "text-left bg-hp-charcoal border border-hp-line hover:border-hp-accent rounded p-4 transition-colors",
      },
        h("div", { className: "flex items-start gap-3 mb-2" },
          h("div", { className: "text-2xl" }, p.icon),
          h("div", { className: "flex-1" },
            h("div", { className: "font-semibold text-white" }, p.name),
            h("div", { className: "text-xs text-hp-mute" }, p.tagline),
          ),
        ),
        p.demo_narrative && h("div", { className: "text-[11px] text-hp-mute italic border-l-2 border-hp-accent/40 pl-2 my-2" }, `"${p.demo_narrative}"`),
        h("div", { className: "text-[10px] mono uppercase tracking-wider text-hp-mute mt-2" }, `${p.column_count} columns`),
      )),
      h("button", {
        onClick: () => onPick(null),
        className: "text-left bg-hp-charcoal border border-dashed border-hp-line hover:border-hp-mute rounded p-4 transition-colors",
      },
        h("div", { className: "text-2xl mb-2" }, "⨯"),
        h("div", { className: "font-semibold text-white" }, "Start blank"),
        h("div", { className: "text-xs text-hp-mute" }, "Build a schema from scratch"),
      ),
    ),
  );
}

// ---------- Model selector (multi-model aware) ----------
// schema.models is a list. models[0] is the primary; the inputs at the top edit it.
// Additional models show as compact rows below. Each LLM column references a
// specific model by alias (handled in ColumnEditor).
function ModelSelector({ schema, onChange, models }) {
  const primary = schema.models[0];
  const others = schema.models.slice(1);

  // Resolve mode -> available model ids for the dropdown
  const modeForModel = (m) => m?.mode || "hosted";
  const modelOptions = (models?.[modeForModel(primary)] || []).map(m => ({
    value: m.id,
    label: `${m.label}${m.tags?.length ? " — " + m.tags.join(", ") : ""}`,
  }));

  const updatePrimary = (patch) => {
    const next = [...schema.models];
    next[0] = { ...primary, ...patch };
    onChange({ ...schema, models: next });
  };

  const updateOther = (idx, patch) => {
    // idx is 0-indexed within `others`, so real index is idx+1
    const next = [...schema.models];
    next[idx + 1] = { ...next[idx + 1], ...patch };
    onChange({ ...schema, models: next });
  };

  const removeOther = (idx) => {
    const next = schema.models.filter((_, i) => i !== idx + 1);
    onChange({ ...schema, models: next });
  };

  const addModel = () => {
    // Pick a unique alias
    const existing = new Set(schema.models.map(m => m.alias));
    let alias = "fast";
    let n = 2;
    while (existing.has(alias)) { alias = `model_${n++}`; }
    const newM = {
      mode: primary.mode === "local" ? "local_fast" : primary.mode,
      model_id: primary.model_id,
      alias,
      temperature: primary.temperature,
      top_p: primary.top_p,
      max_tokens: primary.max_tokens,
    };
    onChange({ ...schema, models: [...schema.models, newM] });
  };

  const modeBtn = (o, current, onPick) => h("button", {
    key: o.v,
    onClick: () => onPick(o.v),
    className: `px-3 py-2 rounded border text-sm transition-colors ${
      current === o.v
        ? (o.v === "hosted" ? "bg-blue-500/15 border-blue-500/40 text-blue-400"
           : o.v === "local_fast" ? "bg-amber-500/15 border-amber-500/40 text-amber-400"
           : "bg-hp-accent-dim/20 border-hp-accent/40 text-hp-accent")
        : "bg-hp-charcoal border-hp-line text-hp-mute hover:text-white"
    }`,
  }, o.label);

  return h("div", { className: "bg-hp-charcoal border border-hp-line rounded p-4 space-y-3" },
    h("div", { className: "flex items-center justify-between" },
      h("div", { className: "text-[11px] uppercase tracking-wider text-hp-mute mono" }, "Execution · primary"),
      h("span", { className: "text-[10px] mono text-hp-mute" }, `alias: ${primary.alias}`),
    ),
    h("div", { className: "grid grid-cols-3 gap-2" },
      [
        { v: "hosted",     label: "NVIDIA Hosted" },
        { v: "local",      label: "ZGX · Local" },
        { v: "local_fast", label: "ZGX · Fast" },
      ].map(o => modeBtn(o, primary.mode, (v) => {
        const targetMode = v === "local_fast" ? "local" : v;
        const firstModel = models?.[targetMode]?.[0]?.id;
        updatePrimary({ mode: v, model_id: firstModel || primary.model_id });
      })),
    ),
    h(Field, { label: "Model" },
      h(Select, {
        value: primary.model_id,
        onChange: e => updatePrimary({ model_id: e.target.value }),
        options: modelOptions.length ? modelOptions : [{ value: primary.model_id, label: primary.model_id + " (not loaded)" }],
      }),
    ),
    h("div", { className: "grid grid-cols-3 gap-2" },
      ["temperature", "top_p", "max_tokens"].map(k => h(Field, { key: k, label: k },
        h(Input, {
          type: "number",
          step: k === "max_tokens" ? "64" : "0.05",
          min: "0",
          value: primary[k],
          onChange: e => updatePrimary({ [k]: k === "max_tokens" ? (parseInt(e.target.value) || 1024) : parseFloat(e.target.value) }),
          className: "mono",
        }),
      )),
    ),

    // Secondary models section
    others.length > 0 && h("div", { className: "pt-3 border-t border-hp-line space-y-2" },
      h("div", { className: "text-[11px] uppercase tracking-wider text-hp-mute mono" },
        `Additional models · ${others.length}`),
      others.map((m, i) => h("div", {
        key: i,
        className: "border border-hp-line rounded p-2 space-y-2 bg-hp-graphite/30",
      },
        h("div", { className: "flex items-center gap-2" },
          h("span", { className: "text-[10px] mono text-hp-mute" }, "alias:"),
          h(Input, {
            value: m.alias,
            onChange: e => updateOther(i, { alias: e.target.value }),
            className: "mono text-xs flex-1 py-0.5",
          }),
          h(Button, { variant: "danger", size: "sm", onClick: () => removeOther(i) }, "×"),
        ),
        h("div", { className: "grid grid-cols-3 gap-1" },
          [
            { v: "hosted",     label: "Hosted" },
            { v: "local",      label: "Local" },
            { v: "local_fast", label: "Fast" },
          ].map(o => h("button", {
            key: o.v,
            onClick: () => {
              const firstModel = models?.[o.v]?.[0]?.id;
              updateOther(i, { mode: o.v, model_id: firstModel || m.model_id });
            },
            className: `px-2 py-1 rounded border text-[11px] transition-colors ${
              m.mode === o.v
                ? (o.v === "hosted" ? "bg-blue-500/15 border-blue-500/40 text-blue-400"
                   : o.v === "local_fast" ? "bg-amber-500/15 border-amber-500/40 text-amber-400"
                   : "bg-hp-accent-dim/20 border-hp-accent/40 text-hp-accent")
                : "bg-hp-charcoal border-hp-line text-hp-mute"
            }`,
          }, o.label)),
        ),
        h(Input, {
          value: m.model_id,
          onChange: e => updateOther(i, { model_id: e.target.value }),
          className: "mono text-xs",
          placeholder: "model id (e.g. Qwen/Qwen3-14B-AWQ)",
        }),
        h("div", { className: "grid grid-cols-3 gap-1" },
          ["temperature", "top_p", "max_tokens"].map(k => h(Field, { key: k, label: k.slice(0,4) },
            h(Input, {
              type: "number",
              step: k === "max_tokens" ? "64" : "0.05",
              min: "0",
              value: m[k],
              onChange: e => updateOther(i, { [k]: k === "max_tokens" ? (parseInt(e.target.value) || 1024) : parseFloat(e.target.value) }),
              className: "mono text-xs py-0.5",
            }),
          )),
        ),
      )),
    ),

    h(Button, { size: "sm", variant: "ghost", onClick: addModel }, "+ Add model alias"),
  );
}

// ---------- Results table ----------
function ResultsTable({ data }) {
  if (!data?.records?.length) return null;
  const cols = data.columns.filter(c => !c.endsWith("__trace") && !c.endsWith("__reasoning_content"));
  return h("div", { className: "bg-hp-charcoal border border-hp-line rounded overflow-hidden" },
    h("div", { className: "border-b border-hp-line px-4 py-2 flex items-center justify-between" },
      h("div", { className: "text-sm" }, `${data.num_records} records · ${cols.length} columns`),
      h("div", { className: "text-[11px] mono text-hp-mute" }, `${data.est_llm_calls} LLM calls · ${data.job_id}`),
    ),
    h("div", { className: "overflow-x-auto max-h-[500px]" },
      h("table", { className: "w-full text-sm" },
        h("thead", { className: "bg-hp-graphite sticky top-0" },
          h("tr", {}, cols.map(c => h("th", {
            key: c,
            className: "text-left px-3 py-2 text-[11px] mono uppercase tracking-wider text-hp-mute border-b border-hp-line",
          }, c))),
        ),
        h("tbody", {}, data.records.map((rec, i) => h("tr", {
          key: i, className: "border-b border-hp-line/50 hover:bg-hp-graphite/50",
        }, cols.map(c => h("td", {
          key: c, className: "px-3 py-2 align-top max-w-md",
        }, formatCell(rec[c])))))),
      ),
    ),
  );
}

function formatCell(v) {
  if (v === null || v === undefined) return h("span", { className: "text-hp-mute italic text-xs" }, "null");
  if (typeof v === "object") return h("pre", { className: "text-xs mono whitespace-pre-wrap" }, JSON.stringify(v, null, 2));
  const s = String(v);
  if (s.length > 200) return h("details", {}, h("summary", { className: "text-xs text-hp-mute cursor-pointer" }, `${s.slice(0, 180)}…`), h("div", { className: "text-xs mt-1" }, s));
  return s;
}

// ---------- Builder ----------
function BuilderPage({ models, onJobCreated }) {
  const toast = useToast();
  const [schema, setSchema] = useState(null);
  const [validation, setValidation] = useState(null);
  const [numRecords, setNumRecords] = useState(10);
  const [preview, setPreview] = useState(null);
  const [running, setRunning] = useState(false);

  const loadPreset = async (presetId) => {
    if (presetId) {
      try {
        const data = await api(`/api/presets/${presetId}`);
        setSchema(data.schema);
      } catch (e) { toast("Failed to load preset: " + e.message, "error"); }
    } else {
      setSchema({
        name: "untitled_dataset", description: "", vertical: null,
        models: [
          { mode: "hosted", model_id: "nvidia/nemotron-3-nano-30b-a3b", alias: "primary", temperature: 0.6, top_p: 0.95, max_tokens: 1024 },
        ],
        columns: [],
      });
    }
  };

  useEffect(() => {
    if (!schema) { setValidation(null); return; }
    let cancelled = false;
    api("/api/schema/validate", { method: "POST", body: JSON.stringify(schema) })
      .then(r => { if (!cancelled) setValidation(r); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [schema]);

  const estCalls = useMemo(() => {
    if (!schema) return 0;
    return schema.columns.filter(c => c.kind === "llm_text" || c.kind === "llm_code").length * numRecords;
  }, [schema, numRecords]);

  if (!schema) return h(VerticalPicker, { onPick: loadPreset });

  const addColumn = (kind) => {
    const base = { name: `col_${schema.columns.length + 1}`, drop: false, kind };
    let newCol;
    switch (kind) {
      case "sampler":
        newCol = { ...base, sampler_type: "category", params: { values: ["a", "b", "c"] } }; break;
      case "llm_text":
        newCol = { ...base, model_alias: schema.models[0].alias, prompt: "Write something." }; break;
      case "llm_code":
        newCol = { ...base, model_alias: schema.models[0].alias, prompt: "Write a function.", language: "python" }; break;
      case "expression":
        newCol = { ...base, expression: "{{ col_1 }}" }; break;
    }
    setSchema({ ...schema, columns: [...schema.columns, newCol] });
  };

  const updateCol = (i, c) => { const cs = [...schema.columns]; cs[i] = c; setSchema({ ...schema, columns: cs }); };
  const deleteCol = (i) => setSchema({ ...schema, columns: schema.columns.filter((_, j) => j !== i) });

  const runPreview = async () => {
    setRunning(true); setPreview(null);
    try {
      const result = await api(`/api/generate/preview?num_records=${Math.min(numRecords, 10)}`, {
        method: "POST", body: JSON.stringify(schema),
      });
      setPreview(result);
      toast(`Preview ready: ${result.num_records} records`, "ok");
    } catch (e) {
      const lines = [e.message];
      if (e.fieldErrors) lines.push("\n" + e.fieldErrors.map(s => "• " + s).join("\n"));
      toast("Preview failed:\n" + lines.join("\n"), "error", 12000);
    }
    finally { setRunning(false); }
  };

  const runCreate = async () => {
    setRunning(true);
    try {
      const result = await api(`/api/generate/create?num_records=${numRecords}`, {
        method: "POST", body: JSON.stringify(schema),
      });
      toast(`Job ${result.job_id} started · ${result.est_llm_calls} calls`, "ok");
      onJobCreated();
    } catch (e) {
      const lines = [e.message];
      if (e.fieldErrors) lines.push("\n" + e.fieldErrors.map(s => "• " + s).join("\n"));
      toast("Create failed:\n" + lines.join("\n"), "error", 12000);
    }
    finally { setRunning(false); }
  };

  return h("div", { className: "grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-6" },
    h("div", { className: "space-y-4" },
      h("div", { className: "flex items-end gap-3" },
        h("div", { className: "flex-1" },
          h(Field, { label: "Dataset name" },
            h(Input, { value: schema.name, onChange: e => setSchema({ ...schema, name: e.target.value }), className: "mono" }),
          ),
        ),
        h(Button, { variant: "ghost", size: "sm", onClick: () => setSchema(null) }, "← Change preset"),
      ),
      h("div", { className: "space-y-2" },
        h("div", { className: "flex items-center justify-between" },
          h("div", { className: "text-[11px] uppercase tracking-wider text-hp-mute mono" }, `Columns · ${schema.columns.length}`),
          h("div", { className: "flex gap-1" },
            h(Button, { size: "sm", onClick: () => addColumn("sampler") }, "+ Sampler"),
            h(Button, { size: "sm", onClick: () => addColumn("llm_text") }, "+ LLM Text"),
            h(Button, { size: "sm", onClick: () => addColumn("llm_code") }, "+ Code"),
            h(Button, { size: "sm", onClick: () => addColumn("expression") }, "+ Expression"),
          ),
        ),
        schema.columns.map((col, i) => h(ColumnEditor, {
          key: i, col,
          onChange: c => updateCol(i, c),
          onDelete: () => deleteCol(i),
        })),
        schema.columns.length === 0 && h("div", {
          className: "bg-hp-charcoal border border-dashed border-hp-line rounded p-8 text-center text-hp-mute text-sm",
        }, "No columns yet. Add one from the buttons above."),
      ),
    ),
    h("div", { className: "space-y-4" },
      h(ModelSelector, { schema, onChange: setSchema, models }),
      h(BudgetPanel, { mode: schema.models[0].mode === "local_fast" ? "local" : schema.models[0].mode, estCalls }),
      validation && h("div", { className: "bg-hp-charcoal border border-hp-line rounded p-4 space-y-2" },
        h("div", { className: "text-[11px] uppercase tracking-wider text-hp-mute mono" }, "Validation"),
        validation.valid
          ? h(Badge, { tone: "ok" }, "Schema valid")
          : h("div", { className: "space-y-1" },
              validation.errors.map((e, i) => h("div", { key: i, className: "text-xs text-hp-danger" }, "× " + e)),
            ),
        validation.warnings?.map((w, i) => h("div", { key: i, className: "text-xs text-hp-warn" }, "⚠ " + w)),
        h("div", { className: "pt-2 border-t border-hp-line text-[11px] mono text-hp-mute" },
          `${validation.summary.total_columns} cols · ${validation.summary.llm_columns} LLM · ${validation.summary.llm_calls_per_record} call/rec`,
        ),
      ),
      h("div", { className: "bg-hp-charcoal border border-hp-line rounded p-4 space-y-3" },
        h(Field, { label: "Records to generate", hint: "1-100" },
          h(Input, {
            type: "number", min: "1", max: "100",
            value: numRecords,
            onChange: e => setNumRecords(Math.max(1, Math.min(100, parseInt(e.target.value) || 1))),
            className: "mono",
          }),
        ),
        h("div", { className: "grid grid-cols-2 gap-2" },
          h(Button, { onClick: runPreview, disabled: running || !validation?.valid, size: "lg" },
            running ? "…" : "Preview (10)"),
          h(Button, { variant: "primary", onClick: runCreate, disabled: running || !validation?.valid, size: "lg" },
            running ? "…" : `Generate ${numRecords}`),
        ),
      ),
    ),
    preview && h("div", { className: "xl:col-span-2" }, h(ResultsTable, { data: preview })),
  );
}

// ---------- Jobs page ----------
function JobsPage() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const load = () => api("/api/jobs").then(r => { setJobs(r.jobs); setLoading(false); }).catch(() => setLoading(false));
    load();
    const iv = setInterval(load, 4000);
    return () => clearInterval(iv);
  }, []);
  if (loading) return h("div", { className: "text-hp-mute text-sm" }, "Loading jobs…");
  const tone = (s) => s === "complete" ? "ok" : s === "failed" ? "danger" : s === "running" ? "warn" : "default";
  return h("div", { className: "space-y-4" },
    h("h2", { className: "text-xl font-semibold tracking-tight" }, "Job history"),
    h("div", { className: "bg-hp-charcoal border border-hp-line rounded overflow-hidden" },
      h("table", { className: "w-full text-sm" },
        h("thead", { className: "bg-hp-graphite" },
          h("tr", {}, ["ID", "Schema", "Mode", "Model", "Records", "Calls", "Status", "Started", ""].map(c => h("th", {
            key: c,
            className: "text-left px-3 py-2 text-[11px] mono uppercase tracking-wider text-hp-mute border-b border-hp-line",
          }, c))),
        ),
        h("tbody", {}, jobs.length === 0
          ? h("tr", {}, h("td", { colSpan: 9, className: "px-3 py-6 text-center text-hp-mute" }, "No jobs yet"))
          : jobs.map(j => h("tr", { key: j.id, className: "border-b border-hp-line/50 hover:bg-hp-graphite/50" },
              h("td", { className: "px-3 py-2 mono text-xs" }, j.id),
              h("td", { className: "px-3 py-2" }, j.schema_name || "—"),
              h("td", { className: "px-3 py-2" }, h(Badge, { tone: j.mode === "local" ? "local" : "hosted" }, j.mode)),
              h("td", { className: "px-3 py-2 mono text-xs" }, (j.model || "").split("/").pop()),
              h("td", { className: "px-3 py-2 mono" }, j.num_records),
              h("td", { className: "px-3 py-2 mono" }, j.actual_llm_calls || j.est_llm_calls),
              h("td", { className: "px-3 py-2" }, h(Badge, { tone: tone(j.status) }, j.status)),
              h("td", { className: "px-3 py-2 text-xs text-hp-mute" },
                j.started_at ? new Date(j.started_at).toLocaleString() : "—"),
              h("td", { className: "px-3 py-2 text-right" },
                j.status === "complete" && h("a", {
                  href: `${API}/api/jobs/${j.id}/download?format=csv`,
                  className: "text-xs text-hp-accent hover:underline",
                }, "CSV"),
                " ",
                j.status === "complete" && h("a", {
                  href: `${API}/api/jobs/${j.id}/download?format=parquet`,
                  className: "text-xs text-hp-accent hover:underline ml-2",
                }, "Parquet"),
                j.status === "failed" && j.error && h("span", {
                  title: j.error,
                  className: "text-xs text-hp-danger cursor-help",
                }, "see error ↓"),
              ),
            )),
        ),
      ),
    ),
  );
}

// ---------- Preflight page ----------
function PreflightPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const refresh = async () => {
    setLoading(true);
    try { setData(await api("/api/health/detailed")); } catch (e) { setData({ overall: "error", error: e.message }); }
    finally { setLoading(false); }
  };
  useEffect(() => { refresh(); }, []);
  if (!data) return h("div", { className: "text-hp-mute text-sm" }, "Running checks…");

  const overallTone = data.overall === "ok" ? "ok" : data.overall === "warn" ? "warn" : "danger";
  const checkTone = (s) => s === "ok" ? "ok" : s === "warn" ? "warn" : "danger";

  return h("div", { className: "space-y-4 max-w-3xl" },
    h("div", { className: "flex items-center justify-between" },
      h("div", {},
        h("h2", { className: "text-xl font-semibold tracking-tight" }, "Pre-flight checks"),
        h("p", { className: "text-sm text-hp-mute mt-1" },
          "If everything below shows ok, the app will work. If something shows error, that's exactly what to fix."),
      ),
      h(Button, { onClick: refresh, disabled: loading }, loading ? "…" : "Re-check"),
    ),
    h("div", { className: "flex items-center gap-3" },
      h("div", { className: "text-sm font-medium" }, "Overall status:"),
      h(Badge, { tone: overallTone }, data.overall || "?"),
    ),
    h("div", { className: "space-y-2" },
      data.checks?.map((c, i) => h("div", {
        key: i,
        className: "bg-hp-charcoal border border-hp-line rounded p-3 flex items-start gap-3",
      },
        h(Badge, { tone: checkTone(c.status) }, c.status),
        h("div", { className: "flex-1" },
          h("div", { className: "text-sm" }, c.name),
          c.detail && h("div", { className: "text-xs text-hp-mute mono mt-1 whitespace-pre-line" }, c.detail),
          c.models_loaded?.length > 0 && h("div", { className: "text-[11px] mono text-hp-mute mt-1" },
            "Models: " + c.models_loaded.join(", ")),
        ),
      )),
    ),
  );
}

// ---------- Root ----------
function App() {
  const [page, setPage] = useState("builder");
  const [health, setHealth] = useState(null);
  const [models, setModels] = useState({ hosted: [], local: [], local_fast: [] });

  useEffect(() => {
    const load = async () => {
      try { setHealth(await api("/api/health")); } catch {}
      try { setModels(await api("/api/models")); } catch {}
    };
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, []);

  return h(ToastProvider, {},
    h("div", { className: "min-h-screen" },
      h(Header, { page, setPage, health }),
      h("main", { className: "max-w-[1600px] mx-auto px-6 py-6" },
        page === "builder" && h(BuilderPage, { models, onJobCreated: () => setPage("jobs") }),
        page === "jobs" && h(JobsPage, {}),
        page === "preflight" && h(PreflightPage, {}),
      ),
    ),
  );
}

createRoot(document.getElementById("root")).render(h(App));
