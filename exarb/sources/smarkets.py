"""Smarkets public v3 API (read-only, no login needed for prices).

Quotes: `offers` are what we can BACK into, `bids` are what we can LAY into.
Price is implied probability in basis points; quantity is in 1/10000 of a £1
contract, so backer stake = quantity * price / 1e8.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from ..http import Client
from ..models import Market, Price, Selection, prob_to_decimal

SPORTS = {
    "football": {"event_type": "football_match", "market_type": "WINNER_3_WAY"},
    "tennis": {"event_type": "tennis_match", "market_type": "WINNER_2_WAY"},
}
CONTRACT_KEYS = {"HOME": "home", "DRAW": "draw", "AWAY": "away", "PLAYER_A": "home", "PLAYER_B": "away"}
BATCH = 25


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class SmarketsSource:
    name = "smarkets"

    def __init__(self, sports=("football", "tennis"), hours_ahead: int = 48, catalogue_ttl: int = 600):
        self.client = Client("https://api.smarkets.com/v3", min_interval=0.3)
        self.sports = sports
        self.hours_ahead = hours_ahead
        self.catalogue_ttl = catalogue_ttl
        self._catalogue: dict[str, Market] = {}  # market_id -> Market skeleton
        self._contracts: dict[str, tuple[str, str]] = {}  # contract_id -> (market_id, key)
        self._built = 0.0
        self.failed: list[str] = []  # per-market failures from the last fetch, logged by the CLI

    # ---- catalogue (events, markets, contracts) ---------------------------------
    def _events(self, event_type: str):
        horizon = datetime.now(timezone.utc) + timedelta(hours=self.hours_ahead)
        path = f"/events/?type={event_type}&state=upcoming&limit=200&sort=start_datetime,id"
        out = []
        while path:
            data = self.client.get_json(path)
            for e in data.get("events", []):
                if not e.get("start_datetime"):
                    continue
                start = _parse_dt(e["start_datetime"])
                if start > horizon:
                    return out
                if " vs " in e["name"]:
                    out.append(e)
            nxt = (data.get("pagination") or {}).get("next_page")
            path = f"/events/{nxt}" if nxt else None
        return out

    def _build_catalogue(self):
        catalogue, contracts = {}, {}
        for sport in self.sports:
            cfg = SPORTS[sport]
            events = {e["id"]: e for e in self._events(cfg["event_type"])}
            ids = list(events)
            for i in range(0, len(ids), BATCH):
                chunk = ids[i : i + BATCH]
                mk = self.client.get_json(f"/events/{','.join(chunk)}/markets/?limit_by_event=3")
                wanted = [m for m in mk.get("markets", []) if m["market_type"]["name"] == cfg["market_type"]]
                for m in wanted:
                    e = events[m["event_id"]]
                    home, away = [p.strip() for p in e["name"].split(" vs ", 1)]
                    catalogue[m["id"]] = Market(
                        exchange=self.name,
                        sport=sport,
                        event_id=e["id"],
                        event_name=e["name"],
                        home=home,
                        away=away,
                        start=_parse_dt(e["start_datetime"]),
                        market_id=m["id"],
                        url=f"https://smarkets.com/event/{e['id']}{e.get('full_slug', '')}",
                    )
                if wanted:
                    ct = self.client.get_json(f"/markets/{','.join(m['id'] for m in wanted)}/contracts/")
                    for c in ct.get("contracts", []):
                        key = CONTRACT_KEYS.get(c["contract_type"]["name"])
                        if key and c["market_id"] in catalogue:
                            contracts[c["id"]] = (c["market_id"], key)
                            catalogue[c["market_id"]].selections[key] = Selection(key=key, name=c["name"])
        self._catalogue, self._contracts, self._built = catalogue, contracts, time.monotonic()

    # ---- prices --------------------------------------------------------------------
    def fetch(self) -> list[Market]:
        if not self._catalogue or time.monotonic() - self._built > self.catalogue_ttl:
            self._build_catalogue()
        self.failed = []
        now = datetime.now(timezone.utc)
        live_ids = [mid for mid, m in self._catalogue.items() if m.start > now]
        fresh: dict[str, Market] = {}
        for i in range(0, len(live_ids), BATCH):
            chunk = live_ids[i : i + BATCH]
            quotes = self._quotes(chunk)
            for cid, q in quotes.items():
                if cid not in self._contracts:
                    continue
                mid, key = self._contracts[cid]
                skel = self._catalogue[mid]
                m = fresh.setdefault(mid, _clone(skel))
                sel = m.selections[key]
                if q.get("offers"):
                    best = min(q["offers"], key=lambda o: o["price"])  # lowest prob = highest odds
                    sel.back = Price(prob_to_decimal(best["price"]), best["quantity"] * best["price"] / 1e8)
                if q.get("bids"):
                    best = max(q["bids"], key=lambda o: o["price"])  # highest prob = lowest lay odds
                    sel.lay = Price(prob_to_decimal(best["price"]), best["quantity"] * best["price"] / 1e8)
        return list(fresh.values())

    def _quotes(self, chunk: list[str]) -> dict:
        """Fetch quotes for a batch; on failure split it so one bad market cannot sink the scan."""
        try:
            return self.client.get_json(f"/markets/{','.join(chunk)}/quotes/", retries=2)
        except Exception as e:
            if len(chunk) == 1:
                self.failed.append(f"market {chunk[0]}: {e}")
                return {}
            mid = len(chunk) // 2
            return {**self._quotes(chunk[:mid]), **self._quotes(chunk[mid:])}


def _clone(m: Market) -> Market:
    return Market(
        exchange=m.exchange, sport=m.sport, event_id=m.event_id, event_name=m.event_name,
        home=m.home, away=m.away, start=m.start, market_id=m.market_id, url=m.url,
        selections={k: Selection(key=k, name=s.name) for k, s in m.selections.items()},
    )
