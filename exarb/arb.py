"""Commission-adjusted arbitrage maths.

Commission is charged on net winnings per market on each exchange, so a leg
that loses pays no commission. All results are per £1 of the reference stake.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from .matching import oriented

DEFAULT_COMMISSION = {"smarkets": 0.02, "matchbook": 0.02, "betfair": 0.05}


@dataclass
class Opportunity:
    kind: str  # "back_lay" | "dutch"
    event_key: str
    sport: str
    event_name: str
    start: str
    selection: str  # selection for back_lay, "all" for dutch
    legs: str  # human-readable legs, e.g. "BACK smarkets home @2.10 | LAY matchbook home @2.00"
    profit_pct: float  # guaranteed profit: % of the back stake (back_lay) or of total stake (dutch)
    max_stake: float  # largest back stake (back_lay) or total stake (dutch) visible liquidity supports, GBP
    max_profit: float  # GBP at max_stake
    sig: str  # stable id for episode tracking


def back_lay(back_odds: float, back_comm: float, lay_odds: float, lay_comm: float):
    """Back £1 at back_odds on exchange X, lay on exchange Y sized to equalise outcomes.

    Returns (lay_stake, profit) per £1 backed. Profit > 0 means a guaranteed win.
    Wins:  (back_odds-1)*(1-back_comm) - lay_stake*(lay_odds-1)
    Loses: -1 + lay_stake*(1-lay_comm)
    """
    lay_stake = (1 + (back_odds - 1) * (1 - back_comm)) / (lay_odds - lay_comm)
    profit = lay_stake * (1 - lay_comm) - 1
    return lay_stake, profit


def dutch(legs: list[tuple[float, float]]):
    """Back every outcome. legs = [(odds, commission)]. Returns (stake_fractions, profit_pct).

    Equalising net returns gives stakes s_i = R / e_i with e_i = 1+(odds_i-1)(1-c_i).
    Profit as a fraction of total stake = 1/sum(1/e_i) - 1.
    (Conservative when two legs share an exchange: real commission would be lower.)
    """
    eff = [1 + (o - 1) * (1 - c) for o, c in legs]
    inv = sum(1 / e for e in eff)
    fractions = [(1 / e) / inv for e in eff]
    return fractions, 1 / inv - 1


def find(groups, commission=None, min_profit_pct: float = 0.0) -> list[Opportunity]:
    commission = {**DEFAULT_COMMISSION, **(commission or {})}
    found: list[Opportunity] = []
    for key, group in groups:
        anchor = next(iter(group.values()))[0]
        sels_by_ex = {ex: oriented(m, sw) for ex, (m, sw) in group.items()}
        keys = sorted(set.intersection(*(set(s) for s in sels_by_ex.values())))
        base = dict(event_key=key, sport=anchor.sport, event_name=anchor.event_name, start=anchor.start.isoformat())

        # 1) back on one exchange, lay the same selection on another
        for sel_key in keys:
            for bx, lx in product(sels_by_ex, repeat=2):
                if bx == lx:
                    continue
                b, l = sels_by_ex[bx][sel_key].back, sels_by_ex[lx][sel_key].lay
                if not b or not l or b.odds <= 1 or l.odds <= 1:
                    continue
                lay_stake, profit = back_lay(b.odds, commission[bx], l.odds, commission[lx])
                pct = profit * 100
                if pct <= min_profit_pct:
                    continue
                max_stake = min(b.size, l.size / lay_stake)
                found.append(Opportunity(
                    kind="back_lay", selection=sel_key, profit_pct=round(pct, 3),
                    legs=f"BACK {bx} {sel_key} @{b.odds:.2f} (£{b.size:.0f}) | LAY {lx} {sel_key} @{l.odds:.2f} (£{l.size:.0f})",
                    max_stake=round(max_stake, 2), max_profit=round(max_stake * profit, 2),
                    sig=f"{key}|bl|{sel_key}|{bx}>{lx}", **base,
                ))

        # 2) back every outcome at the best exchange for each (needs full outcome set)
        if len(keys) in (2, 3) and set(keys) in ({"home", "away"}, {"home", "draw", "away"}):
            best = {}
            for sel_key in keys:
                cands = [(s[sel_key].back, ex) for ex, s in sels_by_ex.items() if s[sel_key].back]
                if len(cands) == len(sels_by_ex):  # every exchange quotes it, take the best
                    best[sel_key] = max(cands, key=lambda c: 1 + (c[0].odds - 1) * (1 - commission[c[1]]))
            if len(best) == len(keys) and len({ex for _, ex in best.values()}) > 1:
                legs = [(best[k][0].odds, commission[best[k][1]]) for k in keys]
                fractions, profit = dutch(legs)
                pct = profit * 100
                if pct > min_profit_pct:
                    # total stake T limited by each leg: fraction_i * T <= size_i
                    max_total = min(best[k][0].size / f for k, f in zip(keys, fractions))
                    found.append(Opportunity(
                        kind="dutch", selection="all", profit_pct=round(pct, 3),
                        legs=" | ".join(f"BACK {best[k][1]} {k} @{best[k][0].odds:.2f} (£{best[k][0].size:.0f})" for k in keys),
                        max_stake=round(max_total, 2), max_profit=round(max_total * profit, 2),
                        sig=f"{key}|dutch|" + ",".join(best[k][1] for k in keys), **base,
                    ))
    return found
