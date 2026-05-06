#!/usr/bin/env bash
#
# deploy.sh - one-shot deploy of Data Designer Studio to the ZGX Nano
#
# Run from your dev machine. Requires ssh + scp access to the Nano.
# Safe to re-run: re-deploy is idempotent (updates in place, preserves DB and
# artifacts in the named docker volume).
#
# Usage:
#   ./deploy.sh                    # defaults: curtis@192.168.10.123
#   ./deploy.sh user@other.host    # override target
#   NVIDIA_API_KEY=nvapi-... ./deploy.sh   # pass key inline (optional)

set -euo pipefail

# ---------- config ----------
TARGET="${1:-curtis@192.168.10.123}"
REMOTE_DIR="data-designer-studio"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARBALL="/tmp/ddstudio-deploy-$(date +%s).tar.gz"
NANO_PORT=8765

# ---------- pretty logging ----------
log()  { printf '\033[0;36m[deploy]\033[0m %s\n' "$*"; }
ok()   { printf '\033[0;32m[ok]\033[0m     %s\n' "$*"; }
warn() { printf '\033[0;33m[warn]\033[0m   %s\n' "$*" >&2; }
die()  { printf '\033[0;31m[fail]\033[0m   %s\n' "$*" >&2; exit 1; }

# ---------- preflight ----------
log "target:  $TARGET"
log "source:  $PROJECT_DIR"

[[ -f "$PROJECT_DIR/docker-compose.yml" ]] || die "not a project root (no docker-compose.yml). Run from data-designer-studio/."
[[ -f "$PROJECT_DIR/Dockerfile" ]]         || die "Dockerfile missing"
[[ -d "$PROJECT_DIR/backend" ]]            || die "backend/ missing"
[[ -d "$PROJECT_DIR/frontend" ]]           || die "frontend/ missing"
[[ -d "$PROJECT_DIR/presets" ]]            || die "presets/ missing"

command -v ssh >/dev/null || die "ssh not installed"
command -v scp >/dev/null || die "scp not installed"

log "ssh check..."
ssh -o BatchMode=yes -o ConnectTimeout=5 "$TARGET" "echo connected" >/dev/null 2>&1 \
  || die "cannot ssh to $TARGET. Is your key in ~/.ssh/authorized_keys on the Nano?"
ok "ssh reachable"

log "remote docker check..."
ssh "$TARGET" "command -v docker && docker compose version" >/dev/null 2>&1 \
  || die "docker or docker compose plugin not installed on $TARGET"
ok "docker + compose present"

# ---------- package ----------
log "building tarball (excluding .venv, __pycache__, .git, artifacts)..."
tar czf "$TARBALL" \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='*.pyc' \
  --exclude='/tmp/ddstudio_*' \
  -C "$(dirname "$PROJECT_DIR")" \
  "$(basename "$PROJECT_DIR")"
TAR_SIZE=$(du -h "$TARBALL" | cut -f1)
ok "packaged: $TARBALL ($TAR_SIZE)"

# ---------- copy ----------
log "copying to $TARGET:~/..."
scp -q "$TARBALL" "$TARGET:/tmp/ddstudio-deploy.tar.gz"
rm -f "$TARBALL"
ok "copied"

# ---------- extract + configure + start (on the Nano) ----------
log "extracting and (re)starting on remote..."
# Pass the local NVIDIA_API_KEY env if set; otherwise the remote will reuse
# whatever is already in .env on the Nano (preserved across deploys).
REMOTE_SCRIPT=$(cat <<REMOTE_EOF
set -euo pipefail

# Preserve existing .env across redeploys
STASHED_ENV=""
if [[ -f ~/${REMOTE_DIR}/backend/.env ]]; then
    STASHED_ENV=\$(mktemp)
    cp ~/${REMOTE_DIR}/backend/.env "\$STASHED_ENV"
    echo "[remote] preserved existing backend/.env"
fi

# Extract fresh copy
mkdir -p ~/${REMOTE_DIR}
tar xzf /tmp/ddstudio-deploy.tar.gz -C ~/ --strip-components=0
rm /tmp/ddstudio-deploy.tar.gz
echo "[remote] extracted to ~/${REMOTE_DIR}"

# Restore stashed .env if we had one, otherwise seed from example
if [[ -n "\$STASHED_ENV" ]]; then
    cp "\$STASHED_ENV" ~/${REMOTE_DIR}/backend/.env
    rm "\$STASHED_ENV"
    echo "[remote] restored existing backend/.env"
else
    cp ~/${REMOTE_DIR}/backend/.env.example ~/${REMOTE_DIR}/backend/.env
    # Default LOCAL_VLLM_URL to host.docker.internal for Docker-on-same-host vLLM
    sed -i 's|^LOCAL_VLLM_URL=.*|LOCAL_VLLM_URL=http://host.docker.internal:8090/v1|' \
        ~/${REMOTE_DIR}/backend/.env
    echo "[remote] seeded fresh backend/.env (edit to set NVIDIA_API_KEY)"
fi

# If the local environment passed NVIDIA_API_KEY, write it now (single-line sed
# pattern per Curtis's convention — fits exactly on one line for reliable sed)
if [[ -n "\${NVIDIA_API_KEY:-}" ]]; then
    sed -i "s|^NVIDIA_API_KEY=.*|NVIDIA_API_KEY=\${NVIDIA_API_KEY}|" \
        ~/${REMOTE_DIR}/backend/.env
    echo "[remote] applied NVIDIA_API_KEY from deploy environment"
fi

# Build + start
cd ~/${REMOTE_DIR}
echo "[remote] docker compose up -d --build (first run: ~3-4 min)"
docker compose up -d --build

# Wait for healthy
echo "[remote] waiting for healthcheck..."
for i in \$(seq 1 30); do
    if curl -fs http://localhost:${NANO_PORT}/api/health >/dev/null 2>&1; then
        echo "[remote] healthy after \${i}*2s"
        break
    fi
    sleep 2
    if [[ \$i -eq 30 ]]; then
        echo "[remote] service did not become healthy in 60s"
        docker compose logs --tail=50 ddstudio
        exit 1
    fi
done

# Final status
echo ""
echo "--- health ---"
curl -s http://localhost:${NANO_PORT}/api/health | python3 -m json.tool || true
echo ""
echo "--- containers ---"
docker compose ps
REMOTE_EOF
)

# Forward NVIDIA_API_KEY to remote if set locally
if [[ -n "${NVIDIA_API_KEY:-}" ]]; then
    ssh "$TARGET" "NVIDIA_API_KEY='$NVIDIA_API_KEY' bash -s" <<< "$REMOTE_SCRIPT"
else
    ssh "$TARGET" "bash -s" <<< "$REMOTE_SCRIPT"
fi

# ---------- done ----------
NANO_HOST="${TARGET#*@}"
ok "deployment complete"
echo ""
echo "┌─────────────────────────────────────────────────────────────┐"
echo "│  Open in your browser:                                      │"
echo "│    http://${NANO_HOST}:${NANO_PORT}/app/"
echo "│                                                             │"
echo "│  API docs:                                                  │"
echo "│    http://${NANO_HOST}:${NANO_PORT}/docs"
echo "│                                                             │"
echo "│  Logs (live tail):                                          │"
echo "│    ssh ${TARGET} 'cd ${REMOTE_DIR} && docker compose logs -f'"
echo "│                                                             │"
echo "│  Next time: re-run this script. DB + artifacts preserved.   │"
echo "└─────────────────────────────────────────────────────────────┘"
