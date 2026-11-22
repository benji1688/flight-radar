"""Aviasales / Travelpayouts : prix en cache (2 à 7 jours), gratuits, idéaux pour repérer les destinations.

Doc : https://support.travelpayouts.com/hc/en-us/articles/203956163
Le cache est le même quel que soit le marché demandé (vérifié le 22/11/2026), on interroge donc « fr ».
"""

from __future__ import annotations

import logging

import requests

from ..fx import FX
from ..planner import Leg

log = logging.getLogger(__name__)

API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AIRPORTS = "https://api.travelpayouts.com/data/fr/airports.json"
CITIES = "https://api.travelpayouts.com/data/fr/cities.json"


class Travelpayouts:
    def __init__(self, token: str | None, max_calls: int = 300):
        self.token = token
        self.max_calls = max_calls
        self.calls = 0
        self.errors: list[str] = []

    @property
    def enabled(self) -> bool:
        return bool(self.token) and self.calls < self.max_calls

    def one_way(self, origin: str, destination: str | None, month: str, direct: bool,
                fx: FX, fee_pct: float) -> list[Leg]:
        """Allers simples en cache pour un mois (destination None = toutes les destinations)."""
        if not self.enabled:
            return []
        params = {
            "origin": origin, "departure_at": month, "one_way": "true",
            "direct": "true" if direct else "false", "currency": "eur", "market": "fr",
            "sorting": "price", "unique": "false", "limit": 1000, "page": 1, "token": self.token,
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
        return [x for x in (parse_item(it, fx, fee_pct) for it in payload.get("data") or []) if x]


def parse_item(it: dict, fx: FX, fee_pct: float) -> Leg | None:
    try:
        out_at = it["departure_at"]
        price = float(it["price"])
    except (KeyError, TypeError, ValueError):
        return None
    link = it.get("link") or ""
    if link.startswith("/"):
        link = "https://www.aviasales.com" + link
    transfers = it.get("transfers")
    return Leg(
        origin=it.get("origin_airport") or it.get("origin", ""),
        destination=it.get("destination_airport") or it.get("destination", ""),
        date=out_at[:10], price=price, currency="EUR", eur=fx.effective_eur(price, "EUR", fee_pct),
        market="fr", source="aviasales", airline=it.get("airline", ""),
        stops=int(transfers) if transfers is not None else None,
        time=out_at[11:16] if len(out_at) >= 16 else None, link=link,
    )


def load_airports() -> dict[str, dict]:
    """Code aéroport → {name, city, country}, en français. Sert aux messages et au pays de destination."""
    try:
        cities = {c["code"]: c.get("name") or c["code"] for c in requests.get(CITIES, timeout=30).json() if c.get("code")}
    except Exception as e:
        log.warning("liste des villes indisponible : %s", e)
        cities = {}
    try:
        out = {}
        for a in requests.get(AIRPORTS, timeout=30).json():
            if not a.get("code"):
                continue
            city_code = a.get("city_code") or a["code"]
            out[a["code"]] = {"name": cities.get(city_code) or a.get("name") or a["code"],
                              "city": city_code, "country": (a.get("country_code") or "").lower(),
                              "flightable": a.get("flightable", True), "iata_type": a.get("iata_type")}
        return out
    except Exception as e:
        log.warning("liste des aéroports indisponible : %s", e)
        return {}
