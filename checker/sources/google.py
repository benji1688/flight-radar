"""Google Flights via la bibliothèque open source faster-flights (pas de clé, usage perso).

Testé le 22/11/2026 : la page HTML ne montre pas les low-cost (Vueling, easyJet…), l'appel interne
trié par prix oui (Lyon–Barcelone vendredi : 37 € via l'appel interne, 101 € au mieux sur la page).

On passe par l'appel interne « GetShoppingResults » de Google Flights (tri par prix), plus fiable
que la lecture de la page HTML, et on remplace le pays (gl) pour simuler un achat depuis un autre pays.
Testé le 22/11/2026 : Lyon–Madrid sort à 159 € en France, 706 PLN en Pologne, 8 777 TRY en Turquie.
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlencode

from fast_flights import FlightQuery, Passengers, create_query
from fast_flights import shopping as S
from fast_flights.fetcher import URL, _build_default_client
from fast_flights.shopping_options import ShoppingOptions

from ..fx import FX
from ..markets import Market
from ..planner import Leg, in_window

log = logging.getLogger(__name__)

_orig_url = S._shopping_rpc_url
_orig_headers = S._shopping_rpc_headers
CHEAPEST = ShoppingOptions(ranking_mode="cheapest", result_sort="price")


def _hhmm(t) -> str | None:
    """Google donne l'heure sous forme [h] ou [h, m] (les minutes à zéro sont omises)."""
    if not t:
        return None
    return f"{t[0]:02d}:{(t[1] if len(t) > 1 else 0):02d}"


class Blocked(Exception):
    pass


class GoogleFlights:
    def __init__(self, max_requests: int = 80, delay: tuple[float, float] = (2.0, 5.0)):
        self.max_requests = max_requests
        self.delay = delay
        self.requests = 0
        self.status = "ok"
        self.empty = 0
        self.empty_streak = 0
        self.last_empty = False
        self.empty_ok = False   # devient vrai dès que Google renvoie des vols pendant ce passage
        self.client = None

    @property
    def available(self) -> bool:
        return self.status != "bloqué" and self.requests < self.max_requests

    def _rpc(self, legs, market: Market):
        """Appel interne GetShoppingResults avec le pays forcé. Réessaie sur réponse vide ; lève Blocked sur 403/429."""
        if self.client is None:
            self.client = _build_default_client()
            S._warmup_shopping_session(self.client, language="en-GB",
                                       cookie_header=_orig_headers(language="en-GB", currency="EUR")["cookie"])
        url = _orig_url(language=market.hl, currency=market.currency).replace("&gl=US", f"&gl={market.gl}")
        headers = _orig_headers(language=market.hl, currency=market.currency)
        headers["x-goog-ext-259736195-jspb"] = headers["x-goog-ext-259736195-jspb"].replace('"IE"', f'"{market.gl}"')
        body = S._encode_shopping_request(legs, [], 1, shopping=CHEAPEST).encode("utf-8")
        for attempt in range(3):
            if attempt:
                time.sleep(2.0 * (1.5 ** (attempt - 1)))
            try:
                res = self.client.post(url, headers=headers, content=body)
            except Exception as e:
                log.warning("Google Flights injoignable : %s", e)
                continue
            if res.status_code in (403, 429):
                # Google limite chaque adresse IP à une dizaine d'appels rapprochés : on s'arrête là,
                # le passage suivant tournera sur une autre machine GitHub (donc une autre IP).
                self.status = "bloqué"
                raise Blocked(f"HTTP {res.status_code}")
            if res.status_code != 200:
                return None
            flights = S._extract_full_flights_list(res.text, shopping=CHEAPEST, source="rpc")
            if flights:
                self.empty_streak = 0
                self.empty_ok = True   # Google répond : les réponses vides précédentes étaient réelles
                return flights
        self.empty += 1
        self.empty_streak += 1
        self.last_empty = True
        if self.empty_streak >= 3 and not self._canary():
            self.status = "bloqué"
            raise Blocked("réponses vides en série")
        return None

    def _canary(self) -> bool:
        """Plusieurs réponses vides d'affilée : vraie absence de vols ou blocage déguisé ?
        On teste une liaison toujours desservie (Paris → Londres). Si elle répond, Google fonctionne."""
        from datetime import date, timedelta
        day = (date.today() + timedelta(days=10)).isoformat()
        time.sleep(random.uniform(*self.delay))
        self.requests += 1
        legs = [FlightQuery(date=day, from_airport="CDG", to_airport="LHR")]
        url = _orig_url(language="en-GB", currency="EUR").replace("&gl=US", "&gl=FR")
        headers = _orig_headers(language="en-GB", currency="EUR")
        headers["x-goog-ext-259736195-jspb"] = headers["x-goog-ext-259736195-jspb"].replace('"IE"', '"FR"')
        body = S._encode_shopping_request(legs, [], 1, shopping=CHEAPEST).encode("utf-8")
        try:
            res = self.client.post(url, headers=headers, content=body)
            ok = res.status_code == 200 and bool(S._extract_full_flights_list(res.text, shopping=CHEAPEST, source="rpc"))
        except Exception:
            ok = False
        if ok:
            log.info("réponses vides mais Google répond sur Paris–Londres : absence réelle de vols")
            self.empty_streak = 0
            self.empty_ok = True
        return ok

    def search_leg(self, origin: str, destination: str, day: str, market: Market, direct: bool,
                   window: list | None, fx: FX, fee_pct: float) -> Leg | None:
        """Aller simple le moins cher à cette date, dans le créneau, vendu dans le pays `market`.

        Renvoie None s'il n'y a aucun vol compatible (ou pas de réponse).
        """
        if not self.available or not fx.has(market.currency):
            return None
        legs = [FlightQuery(date=day, from_airport=origin, to_airport=destination)]
        q = create_query(flights=legs, trip="one-way", seat="economy", passengers=Passengers(adults=1),
                         language=market.hl, currency=market.currency, max_stops=0 if direct else None)
        link = f"{URL}?{urlencode({**q.params(), 'gl': market.gl})}"

        if self.requests:
            time.sleep(random.uniform(*self.delay))
        self.requests += 1
        self.last_empty = False
        flights = self._rpc(legs, market)
        if not flights:
            return None

        best = None
        for f in flights:
            if not f.price or f.price <= 0 or not f.flights:
                continue
            dep = _hhmm(f.flights[0].departure.time)
            stops = len(f.flights) - 1
            if not in_window(dep, window) or (direct and stops):
                continue
            if best is None or f.price < best[0].price:
                best = (f, dep, stops)
        if best is None:
            return None
        f, dep, stops = best
        eur = fx.effective_eur(f.price, market.currency, fee_pct)
        if eur is None:
            return None
        return Leg(origin=origin, destination=destination, date=day, price=float(f.price),
                   currency=market.currency, eur=eur, market=market.code, source="google",
                   airline=", ".join(f.airlines[:2]), stops=stops, time=dep, link=link)
