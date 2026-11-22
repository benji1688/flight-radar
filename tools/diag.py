"""Diagnostic ponctuel : teste les différentes façons d'interroger Google Flights et Aviasales."""
import os, traceback
from unittest import mock

import requests
from fast_flights import FlightQuery, Passengers, ShoppingOptions, create_query, get_flights
from fast_flights import shopping as S

OUT, RET = "2026-12-03", "2026-12-06"
legs = [FlightQuery(date=OUT, from_airport="LYS", to_airport="MAD"),
        FlightQuery(date=RET, from_airport="MAD", to_airport="LYS")]


def show(label, fn):
    try:
        res = fn()
        prices = sorted(f.price for f in res if f.price)
        d = getattr(res, "diagnostics", None)
        print(f"{label}: {len(res)} vols, prix min {prices[:3]}, diag={d}")
        if res:
            f = res[0]
            print("   ex:", f.airlines, f.price, [(s.from_airport.code, s.to_airport.code, s.departure.date, s.departure.time) for s in f.flights])
    except Exception as e:
        print(f"{label}: ERREUR {type(e).__name__}: {e}")


def q(lang, curr, trip="round-trip"):
    return create_query(flights=legs if trip == "round-trip" else legs[:1], trip=trip,
                        passengers=Passengers(adults=1), language=lang, currency=curr)


show("A html en-US/USD", lambda: get_flights(q("en-US", "USD")))
show("B html fr/EUR", lambda: get_flights(q("fr", "EUR")))
show("C rpc fr/EUR cheapest", lambda: get_flights(q("fr", "EUR"), shopping=ShoppingOptions(ranking_mode="cheapest", result_sort="price")))
show("C2 rpc en-GB/EUR one-way", lambda: get_flights(q("en-GB", "EUR", "one-way"), shopping=ShoppingOptions(ranking_mode="cheapest", result_sort="price")))

orig_url, orig_headers = S._shopping_rpc_url, S._shopping_rpc_headers
for gl, curr in [("FR", "EUR"), ("PL", "PLN"), ("TR", "TRY"), ("IN", "INR")]:
    def url(**kw):
        return orig_url(**kw).replace("&gl=US", f"&gl={gl}")
    def headers(**kw):
        h = orig_headers(**kw)
        h["x-goog-ext-259736195-jspb"] = h["x-goog-ext-259736195-jspb"].replace('"IE"', f'"{gl}"')
        return h
    with mock.patch.object(S, "_shopping_rpc_url", url), mock.patch.object(S, "_shopping_rpc_headers", headers):
        show(f"D rpc gl={gl}/{curr}", lambda: get_flights(q("en-GB", curr), shopping=ShoppingOptions(ranking_mode="cheapest", result_sort="price")))

tok = os.environ.get("TRAVELPAYOUTS_TOKEN")
for market in ["fr", "pl", "de", "es"]:
    for month in ["2026-12", "2027-01"]:
        try:
            r = requests.get("https://api.travelpayouts.com/aviasales/v3/prices_for_dates", timeout=30, params={
                "origin": "LYS", "destination": "MAD", "departure_at": month, "one_way": "false", "currency": "eur",
                "market": market, "sorting": "price", "unique": "false", "limit": 1000, "token": tok})
            j = r.json()
            data = j.get("data") or []
            print(f"TP {market} {month}: HTTP {r.status_code} success={j.get('success')} n={len(data)} err={j.get('error')}")
            for it in data[:4]:
                print("   ", {k: it.get(k) for k in ("origin_airport", "destination_airport", "price", "departure_at", "return_at", "transfers", "return_transfers", "airline")})
        except Exception:
            traceback.print_exc()
