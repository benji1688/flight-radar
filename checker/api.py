"""Client de l'API privée du relais Cloudflare."""

from __future__ import annotations

import requests


class Relay:
    def __init__(self, base_url: str, api_key: str):
        self.base = base_url.rstrip("/")
        self.headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}

    def state(self) -> dict:
        r = requests.get(f"{self.base}/api/state", headers=self.headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def save(self, results: dict, stats: dict, run: dict) -> None:
        r = requests.put(f"{self.base}/api/results", headers=self.headers, timeout=30,
                         json={"results": results, "stats": stats, "run": run})
        r.raise_for_status()

    def notify(self, messages: list[dict]) -> None:
        if not messages:
            return
        r = requests.post(f"{self.base}/api/notify", headers=self.headers, timeout=60, json={"messages": messages})
        r.raise_for_status()
