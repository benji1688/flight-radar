"""Diagnostic : teste le moteur réel sur plusieurs dates Lyon–Madrid."""
import logging
from checker.fx import FX
from checker.markets import MARKETS
from checker.sources.google import GoogleFlights

logging.basicConfig(level=logging.WARNING)
fx = FX.load()
g = GoogleFlights(delay=(2, 4))
for out, ret in [("2026-12-04", "2026-12-07"), ("2026-12-10", "2026-12-13"), ("2026-12-11", "2026-12-14"), ("2026-12-17", "2026-12-20")]:
    q = g.search("LYS", "MAD", out, ret, MARKETS["fr"], False, None, fx, 2)
    print(out, ret, q and (q.price, q.airline, q.out_time, q.stops))
    q = g.search("LYS", "MAD", out, ret, MARKETS["pl"], False, None, fx, 2)
    print("  pl", q and (q.price, q.currency, round(q.eur, 1)))
print("statut", g.status, g.requests, "vides", g.empty)
