#!/usr/bin/env bash
# =============================================================================
#  Data Designer Studio - Start Script
#
#  Brings up the Studio backend + (optionally) a local vLLM serving model.
#  Designed to be re-runnable: idempotent vLLM container (reuses if healthy),
#  detached Studio container (survives script exit), auto-detects host IP.
#
#  Usage:
#    ./start.sh                # full start: preflight + vLLM + Studio
#    ./start.sh --skip-vllm    # Studio only (hosted-mode demos)
#    ./start.sh --help
#
#  Environment overrides (all optional):
#    VLLM_IMAGE          default: vllm/vllm-openai:latest
#    VLLM_MODEL          default: Qwen/Qwen3-32B-AWQ
#    VLLM_QUANT          default: awq_marlin       (use "" to disable)
#    VLLM_PORT           default: 8090             (host-side port)
#    VLLM_EXTRA_ARGS     default: ""               (extra args to vllm serve)
#    HF_CACHE            default: ~/.cache/huggingface
#    HF_TOKEN            (passed through if set)
#    HOST_IP             default: auto-detected
# =============================================================================
set -e

# ── Defaults (overridable via env) ──────────────────────────────────────────

VLLM_CONTAINER_NAME="${VLLM_CONTAINER_NAME:-ddstudio-vllm}"
VLLM_IMAGE="${VLLM_IMAGE:-vllm/vllm-openai:latest}"
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3-32B-AWQ}"
VLLM_QUANT="${VLLM_QUANT:-awq_marlin}"
VLLM_PORT="${VLLM_PORT:-8090}"
# Bound 32B's memory so the fast 14B has room (unified memory shared on GB10).
# Default 0.55 = ~65 GB for 32B, leaving ~42 GB for 14B + headroom.
# If running 32B alone (VLLM_FAST_ENABLED=false), bump this to 0.9 for headroom.
VLLM_GPU_MEM="${VLLM_GPU_MEM:-0.55}"
VLLM_EXTRA_ARGS="${VLLM_EXTRA_ARGS:-}"

# Optional second vLLM for the smaller/faster model. Used for healthcare's
# 'fast' alias and as the default for non-healthcare presets.
VLLM_FAST_ENABLED="${VLLM_FAST_ENABLED:-true}"
VLLM_FAST_CONTAINER_NAME="${VLLM_FAST_CONTAINER_NAME:-ddstudio-vllm-fast}"
VLLM_FAST_MODEL="${VLLM_FAST_MODEL:-Qwen/Qwen3-14B-AWQ}"
VLLM_FAST_PORT="${VLLM_FAST_PORT:-8091}"
VLLM_FAST_GPU_MEM="${VLLM_FAST_GPU_MEM:-0.35}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
APP_PORT="${APP_PORT:-8765}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Flag parsing ────────────────────────────────────────────────────────────

SKIP_VLLM=false
for arg in "$@"; do
    case "$arg" in
        --skip-vllm)    SKIP_VLLM=true ;;
        --help|-h)
            sed -n '2,/^# =====/p' "$0" | sed 's/^#//; s/^ //'
            exit 0
            ;;
        *)
            echo "Unknown flag: $arg (try --help)"
            exit 1
            ;;
    esac
done

# ── Pretty-print helpers ────────────────────────────────────────────────────

ok()   { printf '  \033[0;32m[OK]\033[0m   %s\n' "$*"; }
info() { printf '  \033[0;36m[INFO]\033[0m %s\n' "$*"; }
warn() { printf '  \033[0;33m[WARN]\033[0m %s\n' "$*"; }
fail() { printf '  \033[0;31m[FAIL]\033[0m %s\n' "$*"; exit 1; }
hdr()  { printf '\n\033[1m==============================================\n  %s\n==============================================\033[0m\n\n' "$*"; }

# ── Pre-flight checks ───────────────────────────────────────────────────────

hdr "Data Designer Studio - Preflight"

# Docker daemon
docker info &>/dev/null || fail "Docker daemon not running. Try: sudo systemctl start docker"
ok "Docker daemon up"

# Docker compose (v2 plugin syntax)
docker compose version &>/dev/null || fail "docker compose plugin missing. Install with: sudo apt install docker-compose-plugin"
ok "docker compose available"

# NVIDIA GPU (only required if running vLLM)
if [ "$SKIP_VLLM" = false ]; then
    nvidia-smi &>/dev/null || fail "NVIDIA GPU not visible. Check 'nvidia-smi' on the host."
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    ok "GPU detected: $GPU_NAME"

    # Check available memory before trying to load a 32B model
    FREE_MEM_GIB=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 | awk '{print int($1/1024)}')
    if [ -n "$FREE_MEM_GIB" ] && [ "$FREE_MEM_GIB" -lt 30 ]; then
        warn "Only ${FREE_MEM_GIB} GiB GPU memory free. ${VLLM_MODEL} may not fit."
        warn "Run 'nvidia-smi' and stop any unused containers before retrying."
        warn "If vLLM fails to start, that's why."
    else
        ok "GPU memory: ~${FREE_MEM_GIB:-?} GiB free"
    fi

    # vLLM image present (or pull it)
    if docker image inspect "$VLLM_IMAGE" &>/dev/null; then
        ok "vLLM image cached: $VLLM_IMAGE"
    else
        info "Pulling $VLLM_IMAGE (one-time, ~5 GiB)..."
        docker pull "$VLLM_IMAGE" || fail "Could not pull $VLLM_IMAGE"
        ok "vLLM image pulled"
    fi
fi

# Studio compose file
if [ ! -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    fail "docker-compose.yml not found in $SCRIPT_DIR. Run from project root."
fi
ok "Studio compose file present"

# .env handling - auto-seed from .example if missing
if [ ! -f "$SCRIPT_DIR/backend/.env" ]; then
    if [ -f "$SCRIPT_DIR/backend/.env.example" ]; then
        cp "$SCRIPT_DIR/backend/.env.example" "$SCRIPT_DIR/backend/.env"
        warn "Created backend/.env from .env.example"
        warn "Edit backend/.env to set NVIDIA_API_KEY (hosted mode won't work without it)"
    else
        fail "Neither backend/.env nor backend/.env.example exists. Cannot continue."
    fi
fi

# Sanity-check the API key value (warn but don't block - local mode works without)
if grep -qE '^NVIDIA_API_KEY=(nvapi-REPLACE_ME|)\s*$' "$SCRIPT_DIR/backend/.env"; then
    warn "NVIDIA_API_KEY is unset or placeholder. Hosted mode will be unavailable."
    warn "  Edit backend/.env and set NVIDIA_API_KEY=nvapi-... to enable hosted demos."
else
    ok "NVIDIA_API_KEY appears configured"
fi

# Make sure LOCAL_VLLM_URL points where we'll be serving (only if running vLLM)
if [ "$SKIP_VLLM" = false ]; then
    EXPECTED_URL="http://host.docker.internal:${VLLM_PORT}/v1"
    if ! grep -qE "^LOCAL_VLLM_URL=${EXPECTED_URL}$" "$SCRIPT_DIR/backend/.env"; then
        warn "LOCAL_VLLM_URL in backend/.env doesn't match the port we're serving on (${VLLM_PORT})."
        warn "  Expected: LOCAL_VLLM_URL=${EXPECTED_URL}"
        warn "  Current:  $(grep '^LOCAL_VLLM_URL=' "$SCRIPT_DIR/backend/.env" || echo '<unset>')"
        warn "  Fix this in backend/.env or local mode won't connect."
    else
        ok "LOCAL_VLLM_URL matches vLLM port"
    fi
fi

ok "All preflight checks passed"

# ── Detect other vLLM containers that might conflict ────────────────────────

if [ "$SKIP_VLLM" = false ]; then
    OTHER_VLLM=$(docker ps --format '{{.Names}}\t{{.Image}}' | grep -E 'vllm|VLLM' | grep -v "^${VLLM_CONTAINER_NAME}\b" || true)
    if [ -n "$OTHER_VLLM" ]; then
        echo ""
        warn "Other vLLM-like containers are running. They will share GPU memory."
        warn "If $VLLM_MODEL doesn't fit, stop them first:"
        echo "$OTHER_VLLM" | sed 's/^/         /'
        echo ""
    fi
fi

# ── Start or reuse vLLM ─────────────────────────────────────────────────────

if [ "$SKIP_VLLM" = true ]; then
    hdr "Skipping vLLM (--skip-vllm). Local mode will be unavailable."
else
    VLLM_RUNNING=false

    if docker ps --format '{{.Names}}' | grep -q "^${VLLM_CONTAINER_NAME}$"; then
        if curl -sf "http://localhost:${VLLM_PORT}/v1/models" &>/dev/null; then
            hdr "vLLM already healthy - reusing existing container"
            VLLM_RUNNING=true
        else
            warn "$VLLM_CONTAINER_NAME exists but isn't responding. Recreating..."
            docker rm -f "$VLLM_CONTAINER_NAME" &>/dev/null
        fi
    elif docker ps -a --format '{{.Names}}' | grep -q "^${VLLM_CONTAINER_NAME}$"; then
        info "Removing stale stopped container $VLLM_CONTAINER_NAME..."
        docker rm -f "$VLLM_CONTAINER_NAME" &>/dev/null
    fi

    if [ "$VLLM_RUNNING" = false ]; then
        hdr "Starting vLLM ($VLLM_MODEL)"

        echo "  First-time model load: 5-10 min for download + CUDA compilation"
        echo "  Subsequent starts: ~30 sec (model cached, graphs precompiled)"
        echo "  Tip: leave this container running between Studio restarts"
        echo ""

        # Build the vllm serve args from our config
        VLLM_ARGS=(--model "$VLLM_MODEL")
        if [ -n "$VLLM_QUANT" ]; then
            VLLM_ARGS+=(--quantization "$VLLM_QUANT")
        fi
        VLLM_ARGS+=(--port 8000)
        VLLM_ARGS+=(--gpu-memory-utilization "$VLLM_GPU_MEM")
        # Reasoning parser strips Qwen3 <think> blocks from response.content.
        # Chat template kwargs disables thinking generation entirely - the right
        # behavior for synthetic data where we want the answer, not the reasoning.
        # Passed as separate array elements so no shell-quoting fight with the JSON.
        VLLM_ARGS+=(--reasoning-parser qwen3)
        VLLM_ARGS+=(--default-chat-template-kwargs '{"enable_thinking": false}')
        # Append any user-provided extras (split on whitespace, no quoting magic)
        if [ -n "$VLLM_EXTRA_ARGS" ]; then
            # shellcheck disable=SC2206
            VLLM_ARGS+=($VLLM_EXTRA_ARGS)
        fi

        DOCKER_ARGS=(
            -d
            --gpus all
            --name "$VLLM_CONTAINER_NAME"
            --restart unless-stopped
            -v "$HF_CACHE:/root/.cache/huggingface"
            -p "${VLLM_PORT}:8000"
            --ipc=host
        )
        if [ -n "${HF_TOKEN:-}" ]; then
            DOCKER_ARGS+=(-e "HF_TOKEN=$HF_TOKEN")
        fi

        docker run "${DOCKER_ARGS[@]}" "$VLLM_IMAGE" "${VLLM_ARGS[@]}" > /dev/null
        info "Container started: $VLLM_CONTAINER_NAME"
        echo ""

        # Health-poll. vLLM doesn't expose /health, but /v1/models works once ready.
        ATTEMPTS=0
        MAX_ATTEMPTS=180  # 15 min max; a 32B model on cold cache can be slow
        echo -n "  Loading"
        while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
            if curl -sf "http://localhost:${VLLM_PORT}/v1/models" &>/dev/null; then
                echo ""
                ok "vLLM is serving on port $VLLM_PORT"
                break
            fi
            ATTEMPTS=$((ATTEMPTS + 1))
            ELAPSED=$((ATTEMPTS * 5))

            if [ $((ATTEMPTS % 6)) -eq 0 ]; then
                echo -n " ${ELAPSED}s"
            else
                echo -n "."
            fi

            # Check if container died early
            if ! docker ps --format '{{.Names}}' | grep -q "^${VLLM_CONTAINER_NAME}$"; then
                echo ""
                fail "vLLM container exited unexpectedly. Logs: docker logs $VLLM_CONTAINER_NAME"
            fi

            sleep 5
        done

        if [ $ATTEMPTS -ge $MAX_ATTEMPTS ]; then
            echo ""
            fail "vLLM did not become healthy in 15 minutes. Logs: docker logs $VLLM_CONTAINER_NAME"
        fi
    fi
fi

# ── Start Studio (always rebuild on changes) ────────────────────────────────


# ── Optionally start the 'fast' vLLM container ─────────────────────────────
if [ "$SKIP_VLLM" = false ] && [ "$VLLM_FAST_ENABLED" = "true" ]; then
    FAST_RUNNING=false
    if docker ps --format '{{.Names}}' | grep -q "^${VLLM_FAST_CONTAINER_NAME}$"; then
        if curl -sf "http://localhost:${VLLM_FAST_PORT}/v1/models" &>/dev/null; then
            hdr "Fast vLLM already healthy - reusing"
            FAST_RUNNING=true
        else
            warn "${VLLM_FAST_CONTAINER_NAME} exists but not responding. Recreating..."
            docker rm -f "$VLLM_FAST_CONTAINER_NAME" &>/dev/null
        fi
    elif docker ps -a --format '{{.Names}}' | grep -q "^${VLLM_FAST_CONTAINER_NAME}$"; then
        docker rm -f "$VLLM_FAST_CONTAINER_NAME" &>/dev/null
    fi

    if [ "$FAST_RUNNING" = false ]; then
        hdr "Starting fast vLLM (${VLLM_FAST_MODEL})"
        echo "  Memory utilization: ${VLLM_FAST_GPU_MEM} (bounded so 32B has room)"
        echo ""

        FAST_DOCKER_ARGS=(
            -d --gpus all
            --name "$VLLM_FAST_CONTAINER_NAME"
            --restart unless-stopped
            -v "$HF_CACHE:/root/.cache/huggingface"
            -p "${VLLM_FAST_PORT}:8000"
            --ipc=host
        )
        if [ -n "${HF_TOKEN:-}" ]; then
            FAST_DOCKER_ARGS+=(-e "HF_TOKEN=$HF_TOKEN")
        fi

        FAST_VLLM_ARGS=(
            --model "$VLLM_FAST_MODEL"
            --quantization awq_marlin
            --port 8000
            --gpu-memory-utilization "$VLLM_FAST_GPU_MEM"
            --max-model-len 8192
            --reasoning-parser qwen3
            --default-chat-template-kwargs '{"enable_thinking": false}'
        )

        docker run "${FAST_DOCKER_ARGS[@]}" "$VLLM_IMAGE" "${FAST_VLLM_ARGS[@]}" > /dev/null
        info "fast vLLM container started"

        echo -n "  Loading"
        ATTEMPTS=0
        while [ $ATTEMPTS -lt 60 ]; do
            if curl -sf "http://localhost:${VLLM_FAST_PORT}/v1/models" &>/dev/null; then
                echo ""
                ok "fast vLLM serving on port $VLLM_FAST_PORT"
                break
            fi
            ATTEMPTS=$((ATTEMPTS + 1))
            echo -n "."
            if ! docker ps --format '{{.Names}}' | grep -q "^${VLLM_FAST_CONTAINER_NAME}$"; then
                echo ""
                warn "fast vLLM exited. Logs: docker logs $VLLM_FAST_CONTAINER_NAME"
                warn "Continuing without fast vLLM. Healthcare preset will fall back to 32B."
                break
            fi
            sleep 5
        done
    fi
fi

hdr "Starting Studio"

cd "$SCRIPT_DIR"
docker compose up -d --build 2>&1 | grep -vE '^WARN.*version.*obsolete' || true
ok "Studio container up"

# Health-poll Studio
ATTEMPTS=0
while [ $ATTEMPTS -lt 30 ]; do
    if curl -sf "http://localhost:${APP_PORT}/api/health" &>/dev/null; then
        ok "Studio is responding on port $APP_PORT"
        break
    fi
    ATTEMPTS=$((ATTEMPTS + 1))
    sleep 1
done

if [ $ATTEMPTS -ge 30 ]; then
    warn "Studio did not respond in 30 seconds. Check logs:"
    warn "  docker compose logs -f ddstudio"
fi

# ── Detect host LAN IP for the friendly URL ────────────────────────────────

if [ -z "${HOST_IP:-}" ]; then
    HOST_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
fi
if [ -z "$HOST_IP" ]; then
    HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
if [ -z "$HOST_IP" ]; then
    HOST_IP="localhost"
fi

# ── Final status & next steps ───────────────────────────────────────────────

hdr "Data Designer Studio is up"

cat <<EOF
  UI:       http://${HOST_IP}:${APP_PORT}/app/
  Preflight check:  http://${HOST_IP}:${APP_PORT}/api/health/detailed
  API docs: http://${HOST_IP}:${APP_PORT}/docs

  First-stop: open the UI and click the "Preflight" tab. Five green
  rows means everything is wired correctly.

EOF

if [ "$SKIP_VLLM" = false ]; then
    cat <<EOF
  Local model: ${VLLM_MODEL}
  vLLM logs:   docker logs -f ${VLLM_CONTAINER_NAME}
  Stop vLLM:   docker stop ${VLLM_CONTAINER_NAME}

EOF
fi

cat <<EOF
  Studio logs: cd $SCRIPT_DIR && docker compose logs -f ddstudio
  Stop Studio: cd $SCRIPT_DIR && docker compose down

  Both Studio and vLLM run detached. Closing this terminal does not
  stop them. Re-run this script anytime to verify and rebuild.
EOF