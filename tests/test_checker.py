import unittest
from datetime import date

from checker import main as M
from checker.fx import FX
from checker.markets import MARKETS, rank_markets, record
from checker.notify import build_message, is_quiet, should_notify
from checker.planner import Quote, date_combos, months_to_scan, quote_ok
from checker.sources.travelpayouts import parse_item

TODAY = date(2026, 11, 22)
FXR = FX({"PLN": 4.25, "HUF": 400.0, "TRY": 40.0, "USD": 1.08})

WEEKEND = {"id": "a1", "origins": ["LYS"], "destinations": ["BCN"], "date_from": "2027-03-01",
           "date_to": "2027-03-31", "months": ["2027-03"], "weekends": True, "nights": [1, 3],
           "one_way": False, "direct": False, "max_price": 80, "dep_window": None, "ret_window": None,
           "notify": True, "active": True}


def q(market="fr", eur=70.0, out="2027-03-05", ret="2027-03-07", source="google", **kw):
    return Quote("LYS", "BCN", out, ret, eur, "EUR", eur, market, source, **kw)


class Planner(unittest.TestCase):
    def test_weekend_combos(self):
        combos = date_combos(WEEKEND, TODAY)
        self.assertEqual(combos[0], ("2027-03-05", "2027-03-07"))  # vendredi → dimanche d'abord
        for out, ret in combos:
            self.assertIn(date.fromisoformat(out).weekday(), {3, 4, 5})
            self.assertIn(date.fromisoformat(ret).weekday(), {5, 6, 0})

    def test_filters(self):
        a = dict(WEEKEND, direct=True, dep_window=[6, 12])
        self.assertTrue(quote_ok(a, q(stops=0, out_time="07:30"), TODAY))
        self.assertFalse(quote_ok(a, q(stops=1, out_time="07:30"), TODAY))
        self.assertFalse(quote_ok(a, q(stops=0, out_time="18:00"), TODAY))
        self.assertFalse(quote_ok(a, q(out="2027-03-03", ret="2027-03-05"), TODAY))  # mercredi

    def test_months(self):
        a = dict(WEEKEND, date_from="2026-12-01", date_to="2027-02-28", months=[])
        self.assertEqual(months_to_scan(a, TODAY), ["2026-12", "2027-01", "2027-02"])


class Markets(unittest.TestCase):
    def test_learning_changes_order(self):
        stats = {}
        first = rank_markets(stats, "LYS-BCN", "es", [])
        self.assertEqual(first[:2], ["es", "pl"])  # pays de la destination, puis ordre initial
        for _ in range(6):
            record(stats, "LYS-BCN", "ro", True, 12)
            record(stats, "LYS-BCN", "pl", False, 0)
        ranked = rank_markets(stats, "LYS-BCN", None, ["hu"])
        self.assertEqual(ranked[0], "ro")
        self.assertNotIn("hu", ranked)
        self.assertLess(ranked.index("ro"), ranked.index("pl"))


class Notify(unittest.TestCase):
    S = {"drop_pct": 5, "fx_fee_pct": 2, "min_gain_eur": 15}

    def test_threshold_and_drop(self):
        res = {}
        self.assertFalse(should_notify(WEEKEND, 95, res, self.S)[0])
        self.assertTrue(should_notify(WEEKEND, 75, res, self.S)[0])
        res["notified_eur"] = 75
        self.assertFalse(should_notify(WEEKEND, 73, res, self.S)[0])
        self.assertTrue(should_notify(WEEKEND, 70, res, self.S)[0])
        self.assertFalse(should_notify(dict(WEEKEND, notify=False), 10, {}, self.S)[0])

    def test_rearm_after_rise(self):
        res = {"notified_eur": 60}
        should_notify(WEEKEND, 90, res, self.S)
        self.assertIsNone(res["notified_eur"])
        self.assertTrue(should_notify(WEEKEND, 78, res, self.S)[0])

    def test_quiet(self):
        s = {"quiet": [23, 7]}
        self.assertTrue(is_quiet(s, 2))
        self.assertTrue(is_quiet(s, 23))
        self.assertFalse(is_quiet(s, 12))

    def test_message(self):
        best = Quote("LYS", "BCN", "2027-03-05", "2027-03-07", 241, "PLN", 57.8, "pl", "google",
                     airline="Vueling", stops=0, out_time="07:15", link="https://example.org")
        txt = build_message(WEEKEND, best, "baisse de 6 €", 79.0, self.S, False, {"BCN": {"name": "Barcelona"}})
        self.assertIn("58 €", txt)
        self.assertIn("Pologne", txt)
        self.assertIn("21 € de moins", txt)
        self.assertIn("ven. 5 mars", txt)


class FXTest(unittest.TestCase):
    def test_fee(self):
        self.assertAlmostEqual(FXR.effective_eur(425, "PLN", 2), 102.0)
        self.assertAlmostEqual(FXR.effective_eur(100, "EUR", 2), 100.0)
        self.assertIsNone(FXR.effective_eur(100, "XYZ", 2))


class Aviasales(unittest.TestCase):
    def test_parse(self):
        it = {"origin": "LYS", "destination": "BCN", "origin_airport": "LYS", "destination_airport": "BCN",
              "price": 54, "airline": "VY", "departure_at": "2027-03-05T07:15:00+01:00",
              "return_at": "2027-03-07T21:40:00+01:00", "transfers": 0, "return_transfers": 0,
              "link": "/search/LYS0503BCN07031"}
        x = parse_item(it, "fr", FXR, 2)
        self.assertEqual((x.out_date, x.ret_date, x.out_time, x.stops), ("2027-03-05", "2027-03-07", "07:15", 0))
        self.assertTrue(x.link.startswith("https://www.aviasales.com/"))


class FakeTP:
    enabled = True
    calls = 0
    errors = []

    def search(self, origin, dest, month, one_way, direct, market, fx, fee):
        self.calls += 1
        return [q(eur=66, source="aviasales"), q(eur=40, out="2027-03-03", ret="2027-03-05", source="aviasales")]


class FakeGoogle:
    available = True
    status = "ok"
    requests = 0
    max_requests = 80
    PRICES = {"fr": 72, "pl": 50, "hu": 69}

    def search(self, origin, dest, out_s, ret_s, market, direct, win, fx, fee):
        self.requests += 1
        eur = self.PRICES.get(market.code, 90)
        return Quote(origin, dest, out_s, ret_s, eur, market.currency, eur, market.code, "google")


class EndToEnd(unittest.TestCase):
    def test_process_alert(self):
        stats, res = {}, {}
        ctx = M.Ctx({"min_gain_eur": 15, "drop_pct": 5, "fx_fee_pct": 2, "markets_per_search": 3},
                    stats, FXR, FakeTP(), FakeGoogle(), {"BCN": {"country": "es", "name": "Barcelona"}}, TODAY)
        msg = M.process_alert(WEEKEND, res, ctx, budget=40)
        self.assertIsNotNone(msg)
        self.assertEqual(res["best"]["market"], "pl")      # 50 € en Pologne, 22 € de gain ≥ 15 €
        self.assertEqual(res["best"]["out_date"], "2027-03-05")  # le mercredi Aviasales est écarté
        self.assertIn("pl", stats["_all"])
        self.assertEqual(stats["_all"]["pl"]["wins"], stats["_all"]["pl"]["tries"])
        self.assertEqual(res["notified_eur"], 50)
        self.assertIn("explored_at", res)
        # Deuxième passage au même prix : pas de nouvelle notif.
        self.assertIsNone(M.process_alert(WEEKEND, res, ctx, budget=40))

    def test_small_gain_keeps_france(self):
        pool = M.eligible_quotes([q("fr", 72), q("hu", 69)], 15)
        self.assertEqual(pool[0].market, "fr")


class GoogleQuery(unittest.TestCase):
    def test_query_build_offline(self):
        from fast_flights import FlightQuery, Passengers, create_query
        qq = create_query(flights=[FlightQuery(date="2027-03-05", from_airport="LYS", to_airport="BCN"),
                                   FlightQuery(date="2027-03-07", from_airport="BCN", to_airport="LYS")],
                          trip="round-trip", passengers=Passengers(adults=1), language="en-GB", currency="PLN")
        p = qq.params()
        self.assertEqual(p["curr"], "PLN")
        self.assertTrue(p["tfs"])
        self.assertIn(MARKETS["pl"].gl, "PL")


if __name__ == "__main__":
    unittest.main()
