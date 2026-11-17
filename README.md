# exchange-arb-scanner

Read-only scanner that logs arbitrage gaps between UK betting exchanges. **It places no bets.**

It compares **Smarkets** and **Matchbook** match-odds prices on pre-match football and tennis, then logs every
gap that is a guaranteed profit **after commission**, how much money was available at that price, and how long the
gap stayed open. The point is to measure the real edge for a few weeks before spending anything (for example the
£299 Betfair live API key) or risking money.

## What it looks for

| Type | How it works |
|---|---|
| Back/lay | Back a selection on one exchange and lay the same selection on the other, sized so you win the same either way. |
| Back all (dutch) | Back every outcome, each at whichever exchange has the best price, so one leg always wins. |

Maths (per £1 backed, commission `c` on net market winnings, so losing legs pay none):

```
lay_stake = (1 + (back - 1) * (1 - c_back)) / (lay - c_lay)
profit    = lay_stake * (1 - c_lay) - 1
```

Worked example: back £100 @ 2.10 on Smarkets (2%), lay £106.56 @ 2.00 on Betfair (5%) = **+£1.24** either way.

## Data sources

| Exchange | Endpoint | Auth |
|---|---|---|
| Smarkets | `api.smarkets.com/v3` events, markets, contracts, quotes | none (public prices) |
| Matchbook | `api.matchbook.com/edge/rest/events` with prices | none (public prices) |
| Betfair | not yet: needs a live app key (£299) or an aggregator such as OddsRelay (pre-match, token-priced) | later |

Assumptions to check before trusting the £ figures:
- Matchbook `available-amount` is treated as the backer's stake on both sides.
- Commission defaults: Smarkets 2%, Matchbook 2% (set `EXARB_COMMISSION='{"matchbook":0.015}'` to change).
- Prices are snapshots about 30 seconds apart. A gap that shows for one scan may already be gone.

## Run it

```bash
python -m exarb                         # one scan
python -m exarb --duration 3600         # scan every 30s for an hour
python -m unittest discover -s tests    # maths + matching tests
```

No dependencies beyond the Python 3.11+ standard library.

Output (in `data/`):
- `episodes.csv`: one row per arb, with first/last seen, how long it stayed open, best profit %, max stake, legs.
- `scans-YYYY-MM.csv`: one row per scan: events matched, arbs, near misses (within 0.5%), best margin.

## Always-on (GitHub Actions)

`.github/workflows/scan.yml` runs the scanner for about 4.5 minutes every 5 minutes and commits the CSVs to the
`data` branch. GitHub can delay or skip scheduled runs, so expect small gaps.

## Dashboard

`dashboard/index.html` reads the CSVs from the `data` branch (or `?data=../data/` locally) and shows the closest gap
per scan, near misses, and every arb found. Light mode, no build step.

## Not financial advice

This is a measurement tool. Betting involves risk. Betfair, Smarkets and Matchbook terms apply to any API use.
