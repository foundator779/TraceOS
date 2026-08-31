from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "TraceOS"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    traceos_db_path: str = str(ROOT / "data" / "traceos.db")
    traceos_store: str = "sqlite"
    traceos_api_key: str | None = None
    google_api_key: str | None = None
    gemini_model: str = "gemini-3.7-flash"
    gemini_vision_model: str = "gemini-2.5-flash"
    gemini_use_vertex: bool = False
    gemini_location: str = "global"
    google_cloud_project: str = "traceos-506713"
    google_cloud_location: str = "us-central1"
    enable_cloud_connectors: bool = False
    enable_model_armor: bool = False
    model_armor_template_id: str = "traceos-evidence"
    evidence_bucket: str | None = None
    evidence_local_path: str = str(ROOT / "data" / "evidence")
    max_image_bytes: int = 5 * 1024 * 1024
    max_image_dimension: int = 4096
    demo_daily_run_limit: int = 20
    pubsub_push_audience: str | None = None
    pubsub_push_service_account: str | None = None
    agent_gateway_status: str = "UNAVAILABLE_IN_PROJECT"
    runtime_step_delay_ms: int = 260
    enable_gemma_verifier: bool = False
    enable_veo_training: bool = False
    enable_lyria_training: bool = False
    gemma_verifier_model: str = "gemma-4-26b-a4b-it-maas"
    veo_training_model: str = "veo-3.1-fast-generate-001"
    lyria_training_model: str = "lyria-3-clip-preview"
    training_media_location: str = "us-central1"
    training_output_bucket: str | None = None
    training_local_path: str = str(ROOT / "data" / "training")
    training_budget_usd: float = 1.0
    training_max_live_runs: int = 1
    training_max_artifact_retries: int = 2
    training_pubsub_topic: str | None = None
    training_pubsub_audience: str | None = None
    training_worker_service_account: str | None = None
    training_job_timeout_seconds: int = 240

    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env", ROOT.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
