import unittest
from datetime import datetime, timezone

from exarb import arb
from exarb.matching import match_markets, sim
from exarb.models import Market, Price, Selection, prob_to_decimal


def mk(ex, home, away, sels, sport="football", start="2026-11-20T15:00:00+00:00"):
    m = Market(ex, sport, f"{ex}1", f"{home} vs {away}", home, away, datetime.fromisoformat(start), f"{ex}m")
    for k, (b, bs, l, ls) in sels.items():
        m.selections[k] = Selection(k, k, Price(b, bs) if b else None, Price(l, ls) if l else None)
    return m


class BackLayMaths(unittest.TestCase):
    def test_worked_example(self):
        # Back £100 @2.10 on Smarkets (2%), lay @2.00 on Betfair (5%)
        lay_stake, profit = arb.back_lay(2.10, 0.02, 2.00, 0.05)
        self.assertAlmostEqual(lay_stake * 100, 106.56, places=2)
        self.assertAlmostEqual(profit * 100, 1.24, places=2)

    def test_both_outcomes_equal(self):
        b, cb, l, cl = 3.4, 0.02, 3.1, 0.02
        ls, profit = arb.back_lay(b, cb, l, cl)
        wins = (b - 1) * (1 - cb) - ls * (l - 1)
        loses = -1 + ls * (1 - cl)
        self.assertAlmostEqual(wins, loses, places=9)
        self.assertAlmostEqual(wins, profit, places=9)

    def test_no_arb_when_back_below_lay(self):
        _, profit = arb.back_lay(2.0, 0.02, 2.02, 0.02)
        self.assertLess(profit, 0)

    def test_commission_can_kill_a_gap(self):
        _, gross = arb.back_lay(2.02, 0.0, 2.0, 0.0)
        _, net = arb.back_lay(2.02, 0.02, 2.0, 0.02)
        self.assertGreater(gross, 0)
        self.assertLess(net, 0)


class DutchMaths(unittest.TestCase):
    def test_returns_equalised(self):
        legs = [(2.3, 0.02), (3.8, 0.02), (3.9, 0.02)]
        fr, profit = arb.dutch(legs)
        total = 100
        rets = [total * f * (1 + (o - 1) * (1 - c)) for f, (o, c) in zip(fr, legs)]
        for r in rets:
            self.assertAlmostEqual(r, rets[0], places=6)
        self.assertAlmostEqual(rets[0] / total - 1, profit, places=9)

    def test_two_way_arb(self):
        _, profit = arb.dutch([(2.1, 0.02), (2.1, 0.02)])
        self.assertGreater(profit, 0)


class Smarkets(unittest.TestCase):
    def test_prob_conversion(self):
        self.assertEqual(prob_to_decimal(5000), 2.0)
        self.assertAlmostEqual(prob_to_decimal(3226), 3.0998, places=3)


class Matching(unittest.TestCase):
    def test_similarity(self):
        self.assertEqual(sim("Arsenal FC", "Arsenal"), 1.0)
        self.assertGreater(sim("Brighton & Hove Albion", "Brighton and Hove Albion"), 0.78)
        self.assertEqual(sim("Arsenal Women", "Arsenal"), 0.0)  # different competition

    def test_finds_cross_exchange_arb(self):
        sm = mk("smarkets", "Leeds United", "Burnley", {
            "home": (2.10, 200, 2.14, 200), "draw": (3.5, 100, 3.6, 100), "away": (3.6, 100, 3.7, 100)})
        mb = mk("matchbook", "Leeds United FC", "Burnley", {
            "home": (1.96, 300, 2.00, 300), "draw": (3.5, 100, 3.6, 100), "away": (3.6, 100, 3.7, 100)})
        groups = match_markets({"smarkets": [sm], "matchbook": [mb]})
        self.assertEqual(len(groups), 1)
        opps = arb.find(groups)
        bl = [o for o in opps if o.kind == "back_lay"]
        self.assertEqual(len(bl), 1)
        o = bl[0]
        self.assertIn("BACK smarkets home @2.10", o.legs)
        self.assertIn("LAY matchbook home @2.00", o.legs)
        self.assertGreater(o.profit_pct, 0)
        # liquidity: £200 back, £300 lay backer stake; lay ratio ~1.06 → back stake capped at 200
        self.assertAlmostEqual(o.max_stake, 200, places=0)

    def test_tennis_swapped_order(self):
        sm = mk("smarkets", "Carlos Alcaraz", "Jannik Sinner", {"home": (2.2, 50, 2.3, 50), "away": (1.75, 50, 1.8, 50)}, "tennis")
        mb = mk("matchbook", "Jannik Sinner", "Carlos Alcaraz", {"home": (1.75, 50, 1.8, 50), "away": (2.2, 50, 2.3, 50)}, "tennis")
        groups = match_markets({"smarkets": [sm], "matchbook": [mb]})
        self.assertEqual(len(groups), 1)
        self.assertEqual(arb.find(groups), [])  # identical prices once re-oriented → no arb

    def test_kickoff_too_far_apart(self):
        sm = mk("smarkets", "A Team", "B Team", {"home": (2, 1, 2.1, 1)})
        mb = mk("matchbook", "A Team", "B Team", {"home": (2, 1, 2.1, 1)}, start="2026-11-20T18:00:00+00:00")
        self.assertEqual(match_markets({"smarkets": [sm], "matchbook": [mb]}), [])


if __name__ == "__main__":
    unittest.main()
