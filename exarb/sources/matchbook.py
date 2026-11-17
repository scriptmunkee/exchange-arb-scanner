"""Matchbook public edge API (read-only, prices available without login).

side=back prices are what we can BACK at; side=lay prices are what we can LAY at.
`available-amount` is treated as the backer's stake (an assumption, flagged in README).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..http import Client
from ..models import Market, Price, Selection

SPORTS = {
    "football": {"sport_id": 15, "market_types": {"one_x_two"}},
    "tennis": {"sport_id": 9, "market_types": {"money_line"}},
}
PER_PAGE = 100


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class MatchbookSource:
    name = "matchbook"

    def __init__(self, sports=("football", "tennis"), hours_ahead: int = 48):
        self.client = Client("https://api.matchbook.com/edge/rest", min_interval=0.3)
        self.sports = sports
        self.hours_ahead = hours_ahead

    def fetch(self) -> list[Market]:
        out: list[Market] = []
        now = datetime.now(timezone.utc)
        after = int(now.timestamp())  # Matchbook wants epoch seconds
        before = int((now + timedelta(hours=self.hours_ahead)).timestamp())
        for sport in self.sports:
            cfg = SPORTS[sport]
            offset = 0
            while True:
                data = self.client.get_json(
                    f"/events?sport-ids={cfg['sport_id']}&states=open&per-page={PER_PAGE}&offset={offset}"
                    f"&after={after}&before={before}&include-prices=true&price-depth=1&odds-type=DECIMAL"
                    "&exchange-type=back-lay&include-event-participants=true"
                )
                for e in data.get("events", []):
                    m = self._parse_event(e, sport, cfg["market_types"])
                    if m:
                        out.append(m)
                offset += PER_PAGE
                if offset >= data.get("total", 0) or not data.get("events"):
                    break
        return out

    def _parse_event(self, e: dict, sport: str, market_types: set[str]) -> Market | None:
        if e.get("in-running-flag") or " vs " not in e.get("name", ""):
            return None
        parts = {p["id"]: p for p in e.get("event-participants", [])}
        mk = next((m for m in e.get("markets", []) if m.get("market-type") in market_types and m.get("status") == "open"), None)
        if not mk:
            return None
        home, away = [p.strip() for p in e["name"].split(" vs ", 1)]
        m = Market(
            exchange=self.name, sport=sport, event_id=str(e["id"]), event_name=e["name"], home=home, away=away,
            start=_parse_dt(e["start"]), market_id=str(mk["id"]),
            url=f"https://www.matchbook.com/events/{e['id']}",
        )
        for r in mk.get("runners", []):
            pid = r.get("event-participant-id")
            if pid in parts:
                key = "home" if parts[pid].get("number") == 1 else "away"
            elif r.get("name", "").strip().lower() == "draw":
                key = "draw"
            else:
                continue
            sel = Selection(key=key, name=r["name"])
            backs = [p for p in r.get("prices", []) if p["side"] == "back"]
            lays = [p for p in r.get("prices", []) if p["side"] == "lay"]
            if backs:
                b = max(backs, key=lambda p: p["odds"])
                sel.back = Price(float(b["odds"]), float(b["available-amount"]))
            if lays:
                l = min(lays, key=lambda p: p["odds"])
                sel.lay = Price(float(l["odds"]), float(l["available-amount"]))
            m.selections[key] = sel
        return m if m.selections else None
