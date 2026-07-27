"""Deye Cloud configuration.

Loads config from JSON file. For real credentials, copy `config.json` to 
`config.local.json` and fill your values there. `config.local.json` is gitignored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


CONFIG: Dict[str, str] = {
    "APP_ID": "YOUR_APP_ID",
    "APP_SECRET": "YOUR_APP_SECRET",
    "EMAIL": "your_email@example.com",
    "PASSWORD": "your_deye_password",
    "REGION": "eu",
    "DEVICE_SN": "YOUR_DEVICE_SN",
}


def _load_json_config(filename: str) -> Dict[str, str]:
    """Load config from JSON file."""
    path = Path(__file__).with_name(filename)
    if not path.exists():
        return {}
    
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


# Load local config if exists, otherwise fall back to default
local_config = _load_json_config("config.local.json")
if local_config:
    CONFIG.update(local_config)
else:
    default_config = _load_json_config("config.json")
    CONFIG.update(default_config)
