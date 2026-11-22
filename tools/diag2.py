"""Diagnostic : page HTML de Google Flights (GET) contre appel interne (POST), sur une même série de trajets."""
import random, time
from urllib.parse import urlencode
from fast_flights import FlightQuery, Passengers, create_query
from fast_flights.fetcher import URL, _build_default_client
from fast_flights.parser import parse

CONSENT = "CONSENT=YES+cb.20230810-00-p0.en+FX+874; SOCS=CAISHAgCEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiA_LyaBg"
client = _build_default_client()
trips = [("LYS", d, day) for d in ("BCN", "FCO", "AGP", "NCE", "LIS", "PRG") for day in ("2026-12-03", "2026-12-04")]
for lang in ("en-US", "en-GB"):
    for gl, cur in (("FR", "EUR"), ("PL", "PLN")):
        ok = 0
        for o, dst, day in trips[:6]:
            q = create_query(flights=[FlightQuery(date=day, from_airport=o, to_airport=dst)], trip="one-way",
                             passengers=Passengers(adults=1), language=lang, currency=cur)
            params = {**q.params(), "gl": gl}
            r = client.get(URL, params=params, headers={"cookie": CONSENT})
            try:
                fl = parse(r.text)
                ok += 1
                info = (len(fl), min(f.price for f in fl if f.price), fl[0].flights[0].departure.time)
            except Exception as e:
                info = f"{type(e).__name__}: {str(e)[:60]}"
            print(lang, gl, cur, dst, day, r.status_code, info)
            time.sleep(random.uniform(1.5, 3))
        print("==>", lang, gl, ok, "/ 6")
