"""Minimal Home Assistant REST helper for verifying the integration from WSL.

Needs HA_URL and HA_TOKEN in .env.local (Profile -> Security -> Create Token).

    python tools/ha.py states --filter terramaster
    python tools/ha.py state sensor.tnas_cpu_temperature
    python tools/ha.py call select select_option \
        --entity select.tnas_fan_mode --data '{"option": "medium"}'
    python tools/ha.py log
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from _env import load  # noqa: E402


class Ha:
    def __init__(self, url: str, token: str) -> None:
        self._url = url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(self, session, method, path, **kwargs):
        async with session.request(
            method, f"{self._url}/api{path}", headers=self._headers, **kwargs
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise SystemExit(f"HTTP {resp.status}: {text[:300]}")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

    async def states(self, session, needle: str | None):
        data = await self._request(session, "GET", "/states")
        rows = [
            s
            for s in data
            if not needle
            or needle.lower() in s["entity_id"].lower()
            or needle.lower() in str(s["attributes"].get("friendly_name", "")).lower()
        ]
        return sorted(rows, key=lambda s: s["entity_id"])


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_states = sub.add_parser("states", help="list entity states")
    p_states.add_argument("--filter", dest="needle", default=None)

    p_state = sub.add_parser("state", help="show one entity")
    p_state.add_argument("entity_id")

    p_call = sub.add_parser("call", help="call a service")
    p_call.add_argument("domain")
    p_call.add_argument("service")
    p_call.add_argument("--entity", required=False)
    p_call.add_argument("--data", default="{}")

    sub.add_parser("log", help="tail the HA error log")

    args = parser.parse_args()
    env = load()
    url, token = env.get("HA_URL"), env.get("HA_TOKEN")
    if not url or not token:
        raise SystemExit("set HA_URL and HA_TOKEN in .env.local first")

    ha = Ha(url, token)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        if args.command == "states":
            rows = await ha.states(session, args.needle)
            if not rows:
                print("no matching entities")
            width = max((len(r["entity_id"]) for r in rows), default=0)
            for row in rows:
                unit = row["attributes"].get("unit_of_measurement", "")
                print(f"{row['entity_id']:<{width}}  {row['state']} {unit}".rstrip())
            print(f"\n{len(rows)} entities")
        elif args.command == "state":
            print(json.dumps(await ha._request(session, "GET", f"/states/{args.entity_id}"), indent=2))
        elif args.command == "call":
            payload = json.loads(args.data)
            if args.entity:
                payload["entity_id"] = args.entity
            result = await ha._request(
                session, "POST", f"/services/{args.domain}/{args.service}", json=payload
            )
            print(json.dumps(result, indent=2)[:2000])
        elif args.command == "log":
            print(await ha._request(session, "GET", "/error_log"))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
