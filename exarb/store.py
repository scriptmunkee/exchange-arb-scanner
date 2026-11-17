"""Persist scans and arb 'episodes' (an arb that stays open across consecutive scans) as CSV.

CSV keeps the git history readable and diff-friendly when committed by CI.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

EPISODE_FIELDS = [
    "sig", "kind", "sport", "event_name", "start", "selection", "first_seen", "last_seen", "scans",
    "duration_s", "best_profit_pct", "best_max_stake", "best_max_profit", "first_legs", "best_legs",
]
SCAN_FIELDS = ["ts", "matched_events", "markets_smarkets", "markets_matchbook", "opportunities", "near_misses", "best_margin_pct", "api_calls", "secs"]
GAP_CLOSE_S = 90  # an episode closes if not seen for this long


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, data_dir: str = "data"):
        self.dir = data_dir
        os.makedirs(self.dir, exist_ok=True)
        self.episodes_path = os.path.join(self.dir, "episodes.csv")
        self.scans_path = os.path.join(self.dir, f"scans-{_now():%Y-%m}.csv")
        self.episodes: dict[str, dict] = {}  # open + closed, keyed by sig#n
        self._open: dict[str, str] = {}  # sig -> row key of currently open episode
        self._load()

    def _load(self):
        if not os.path.exists(self.episodes_path):
            return
        with open(self.episodes_path, newline="") as f:
            for i, row in enumerate(csv.DictReader(f)):
                k = f"{row['sig']}#{row['first_seen']}"
                self.episodes[k] = row
                last = datetime.fromisoformat(row["last_seen"])
                if (_now() - last).total_seconds() <= GAP_CLOSE_S:
                    self._open[row["sig"]] = k  # resume across CI runs

    def record(self, opportunities, ts: datetime | None = None):
        ts = ts or _now()
        iso = ts.isoformat(timespec="seconds")
        seen = set()
        for o in opportunities:
            seen.add(o.sig)
            k = self._open.get(o.sig)
            row = self.episodes.get(k) if k else None
            if row and (ts - datetime.fromisoformat(row["last_seen"])).total_seconds() > GAP_CLOSE_S:
                row = None
            if row is None:
                k = f"{o.sig}#{iso}"
                row = {
                    "sig": o.sig, "kind": o.kind, "sport": o.sport, "event_name": o.event_name, "start": o.start,
                    "selection": o.selection, "first_seen": iso, "last_seen": iso, "scans": 0, "duration_s": 0,
                    "best_profit_pct": o.profit_pct, "best_max_stake": o.max_stake, "best_max_profit": o.max_profit,
                    "first_legs": o.legs, "best_legs": o.legs,
                }
                self.episodes[k] = row
                self._open[o.sig] = k
            row["last_seen"] = iso
            row["scans"] = int(row["scans"]) + 1
            row["duration_s"] = int((ts - datetime.fromisoformat(row["first_seen"])).total_seconds())
            if float(o.max_profit) > float(row["best_max_profit"]):
                row.update(best_profit_pct=o.profit_pct, best_max_stake=o.max_stake,
                           best_max_profit=o.max_profit, best_legs=o.legs)
        for sig in [s for s in self._open if s not in seen]:
            last = datetime.fromisoformat(self.episodes[self._open[sig]]["last_seen"])
            if (ts - last).total_seconds() > GAP_CLOSE_S:
                del self._open[sig]

    def log_scan(self, row: dict):
        new = not os.path.exists(self.scans_path)
        with open(self.scans_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SCAN_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)

    def flush(self):
        rows = sorted(self.episodes.values(), key=lambda r: r["first_seen"])
        tmp = self.episodes_path + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=EPISODE_FIELDS)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, self.episodes_path)
