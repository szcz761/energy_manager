"""Deye Cloud configuration.

This file is safe to commit and contains placeholder values only.
For real credentials, copy `config.local.example.py` to `config.local.py`
and fill your values there. `config.local.py` is gitignored.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


CONFIG: dict[str, str] = {
    "APP_ID": "YOUR_APP_ID",
    "APP_SECRET": "YOUR_APP_SECRET",
    "EMAIL": "your_email@example.com",
    "PASSWORD": "your_deye_password",
    "REGION": "eu",  # Valid values: "eu" or "us"
    "DEVICE_SN": "YOUR_DEVICE_SN",
}


def _load_local_config() -> dict[str, str]:
    local_path = Path(__file__).with_name("config.local.py")
    if not local_path.exists():
        return {}

    spec = importlib.util.spec_from_file_location("deye_client.config_local", local_path)
    if spec is None or spec.loader is None:
        return {}

    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    local_config: Any = getattr(module, "CONFIG", None)

    if not isinstance(local_config, dict):
        return {}

    return {str(key): str(value) for key, value in local_config.items()}


CONFIG.update(_load_local_config())
