"""Settings - typed config from environment. Imported as `from .settings import settings`."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # Providers
    nvidia_api_key: str = ""
    nvidia_endpoint: str = "https://integrate.api.nvidia.com/v1"
    local_vllm_url: str = "http://<NANO_IP>:8090/v1"
    local_vllm_url_fast: str = "http://<NANO_IP>:8091/v1"
    local_vllm_api_key: str = "not-needed"

    # Backend binding
    backend_host: str = "0.0.0.0"
    backend_port: int = 8765

    # Storage
    artifact_path: Path = Field(default=Path("/var/lib/ddstudio/artifacts"))
    db_path: Path = Field(default=Path("/var/lib/ddstudio/ddstudio.db"))

    log_level: str = "INFO"


settings = Settings()
settings.artifact_path.mkdir(parents=True, exist_ok=True)
settings.db_path.parent.mkdir(parents=True, exist_ok=True)
