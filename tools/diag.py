"""Diagnostic : teste le moteur réel sur Lyon–Madrid (Google multi-pays + Aviasales)."""
import logging, os
from checker.fx import FX
from checker.markets import MARKETS
from checker.sources.google import GoogleFlights

logging.basicConfig(level=logging.INFO)
fx = FX.load()
g = GoogleFlights(delay=(1, 2))
for code in ["fr", "pl", "hu", "tr", "in", "br", "mx", "es", "gb"]:
    q = g.search("LYS", "MAD", "2026-12-03", "2026-12-06", MARKETS[code], False, None, fx, 2)
    print(code, q and (q.price, q.currency, round(q.eur, 2), q.airline, q.out_time, q.stops))
q = g.search("LYS", "MAD", "2026-12-03", "2026-12-06", MARKETS["fr"], False, [17, 23], fx, 2)
print("fr soir", q and (q.price, q.out_time, q.airline))
q = g.search("LYS", "MAD", "2026-12-03", None, MARKETS["fr"], True, None, fx, 2)
print("fr aller simple direct", q and (q.price, q.out_time, q.airline, q.stops))
print("statut", g.status, g.requests)
