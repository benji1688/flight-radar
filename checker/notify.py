"""Décide quand prévenir et rédige les messages Telegram."""

from __future__ import annotations

from datetime import date
from html import escape
from statistics import median

from .markets import MARKETS
from .planner import Quote

DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def fmt_day(s: str) -> str:
    x = date.fromisoformat(s)
    return f"{DAYS[x.weekday()]} {x.day} {MONTHS[x.month]}"


def should_notify(alert: dict, best_eur: float, res: dict, settings: dict) -> tuple[bool, str]:
    """(prévenir ?, raison). Met à jour le prix de référence quand il remonte nettement."""
    if not alert.get("notify", True):
        return False, "notifs coupées"
    max_price = alert.get("max_price")
    if max_price is not None and best_eur > max_price:
        prev = res.get("notified_eur")
        if prev is not None and best_eur > prev * 1.15:
            res["notified_eur"] = None  # le prix est reparti à la hausse : la prochaine baisse sous le seuil re-préviendra
        return False, "au-dessus du prix max"
    prev = res.get("notified_eur")
    if prev is None:
        return True, "premier prix sous ton seuil" if max_price is not None else "premier prix trouvé"
    drop = settings.get("drop_pct", 5) / 100
    if best_eur <= prev * (1 - drop):
        return True, f"baisse de {round(prev - best_eur)} €"
    if best_eur > prev * 1.15:
        res["notified_eur"] = best_eur  # nouvelle référence plus haute, sans notif
    return False, "pas de baisse suffisante"


def is_deal(best_eur: float, history: list) -> bool:
    prices = [p for _, p in history[-30:]]
    return len(prices) >= 5 and best_eur < 0.8 * median(prices)


def build_message(alert: dict, q: Quote, reason: str, fr_eur: float | None, settings: dict,
                  deal: bool, airports: dict) -> str:
    def place(code: str) -> str:
        a = airports.get(code)
        return f"{code} ({escape(a['name'])})" if a and a.get("name") and a["name"] != code else code

    head = "🔥 <b>Prix anormalement bas</b>\n" if deal else ""
    lines = [f"{head}✈️ <b>{place(q.origin)} → {place(q.destination)} · {round(q.eur)} €</b>"]
    if q.ret_date:
        nights = (date.fromisoformat(q.ret_date) - date.fromisoformat(q.out_date)).days
        t_out = f" {q.out_time}" if q.out_time else ""
        t_ret = f" {q.ret_time}" if q.ret_time else ""
        lines.append(f"📅 {fmt_day(q.out_date)}{t_out} → {fmt_day(q.ret_date)}{t_ret} ({nights} nuit{'s' if nights > 1 else ''})")
    else:
        lines.append(f"📅 {fmt_day(q.out_date)}{' ' + q.out_time if q.out_time else ''} · aller simple")
    detail = []
    if q.airline:
        detail.append(escape(q.airline))
    if q.stops is not None:
        detail.append("direct" if q.stops == 0 else f"{q.stops} escale{'s' if q.stops > 1 else ''}")
    if detail:
        lines.append("🛫 " + " · ".join(detail))
    if q.market != "fr" and fr_eur is not None:
        m = MARKETS.get(q.market)
        fee = f", frais {settings.get('fx_fee_pct', 2)} % inclus" if q.currency != "EUR" else ""
        lines.append(f"🌍 Vendu en {m.name if m else q.market.upper()} : {round(q.price):,} {q.currency}".replace(",", " ")
                     + f" ≈ {round(q.eur)} €{fee}, soit {round(fr_eur - q.eur)} € de moins qu'en France ({round(fr_eur)} €)")
        lines.append("   Réservation : un VPN ou une adresse de facturation locale peuvent être demandés (à vérifier sur le site).")
    if q.source == "aviasales":
        lines.append("ℹ️ Prix Aviasales en cache, à confirmer sur le site")
    lines.append(f"💡 {escape(reason)}")
    if q.link:
        label = "Google Flights" if q.source == "google" else "Aviasales"
        lines.append(f'🔗 <a href="{escape(q.link)}">Voir sur {label}</a>')
    lines.append(f"#{alert['id']} · /voir {alert['id']} · /notif {alert['id']} off")
    return "\n".join(lines)


def is_quiet(settings: dict, hour: int) -> bool:
    quiet = settings.get("quiet")
    if not quiet:
        return False
    a, b = quiet
    return (a <= hour or hour < b) if a > b else (a <= hour < b)
