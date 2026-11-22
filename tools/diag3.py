"""Diagnostic : la page HTML contient-elle les vols les moins chers ? Comparaison avec l'appel interne trié par prix."""
import random, time
from fast_flights import FlightQuery, Passengers, ShoppingOptions, create_query, get_flights
from fast_flights.fetcher import URL, _build_default_client
from fast_flights.parser import parse

CONSENT = "CONSENT=YES+cb.20230810-00-p0.en+FX+874; SOCS=CAISHAgCEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiA_LyaBg"
client = _build_default_client()
for dst, day in (("BCN", "2026-12-03"), ("BCN", "2026-12-04"), ("AGP", "2026-12-04"), ("MAD", "2026-12-03")):
    q = create_query(flights=[FlightQuery(date=day, from_airport="LYS", to_airport=dst)], trip="one-way",
                     passengers=Passengers(adults=1), language="en-GB", currency="EUR")
    html = None
    for attempt in range(4):
        r = client.get(URL, params={**q.params(), "gl": "FR"}, headers={"cookie": CONSENT})
        try:
            html = parse(r.text)
            break
        except Exception:
            time.sleep(2)
    hp = sorted((f.price, f.airlines[0] if f.airlines else "", f.flights[0].departure.time, len(f.flights) - 1) for f in (html or []) if f.price)
    print(f"HTML {dst} {day} essais={attempt + 1} n={len(hp)} :", hp[:8])
    time.sleep(random.uniform(2, 3))
    try:
        rpc = get_flights(q, shopping=ShoppingOptions(ranking_mode="cheapest", result_sort="price"))
        rp = sorted((f.price, f.airlines[0] if f.airlines else "", f.flights[0].departure.time, len(f.flights) - 1) for f in rpc if f.price)
        print(f"RPC  {dst} {day} {rpc.diagnostics.status} n={len(rp)} :", rp[:8])
    except Exception as e:
        print("RPC erreur", e)
    time.sleep(random.uniform(2, 3))
