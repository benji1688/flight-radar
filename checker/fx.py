"""Taux de change du jour (BCE via Frankfurter, complété par open.er-api.com pour les devises absentes)."""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

SOURCES = [
    ("https://api.frankfurter.dev/v1/latest?base=EUR", "rates"),
    ("https://api.frankfurter.app/latest?from=EUR", "rates"),
    ("https://open.er-api.com/v6/latest/EUR", "rates"),
]


class FX:
    def __init__(self, rates: dict[str, float]):
        self.rates = {"EUR": 1.0, **rates}

    @classmethod
    def load(cls) -> "FX":
        rates: dict[str, float] = {}
        for url, field in SOURCES:
            try:
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                for cur, val in (r.json().get(field) or {}).items():
                    rates.setdefault(cur.upper(), float(val))
            except Exception as e:  # une source en panne ne bloque pas les autres
                log.warning("taux de change indisponibles sur %s : %s", url, e)
        return cls(rates)

    def has(self, currency: str) -> bool:
        return currency.upper() in self.rates

    def to_eur(self, amount: float, currency: str) -> float | None:
        rate = self.rates.get(currency.upper())
        if not rate:
            return None
        return amount / rate

    def effective_eur(self, amount: float, currency: str, fee_pct: float) -> float | None:
        """Prix en euros tel que débité sur ta carte (frais de change inclus hors euro)."""
        eur = self.to_eur(amount, currency)
        if eur is None:
            return None
        if currency.upper() != "EUR":
            eur *= 1 + fee_pct / 100
        return eur
