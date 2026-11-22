"""Diagnostic : fait tourner le vrai moteur sur deux alertes d'exemple, sans toucher au bot."""
import logging, os
from checker import main as M
from checker.fx import FX
from checker.planner import paris_now
from checker.sources.google import GoogleFlights
from checker.sources.travelpayouts import Travelpayouts, load_airports

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("primp").setLevel(logging.WARNING)
FLEX = {"id": "t1", "origins": ["LYS"], "destinations": [], "date_from": "2026-12-01", "date_to": "2027-01-31",
        "months": ["2026-12", "2027-01"], "weekends": False, "nights": None, "one_way": False, "direct": False,
        "max_price": 100, "dep_window": None, "ret_window": None, "out_rules": {"3": [18, 24], "4": [12, 24]},
        "ret_rules": {"5": None, "6": None, "0": [0, 6]}, "out_dates": None, "ret_dates": None, "notify": True}
NYE = {"id": "t2", "origins": ["LYS"], "destinations": [], "date_from": "2026-12-30", "date_to": "2026-12-31",
       "months": [], "weekends": False, "nights": None, "one_way": False, "direct": False, "max_price": None,
       "dep_window": None, "ret_window": None, "out_rules": None, "ret_rules": None,
       "out_dates": ["2026-12-30", "2026-12-31"], "ret_dates": ["2027-01-02", "2027-01-03"], "notify": True}
g = GoogleFlights(max_requests=int(os.environ.get("N", "70")), delay=(1.5, 3.0))
ctx = M.Ctx({"min_gain_eur": 15, "drop_pct": 5, "fx_fee_pct": 2, "markets_per_search": 2}, {}, FX.load(),
            Travelpayouts(os.environ.get("TRAVELPAYOUTS_TOKEN")), g, load_airports(), paris_now().date())
for alert, budget in ((FLEX, 45), (NYE, 25)):
    res = {}
    msg = M.process_alert(alert, res, ctx, budget)
    print("=====", alert["id"], res.get("coverage"), "TP dests:", list((res.get("tp") or {}).get("score", {}).items())[:12])
    for t in res.get("top", []):
        print(f"  {t['eur']:>7} {t['source']:<9} {t['origin']}>{t['destination']} {t['out_date']} {t['out_time']} {t['out_airline']} {t.get('out_market')}"
              f" | {t['ret_date']} {t['ret_time']} {t['ret_airline']} {t.get('ret_market')}")
    if msg:
        print(msg["text"])
print("google", g.requests, g.status, "vides", g.empty)
