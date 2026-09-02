"""Dump every interesting TOS endpoint to tools/captures/ as raw JSON.

The captured shapes are what the integration's parsers are written against --
run this first, and re-run it after a TOS firmware update to spot drift.
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "terramaster"))
sys.path.insert(0, str(ROOT / "tools"))

from _env import load  # noqa: E402
from tos import TosClient  # noqa: E402

ENDPOINTS = [
    "/hardware/",
    "/power/",
    "/resource/temperature",
    "/resource/network",
    "/disk/GetDiskListData",
    "/disk/IhmInfoList",
    "/disk/GetDiskStatus",
    "/disk/GetOverview",
    "/systemStatus/NasProcessorInfo",
    "/systemStatus/ServiceStatus",
    "/storage/list/pool",
    "/storage/list/volume",
    "/storage/status",
    "/system/getPlatform",
    "/login/state",
]


async def main() -> int:
    env = load()
    out = ROOT / "tools" / "captures"
    out.mkdir(parents=True, exist_ok=True)

    client = TosClient(
        host=env["TOS_HOST"],
        port=int(env.get("TOS_PORT", 8181)),
        username=env["TOS_USER"],
        password=env["TOS_PASS"],
    )
    async with client:
        await client.login()
        for path in ENDPOINTS:
            name = path.strip("/").replace("/", "_") or "root"
            try:
                status, data = await client._request("GET", path)
            except Exception as err:  # noqa: BLE001 - probe tool, report and continue
                print(f"{path:34} ERROR {err}")
                continue
            (out / f"{name}.json").write_text(json.dumps(data, indent=2))
            payload = data.get("data") if isinstance(data, dict) else data
            print(f"{path:34} {status} -> {json.dumps(payload)[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
