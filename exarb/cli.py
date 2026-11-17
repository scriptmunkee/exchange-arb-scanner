"""Command line: scan once, or loop for a fixed duration (used by CI every 5 minutes)."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

from . import arb
from .matching import match_markets
from .sources.matchbook import MatchbookSource
from .sources.smarkets import SmarketsSource
from .store import Store


def build_sources(sports):
    return [SmarketsSource(sports=sports), MatchbookSource(sports=sports)]


def scan_once(sources, store: Store, commission: dict, verbose: bool = True):
    t0 = time.monotonic()
    by_ex, errors = {}, []
    for s in sources:
        try:
            by_ex[s.name] = s.fetch()
        except Exception as e:  # one exchange failing must not kill the run
            errors.append(f"{s.name}: {e}")
            by_ex[s.name] = []
    groups = match_markets(by_ex)
    every = arb.find(groups, commission, min_profit_pct=-100)
    opps = [o for o in every if o.profit_pct > 0]
    best_margin = max((o.profit_pct for o in every), default=None)
    near = sum(1 for o in every if -0.5 < o.profit_pct <= 0)
    ts = datetime.now(timezone.utc)
    store.record(opps, ts)
    store.log_scan({
        "ts": ts.isoformat(timespec="seconds"), "matched_events": len(groups),
        "markets_smarkets": len(by_ex.get("smarkets", [])), "markets_matchbook": len(by_ex.get("matchbook", [])),
        "opportunities": len(opps), "near_misses": near,
        "best_margin_pct": "" if best_margin is None else best_margin, "api_calls": sum(s.client.calls for s in sources),
        "secs": round(time.monotonic() - t0, 1),
    })
    if errors:
        with open(f"{store.dir}/errors-{ts:%Y-%m}.log", "a") as f:
            f.write(f"{ts.isoformat(timespec='seconds')} {' | '.join(errors)}\n")
    if verbose:
        print(f"{ts:%H:%M:%S} matched={len(groups)} sm={len(by_ex.get('smarkets', []))} "
              f"mb={len(by_ex.get('matchbook', []))} arbs={len(opps)} near={near} best={best_margin} {'ERR ' + '; '.join(errors) if errors else ''}")
        for o in sorted(opps, key=lambda o: -o.max_profit)[:5]:
            print(f"   {o.profit_pct:+.2f}% £{o.max_profit:.2f} on £{o.max_stake:.0f}  {o.event_name}  {o.legs}")
    return groups, opps


def main(argv=None):
    p = argparse.ArgumentParser(prog="exarb", description="Read-only exchange arbitrage scanner")
    p.add_argument("--duration", type=int, default=0, help="seconds to keep scanning (0 = one scan)")
    p.add_argument("--interval", type=int, default=30, help="seconds between scans")
    p.add_argument("--sports", default="football,tennis")
    p.add_argument("--data-dir", default=os.environ.get("EXARB_DATA_DIR", "data"))
    p.add_argument("--commission", default=os.environ.get("EXARB_COMMISSION", ""),
                   help='JSON, e.g. {"smarkets":0.02,"matchbook":0.015}')
    a = p.parse_args(argv)
    commission = json.loads(a.commission) if a.commission else {}
    sources = build_sources(tuple(a.sports.split(",")))
    store = Store(a.data_dir)
    end = time.monotonic() + a.duration
    while True:
        started = time.monotonic()
        try:
            scan_once(sources, store, commission)
        finally:
            store.flush()
        if time.monotonic() + a.interval > end:
            break
        time.sleep(max(0, a.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
