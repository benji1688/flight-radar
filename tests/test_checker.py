import unittest
from datetime import date

from checker import main as M
from checker.fx import FX
from checker.markets import MARKETS, rank_markets, record
from checker.notify import build_digest, is_quiet, select_deals
from checker.planner import Leg, Trip, best_trips, out_dates, out_ok, ret_dates, ret_ok
from checker.sources.travelpayouts import parse_item

TODAY = date(2026, 11, 22)
FXR = FX({"PLN": 4.25, "HUF": 400.0, "TRY": 40.0, "USD": 1.08, "GBP": 0.84, "INR": 100.0, "MXN": 20.0,
          "CZK": 25.0, "RON": 5.0, "BRL": 6.0, "CHF": 0.95, "MAD": 11.0, "THB": 38.0, "IDR": 17000.0, "ZAR": 20.0})

# Jeudi après 18 h ou vendredi après 12 h, retour samedi, dimanche ou lundi avant 6 h, déc.-janv., max 100 €.
FLEX = {"id": "a2", "origins": ["LYS"], "destinations": [], "date_from": "2026-12-01", "date_to": "2027-01-31",
        "months": ["2026-12", "2027-01"], "weekends": False, "nights": None, "one_way": False, "direct": False,
        "max_price": 100, "dep_window": None, "ret_window": None, "out_rules": {"3": [18, 24], "4": [12, 24]},
        "ret_rules": {"5": None, "6": None, "0": [0, 6]}, "out_dates": None, "ret_dates": None,
        "notify": True, "active": True}

# Nouvel an : aller le 30 ou 31/12, retour le 2 ou 3/01, sans horaire.
NYE = {"id": "a3", "origins": ["LYS"], "destinations": [], "date_from": "2026-12-30", "date_to": "2026-12-31",
       "months": [], "weekends": False, "nights": None, "one_way": False, "direct": False, "max_price": None,
       "dep_window": None, "ret_window": None, "out_rules": None, "ret_rules": None,
       "out_dates": ["2026-12-30", "2026-12-31"], "ret_dates": ["2027-01-02", "2027-01-03"],
       "notify": True, "active": True}

# Ancienne syntaxe (week-ends, 3 nuits, créneaux globaux).
LEGACY = {"id": "a1", "origins": ["LYS"], "destinations": ["MAD"], "date_from": "2026-11-26",
          "date_to": "2027-03-31", "months": [], "weekends": True, "nights": [3, 3], "one_way": False,
          "direct": False, "max_price": 120, "dep_window": [17, 23], "ret_window": [16, 23],
          "notify": True, "active": True}


def leg(o, dst, day, eur, t=None, market="fr", source="google", stops=0):
    return Leg(o, dst, day, eur, "EUR", eur, market, source, "easyJet", stops, t, "https://example.org")


class Rules(unittest.TestCase):
    def test_flex_dates(self):
        outs = out_dates(FLEX, TODAY)
        self.assertTrue(all(date.fromisoformat(x).weekday() in (3, 4) for x in outs))
        self.assertEqual(outs[0], "2026-12-03")
        rets = ret_dates(FLEX, outs)
        self.assertTrue(all(date.fromisoformat(x).weekday() in (5, 6, 0) for x in rets))

    def test_flex_windows(self):
        self.assertTrue(out_ok(FLEX, leg("LYS", "BCN", "2026-12-03", 40, "19:30"), TODAY))   # jeudi soir
        self.assertFalse(out_ok(FLEX, leg("LYS", "BCN", "2026-12-03", 40, "15:00"), TODAY))  # jeudi trop tôt
        self.assertTrue(out_ok(FLEX, leg("LYS", "BCN", "2026-12-04", 40, "13:00"), TODAY))   # vendredi aprem
        self.assertFalse(out_ok(FLEX, leg("LYS", "BCN", "2026-12-05", 40, "13:00"), TODAY))  # samedi exclu
        self.assertTrue(ret_ok(FLEX, leg("BCN", "LYS", "2026-12-07", 40, "05:30")))           # lundi 5 h 30
        self.assertFalse(ret_ok(FLEX, leg("BCN", "LYS", "2026-12-07", 40, "07:00")))          # lundi trop tard
        self.assertTrue(ret_ok(FLEX, leg("BCN", "LYS", "2026-12-06", 40, "22:00")))           # dimanche soir

    def test_pairs(self):
        outs = [leg("LYS", "BCN", "2026-12-03", 40, "19:30"), leg("LYS", "BCN", "2026-12-04", 30, "14:00")]
        rets = [leg("BCN", "LYS", "2026-12-07", 35, "05:30"), leg("BCN", "LYS", "2026-12-14", 10, "20:00")]
        trips = best_trips(FLEX, outs, rets)
        self.assertEqual((trips[0].out.date, trips[0].ret.date, trips[0].eur), ("2026-12-04", "2026-12-07", 65))
        self.assertNotIn("2026-12-14", [t.ret.date for t in trips])  # retour la semaine suivante exclu

    def test_nye(self):
        self.assertEqual(out_dates(NYE, TODAY), ["2026-12-30", "2026-12-31"])
        self.assertEqual(ret_dates(NYE, out_dates(NYE, TODAY)), ["2027-01-02", "2027-01-03"])

    def test_legacy(self):
        self.assertIn("2026-12-03", out_dates(LEGACY, TODAY))
        trips = best_trips(LEGACY, [leg("LYS", "MAD", "2026-12-03", 60, "19:00")],
                           [leg("MAD", "LYS", "2026-12-06", 50, "20:00"), leg("MAD", "LYS", "2026-12-07", 20, "20:00")])
        self.assertEqual([t.ret.date for t in trips], ["2026-12-06"])  # 3 nuits exactement


class Markets(unittest.TestCase):
    def test_learning_changes_order(self):
        stats = {}
        self.assertEqual(rank_markets(stats, "LYS-BCN", "es", [])[:2], ["es", "pl"])
        for _ in range(6):
            record(stats, "LYS-BCN", "ro", True, 12)
            record(stats, "LYS-BCN", "pl", False, 0)
        ranked = rank_markets(stats, "LYS-BCN", None, ["hu"])
        self.assertEqual(ranked[0], "ro")
        self.assertNotIn("hu", ranked)


class Notify(unittest.TestCase):
    S = {"drop_pct": 5, "fx_fee_pct": 2, "min_gain_eur": 15}

    def trip(self, dst, eur):
        return Trip(leg("LYS", dst, "2026-12-03", eur / 2, "19:00"), leg(dst, "LYS", "2026-12-06", eur / 2, "21:00"))

    def test_deals(self):
        res = {}
        deals = select_deals(FLEX, [self.trip("BCN", 70), self.trip("PRG", 140)], res, self.S)
        self.assertEqual([t.out.destination for t, _ in deals], ["BCN"])
        self.assertEqual(select_deals(FLEX, [self.trip("BCN", 69)], res, self.S), [])   # baisse < 5 %
        self.assertEqual(len(select_deals(FLEX, [self.trip("BCN", 60)], res, self.S)), 1)
        select_deals(FLEX, [self.trip("BCN", 130)], res, self.S)                          # remonte
        self.assertEqual(len(select_deals(FLEX, [self.trip("BCN", 95)], res, self.S)), 1)  # re-annoncé

    def test_aviasales_announced_as_estimate(self):
        t = Trip(leg("LYS", "BCN", "2026-12-03", 20, source="aviasales"), leg("BCN", "LYS", "2026-12-06", 20))
        deals = select_deals(FLEX, [t], {}, self.S)
        self.assertEqual(len(deals), 1)
        self.assertIn("estimation Aviasales", build_digest(FLEX, deals, {}, self.S, {}))

    def test_digest(self):
        t = Trip(Leg("LYS", "BCN", "2026-12-03", 120, "PLN", 28.8, "pl", "google", "Vueling", 0, "19:30", "https://x"),
                 leg("BCN", "LYS", "2026-12-07", 35, "05:30"))
        txt = build_digest(FLEX, [(t, "sous 100 €")], {}, self.S, {"BCN": {"name": "Barcelone"}})
        for s in ("Barcelone (BCN)", "64 €", "jeu. 3 déc. 19:30", "lun. 7 déc. 05:30", "Pologne", "4 nuits"):
            self.assertIn(s, txt)

    def test_quiet(self):
        self.assertTrue(is_quiet({"quiet": [23, 7]}, 2))
        self.assertFalse(is_quiet({"quiet": [23, 7]}, 12))


class Aviasales(unittest.TestCase):
    def test_parse(self):
        it = {"origin": "LYS", "destination": "BCN", "origin_airport": "LYS", "destination_airport": "BCN",
              "price": 54, "airline": "VY", "departure_at": "2027-03-05T07:15:00+01:00", "transfers": 0,
              "link": "/search/LYS0503BCN1"}
        x = parse_item(it, FXR, 2)
        self.assertEqual((x.date, x.time, x.stops, x.eur), ("2027-03-05", "07:15", 0, 54))


class FakeTP:
    enabled = True
    token = "t"
    calls = 0
    errors = []

    def one_way(self, origin, dest, month, direct, fx, fee):
        self.calls += 1
        if origin == "LYS" and month == "2026-12":
            return [leg("LYS", "BCN", "2026-12-03", 25, "19:00", source="aviasales"),
                    leg("LYS", "PRG", "2026-12-04", 30, "15:00", source="aviasales"),
                    leg("LYS", "BCN", "2026-12-03", 15, "09:00", source="aviasales")]   # hors créneau
        if origin in ("BCN", "PRG") and month == "2026-12":
            return [leg(origin, "LYS", "2026-12-06", 30, "21:00", source="aviasales")]
        return []


class FakeGoogle:
    """Barcelone pas cher le jeudi soir et le dimanche ; la Pologne bat la France de 20 € sur l'aller."""
    status = "ok"
    empty = 0
    max_requests = 300

    def __init__(self):
        self.requests = 0
        self.calls = []

    @property
    def available(self):
        return self.requests < self.max_requests

    def search_leg(self, o, dst, day, market, direct, window, fx, fee, max_layover=None):
        self.requests += 1
        self.calls.append((o, dst, day, market.code))
        wd = date.fromisoformat(day).weekday()
        if dst == "BCN" and wd == 3:
            eur = 45 if market.code == "fr" else (25 if market.code == "pl" else 50)
            return leg(o, dst, day, eur, "19:30", market=market.code)
        if o == "BCN" and wd == 6:
            return leg(o, dst, day, 30, "21:00", market=market.code)
        if dst == "PRG" or o == "PRG":
            return leg(o, dst, day, 150, "16:00", market=market.code)
        return None


class EndToEnd(unittest.TestCase):
    def ctx(self, google):
        return M.Ctx({"min_gain_eur": 15, "drop_pct": 5, "fx_fee_pct": 2, "markets_per_search": 3},
                     {}, FXR, FakeTP(), google, {"BCN": {"country": "es", "name": "Barcelone"}}, TODAY)

    def test_flex_partout(self):
        g = FakeGoogle()
        ctx = self.ctx(g)
        res = {}
        msgs = [M.process_alert(FLEX, res, ctx, budget=120) for _ in range(6)]
        self.assertTrue(any(msgs))
        first = next(m for m in msgs if m)["text"]
        self.assertIn("Barcelone (BCN)", first)
        self.assertEqual(res["best"]["destination"], "BCN")
        self.assertEqual(res["best"]["out_market"], "pl")       # 25 € en Pologne contre 45 € en France
        self.assertEqual(res["best"]["eur"], 55)
        # Prague (aller à 150 €) est abandonnée : pas de recherche de retours inutiles
        self.assertFalse(any(c[0] == "PRG" for c in g.calls))
        # Destinations repérées par Aviasales cherchées en premier
        self.assertEqual(g.calls[0][1], "BCN")

    def test_nye_without_max(self):
        g = FakeGoogle()
        M.process_alert(NYE, {}, self.ctx(g), budget=60)
        self.assertTrue(g.calls)
        self.assertTrue(all(c[2] in ("2026-12-30", "2026-12-31", "2027-01-02", "2027-01-03") for c in g.calls))

    def test_store_pruned(self):
        res = {"legs": {"LYS>BCN@2026-11-01": {"at": "2026-10-01T00:00:00+00:00", "fr": None}}}
        M.process_alert(FLEX, res, self.ctx(FakeGoogle()), budget=4)
        self.assertNotIn("LYS>BCN@2026-11-01", res["legs"])


class Layover(unittest.TestCase):
    def test_longest_layover(self):
        from types import SimpleNamespace as N
        from checker.sources.google import longest_layover
        dt = lambda d, t: N(date=d, time=t)
        seg = lambda dep, arr: N(departure=dep, arrival=arr)
        two = [seg(dt((2026, 12, 3), (19, 0)), dt((2026, 12, 3), (20, 30))),
               seg(dt((2026, 12, 3), (22,)), dt((2026, 12, 3), (23, 50)))]
        self.assertEqual(longest_layover(two), 90)
        night = [seg(dt((2026, 12, 3), (21, 0)), dt((2026, 12, 3), (22, 0))),
                 seg(dt((2026, 12, 4), (6, 30)), dt((2026, 12, 4), (8, 0)))]
        self.assertEqual(longest_layover(night), 510)

    def test_domestic_excluded(self):
        g = FakeGoogle()
        ctx = M.Ctx({"min_gain_eur": 15}, {}, FXR, FakeTP(), g,
                    {"LYS": {"country": "fr"}, "NCE": {"country": "fr"}, "BCN": {"country": "es"}}, TODAY)
        M.process_alert(FLEX, {}, ctx, budget=30)
        self.assertFalse(any(c[1] == "NCE" for c in g.calls))


class GoogleQuery(unittest.TestCase):
    def test_query_build_offline(self):
        from fast_flights import FlightQuery, Passengers, create_query
        q = create_query(flights=[FlightQuery(date="2027-03-05", from_airport="LYS", to_airport="BCN")],
                         trip="one-way", passengers=Passengers(adults=1), language="en-GB", currency="PLN")
        self.assertEqual(q.params()["curr"], "PLN")
        self.assertEqual(MARKETS["pl"].gl, "PL")


if __name__ == "__main__":
    unittest.main()


class MainLoop(unittest.TestCase):
    def test_main_with_fake_relay(self):
        import os
        from unittest import mock
        saved = {}

        class FakeRelay:
            def __init__(self, *a):
                pass

            def state(self):
                return {"owner": 1, "alerts": [FLEX, NYE], "settings": {"min_gain_eur": 15}, "results": {},
                        "stats": {}, "run": None}

            def legs(self, alert_id):
                return {}

            def save_legs(self, alert_id, data):
                saved[alert_id] = data

            def save(self, results, stats, run):
                saved["results"], saved["run"] = results, run

            def notify(self, messages):
                saved["messages"] = messages

        g = FakeGoogle()
        with mock.patch.object(M, "Relay", FakeRelay), mock.patch.object(M, "GoogleFlights", lambda **k: g), \
                mock.patch.object(M, "Travelpayouts", lambda tok: FakeTP()), \
                mock.patch.object(M.FX, "load", classmethod(lambda cls: FXR)), \
                mock.patch.object(M, "load_airports", lambda: {}), \
                mock.patch.object(M, "paris_now", lambda: __import__("datetime").datetime(2026, 11, 22, 12)), \
                mock.patch.dict(os.environ, {"WORKER_URL": "https://x", "API_KEY": "k" * 24}):
            self.assertEqual(M.main(), 0)
        self.assertIn("legs", saved["a2"])
        self.assertNotIn("legs", saved["results"]["a2"])   # la mémoire détaillée est stockée à part
        self.assertEqual(saved["run"]["alerts_checked"], 2)
