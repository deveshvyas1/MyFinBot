"""Configuration loading utilities."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from .models import AppConfig


def load_config(config_path: Path) -> AppConfig:
    """Load the application configuration from a YAML file."""
    raw: Dict[str, Any]
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return AppConfig.model_validate(raw)
