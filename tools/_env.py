"""Tiny .env.local loader shared by the probe tools."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: Path | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    target = path or ROOT / ".env.local"
    if target.exists():
        for line in target.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    env.update({k: v for k, v in os.environ.items() if k in env or k.startswith(("TOS_", "NAS_", "HA_"))})
    return env
