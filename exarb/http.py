"""Tiny stdlib HTTP client with a polite user agent, gzip, retries and pacing."""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request

USER_AGENT = "exchange-arb-scanner/0.1 (personal research; read-only)"


class Client:
    def __init__(self, base: str, min_interval: float = 0.25, timeout: float = 20.0):
        self.base = base.rstrip("/")
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0
        self.calls = 0

    def get_json(self, path: str, retries: int = 3):
        url = path if path.startswith("http") else f"{self.base}{path}"
        for attempt in range(retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.calls += 1
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return json.loads(raw)
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    retry_after = float(e.headers.get("Retry-After") or 2 ** attempt)
                    time.sleep(min(retry_after, 30))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                time.sleep(2 ** attempt)
        raise RuntimeError(f"GET failed after {retries} attempts: {url}")
