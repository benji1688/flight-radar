"""Google Flights via la bibliothèque open source faster-flights (pas de clé, usage perso).

On ajoute nous-mêmes le paramètre `gl` (pays) à la requête pour simuler un achat depuis un autre pays.
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlencode

from fast_flights import FlightQuery, Passengers, create_query
from fast_flights.fetcher import URL, _build_default_client
from fast_flights.parser import parse

from ..fx import FX
from ..markets import Market
from ..planner import Quote, in_window

log = logging.getLogger(__name__)

CONSENT = ("CONSENT=YES+cb.20230810-00-p0.en+FX+874; "
           "SOCS=CAISHAgCEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiA_LyaBg")


class Blocked(Exception):
    pass


class GoogleFlights:
    def __init__(self, max_requests: int = 80, delay: tuple[float, float] = (2.0, 5.0)):
        self.max_requests = max_requests
        self.delay = delay
        self.requests = 0
        self.status = "ok"
        self.client = None

    @property
    def available(self) -> bool:
        return self.status != "bloqué" and self.requests < self.max_requests

    def search(self, origin: str, destination: str, out_date: str, ret_date: str | None, market: Market,
               direct: bool, dep_window: list | None, fx: FX, fee_pct: float) -> Quote | None:
        """Prix le moins cher pour une combinaison précise, vendu dans le pays `market`."""
        if not self.available:
            return None
        if not fx.has(market.currency):
            return None
        legs = [FlightQuery(date=out_date, from_airport=origin, to_airport=destination)]
        if ret_date:
            legs.append(FlightQuery(date=ret_date, from_airport=destination, to_airport=origin))
        q = create_query(
            flights=legs,
            trip="round-trip" if ret_date else "one-way",
            seat="economy",
            passengers=Passengers(adults=1),
            language=market.hl,
            currency=market.currency,
            max_stops=0 if direct else None,
        )
        params = {**q.params(), "gl": market.gl}
        link = f"{URL}?{urlencode(params)}"

        if self.requests:
            time.sleep(random.uniform(*self.delay))
        self.requests += 1
        if self.client is None:
            self.client = _build_default_client()
        try:
            res = self.client.get(URL, params=params, headers={"cookie": CONSENT})
        except Exception as e:
            log.warning("Google Flights injoignable : %s", e)
            return None
        if res.status_code in (403, 429):
            self.status = "bloqué"
            raise Blocked(f"HTTP {res.status_code}")
        if res.status_code != 200:
            log.warning("Google Flights HTTP %s pour %s→%s %s", res.status_code, origin, destination, out_date)
            return None
        try:
            flights = parse(res.text)
        except Exception as e:
            log.warning("réponse Google illisible (%s→%s %s, %s) : %s", origin, destination, out_date, market.code, e)
            self.status = "format changé ?"
            return None

        best = None
        for f in flights:
            if not f.price or f.price <= 0 or not f.flights:
                continue
            first = f.flights[0]
            dep = f"{first.departure.time[0]:02d}:{first.departure.time[1]:02d}" if first.departure.time else None
            if not in_window(dep, dep_window):
                continue
            stops = len(f.flights) - 1
            if direct and stops:
                continue
            if best is None or f.price < best[0].price:
                best = (f, dep, stops)
        if best is None:
            return None
        f, dep, stops = best
        eur = fx.effective_eur(f.price, market.currency, fee_pct)
        if eur is None:
            return None
        return Quote(
            origin=origin, destination=destination, out_date=out_date, ret_date=ret_date,
            price=float(f.price), currency=market.currency, eur=eur, market=market.code, source="google",
            airline=", ".join(f.airlines[:2]), stops=stops, out_time=dep, link=link,
        )
