"""Pays de vente (« marchés ») simulés sur Google Flights, et classement appris au fil des recherches."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Market:
    code: str      # code interne (ISO pays en minuscules)
    gl: str        # paramètre pays de Google
    hl: str        # langue de Google
    currency: str
    name: str


MARKETS: dict[str, Market] = {m.code: m for m in [
    Market("fr", "FR", "fr", "EUR", "France"),
    Market("pl", "PL", "en-GB", "PLN", "Pologne"),
    Market("hu", "HU", "en-GB", "HUF", "Hongrie"),
    Market("tr", "TR", "en-GB", "TRY", "Turquie"),
    Market("in", "IN", "en-GB", "INR", "Inde"),
    Market("br", "BR", "en-GB", "BRL", "Brésil"),
    Market("mx", "MX", "en-GB", "MXN", "Mexique"),
    Market("cz", "CZ", "en-GB", "CZK", "Tchéquie"),
    Market("ro", "RO", "en-GB", "RON", "Roumanie"),
    Market("gb", "GB", "en-GB", "GBP", "Royaume-Uni"),
    Market("us", "US", "en-US", "USD", "États-Unis"),
    Market("ch", "CH", "en-GB", "CHF", "Suisse"),
    Market("es", "ES", "en-GB", "EUR", "Espagne"),
    Market("pt", "PT", "en-GB", "EUR", "Portugal"),
    Market("it", "IT", "en-GB", "EUR", "Italie"),
    Market("de", "DE", "en-GB", "EUR", "Allemagne"),
    Market("ma", "MA", "en-GB", "MAD", "Maroc"),
    Market("th", "TH", "en-GB", "THB", "Thaïlande"),
    Market("id", "ID", "en-GB", "IDR", "Indonésie"),
    Market("za", "ZA", "en-GB", "ZAR", "Afrique du Sud"),
]}

# Ordre de départ, avant que les statistiques ne prennent le relais :
# pays à monnaie faible / faible pouvoir d'achat, souvent cités comme moins chers.
# C'est une hypothèse de départ, le classement réel est appris par le moteur.
INITIAL_PRIORITY = ["pl", "hu", "tr", "in", "br", "mx", "cz", "ro", "es", "pt", "gb", "us"]


def _score(s: dict | None) -> float:
    """Taux de victoire lissé (une recherche gagnée sur deux par défaut)."""
    if not s:
        return 0.5
    return (s.get("wins", 0) + 0.5) / (s.get("tries", 0) + 1)


def rank_markets(stats: dict, route: str, dest_country: str | None, excluded: list[str]) -> list[str]:
    """Pays à tester en priorité pour une route, hors France (toujours testée en référence)."""
    route_stats = stats.get(route, {})
    all_stats = stats.get("_all", {})
    candidates = [c for c in MARKETS if c != "fr" and c not in excluded]

    def key(code: str) -> tuple:
        learned = 2 * _score(route_stats.get(code)) + _score(all_stats.get(code))
        tries = route_stats.get(code, {}).get("tries", 0) + all_stats.get(code, {}).get("tries", 0)
        bonus = 0.6 if code == dest_country else 0.0
        initial = INITIAL_PRIORITY.index(code) if code in INITIAL_PRIORITY else len(INITIAL_PRIORITY)
        # Sans données, on suit l'ordre initial ; avec des données, le score appris domine.
        if tries == 0:
            return (-(1.5 + bonus), initial)
        return (-(learned + bonus), initial)

    return sorted(candidates, key=key)


def record(stats: dict, route: str, market: str, won: bool, gain_eur: float) -> None:
    for scope in (route, "_all"):
        s = stats.setdefault(scope, {}).setdefault(market, {"tries": 0, "wins": 0, "gain_sum": 0.0})
        s["tries"] += 1
        if won:
            s["wins"] += 1
            s["gain_sum"] = round(s["gain_sum"] + gain_eur, 2)
