"""Aviasales / Travelpayouts : prix en cache (2 à 7 jours), gratuits, idéaux pour balayer large.

Doc : https://support.travelpayouts.com/hc/en-us/articles/203956163
"""

from __future__ import annotations

import logging

import requests

from ..fx import FX
from ..planner import Quote

log = logging.getLogger(__name__)

API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AIRPORTS = "https://api.travelpayouts.com/data/en/airports.json"


class Travelpayouts:
    def __init__(self, token: str | None, max_calls: int = 300):
        self.token = token
        self.max_calls = max_calls
        self.calls = 0
        self.errors: list[str] = []

    @property
    def enabled(self) -> bool:
        return bool(self.token) and self.calls < self.max_calls

    def search(self, origin: str, destination: str | None, month: str, one_way: bool,
               direct: bool, market: str, fx: FX, fee_pct: float) -> list[Quote]:
        if not self.enabled:
            return []
        params = {
            "origin": origin,
            "departure_at": month,
            "one_way": "true" if one_way else "false",
            "direct": "true" if direct else "false",
            "currency": "eur",
            "market": market,
            "sorting": "price",
            "unique": "false",
            "limit": 1000,
            "page": 1,
            "token": self.token,
        }
        if destination:
            params["destination"] = destination
        self.calls += 1
        try:
            r = requests.get(API, params=params, timeout=30)
            if r.status_code == 401:
                self.errors.append("Token Travelpayouts refusé (vérifie le secret TRAVELPAYOUTS_TOKEN)")
                self.token = None
                return []
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            log.warning("Aviasales %s→%s %s : %s", origin, destination, month, e)
            return []
        if not payload.get("success", True):
            log.warning("Aviasales a répondu une erreur : %s", payload.get("error"))
            return []
        return [q for q in (parse_item(it, market, fx, fee_pct) for it in payload.get("data") or []) if q]


def parse_item(it: dict, market: str, fx: FX, fee_pct: float) -> Quote | None:
    try:
        out_at = it["departure_at"]
        ret_at = it.get("return_at") or None
        price = float(it["price"])
    except (KeyError, TypeError, ValueError):
        return None
    eur = fx.effective_eur(price, "EUR", fee_pct)
    transfers = it.get("transfers")
    back = it.get("return_transfers")
    stops = None
    if transfers is not None:
        stops = max(int(transfers), int(back or 0))
    link = it.get("link") or ""
    if link.startswith("/"):
        link = "https://www.aviasales.com" + link
    return Quote(
        origin=it.get("origin_airport") or it.get("origin", ""),
        destination=it.get("destination_airport") or it.get("destination", ""),
        out_date=out_at[:10],
        ret_date=ret_at[:10] if ret_at else None,
        price=price,
        currency="EUR",
        eur=eur,
        market=market,
        source="aviasales",
        airline=it.get("airline", ""),
        stops=stops,
        out_time=out_at[11:16] if len(out_at) >= 16 else None,
        ret_time=ret_at[11:16] if ret_at and len(ret_at) >= 16 else None,
        link=link,
    )


def load_airports() -> dict[str, dict]:
    """Code aéroport → {name, country}. Utilisé pour deviner le pays de la destination."""
    try:
        r = requests.get(AIRPORTS, timeout=30)
        r.raise_for_status()
        return {a["code"]: {"name": a.get("name") or a.get("code"), "country": (a.get("country_code") or "").lower(),
                            "city": a.get("city_code")} for a in r.json() if a.get("code")}
    except Exception as e:
        log.warning("liste des aéroports indisponible : %s", e)
        return {}
