# Data Designer Studio backend
# Python 3.11 slim. Works on linux/arm64 (ZGX Nano) and x86_64.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir \
    "data-designer>=0.3.0,<0.4.0" \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.27.0" \
    "pandas>=2.0.0" \
    "pyarrow>=15.0.0" \
    "pydantic>=2.6.0" \
    "pydantic-settings>=2.2.0" \
    "httpx>=0.27.0"

COPY backend/app /app/app
COPY frontend /app/frontend
COPY presets /app/presets

# Data Designer 0.3.8 reads provider config from $DATA_DESIGNER_HOME/model_providers.yaml.
# Pin the path inside the image so it's not /root/.data-designer (which is non-writable
# in some container setups) and so the file is a build artifact, not a runtime side effect.
ENV DATA_DESIGNER_HOME=/app/.data-designer
COPY backend/data_designer_home /app/.data-designer
RUN mkdir -p /app/.data-designer/managed-assets
RUN mkdir -p /var/lib/ddstudio/artifacts /var/lib/ddstudio
VOLUME ["/var/lib/ddstudio"]

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8765/api/health || exit 1

CMD ["python", "-m", "app.main"]
