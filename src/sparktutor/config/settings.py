"""Configuration model for SparkTutor."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class ExecutionMode(str, Enum):
    AUTO = "auto"
    LAKEHOUSE = "lakehouse"
    LOCAL = "local"
    DRY_RUN = "dry_run"


class DockerConfig(BaseModel):
    container_name: str = "spark-master-41"
    spark_master_url: str = "spark://localhost:7078"


class ClaudeConfig(BaseModel):
    api_key: Optional[str] = Field(default=None)
    model: str = "claude-sonnet-4-6"

    def get_api_key(self) -> Optional[str]:
        return self.api_key or os.environ.get("ANTHROPIC_API_KEY")

    def get_model(self) -> str:
        return os.environ.get("SPARKTUTOR_CLAUDE_MODEL") or self.model


class Settings(BaseModel):
    execution_mode: ExecutionMode = ExecutionMode.AUTO
    docker: DockerConfig = Field(default_factory=DockerConfig)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    timeout_seconds: int = 120
    data_dir: Path = Path.home() / ".sparktutor"

    @classmethod
    def load(cls) -> "Settings":
        config_path = Path.home() / ".sparktutor" / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        return cls()

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.data_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(self.model_dump(mode="json"), f, default_flow_style=False)
