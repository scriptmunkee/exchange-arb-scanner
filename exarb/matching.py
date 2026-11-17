"""Match the same event across exchanges by team names and kick-off time."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import Market

STOP = {"fc", "afc", "cf", "sc", "ac", "the", "club", "cd", "fk", "sk", "bk", "if", "women", "w", "u21", "u23", "u19"}
KEEP_SUFFIX = {"women", "w", "u21", "u23", "u19", "ii", "b", "reserves"}  # must agree if present
MIN_SIM = 0.78
MAX_START_DIFF_MIN = 20


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(t for t in s.split() if t not in STOP)


def _tags(name: str) -> set[str]:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return {t for t in re.sub(r"[^a-z0-9 ]+", " ", s).split() if t in KEEP_SUFFIX}


def sim(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb or _tags(a) != _tags(b):
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    # token containment helps "Man Utd" vs "Manchester United" style gaps a little
    ta, tb = set(na.split()), set(nb.split())
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(ratio, 0.6 * ratio + 0.4 * overlap)


def match_markets(markets_by_exchange: dict[str, list[Market]]):
    """Return groups: list of (event_key, {exchange: (Market, swapped)}).

    The first exchange is the anchor. `swapped` means home/away are reversed
    relative to the anchor (common in tennis).
    """
    exchanges = list(markets_by_exchange)
    if len(exchanges) < 2:
        return []
    anchor, others = exchanges[0], exchanges[1:]
    groups = []
    for a in markets_by_exchange[anchor]:
        group = {anchor: (a, False)}
        for ex in others:
            best, best_score, best_swap = None, 0.0, False
            for b in markets_by_exchange[ex]:
                if b.sport != a.sport:
                    continue
                if abs((b.start - a.start).total_seconds()) > MAX_START_DIFF_MIN * 60:
                    continue
                straight = min(sim(a.home, b.home), sim(a.away, b.away))
                swapped = min(sim(a.home, b.away), sim(a.away, b.home)) if a.sport == "tennis" else 0.0
                score, swap = (straight, False) if straight >= swapped else (swapped, True)
                if score > best_score:
                    best, best_score, best_swap = b, score, swap
            if best and best_score >= MIN_SIM:
                group[ex] = (best, best_swap)
        if len(group) > 1:
            key = f"{a.sport}|{a.start:%Y%m%d%H%M}|{norm(a.home)}|{norm(a.away)}"
            groups.append((key, group))
    return groups


def oriented(market: Market, swapped: bool):
    """Selections keyed relative to the anchor's home/away."""
    if not swapped:
        return market.selections
    flip = {"home": "away", "away": "home", "draw": "draw"}
    return {flip[k]: v for k, v in market.selections.items()}
