"""Décide quels bons plans annoncer et rédige les messages Telegram."""

from __future__ import annotations

from datetime import date
from html import escape

from .markets import MARKETS
from .planner import Leg, Trip

DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MAX_DEALS_PER_MESSAGE = 6


def fmt_day(s: str) -> str:
    x = date.fromisoformat(s)
    return f"{DAYS[x.weekday()]} {x.day} {MONTHS[x.month]}"


def select_deals(alert: dict, trips: list[Trip], res: dict, settings: dict) -> list[tuple[Trip, str]]:
    """Bons plans à annoncer : une destination est annoncée quand elle passe sous le prix max,
    puis à chaque nouvelle baisse d'au moins `drop_pct` %. Seuls les prix vérifiés sur Google comptent."""
    if not alert.get("notify", True):
        return []
    notified: dict = res.setdefault("notified", {})
    max_price = alert.get("max_price")
    drop = settings.get("drop_pct", 5) / 100
    deals = []
    candidates = [t for t in trips if t.source == "google"]
    if max_price is None:
        candidates = candidates[:3]
    for t in candidates:
        key = f"{t.out.origin}>{t.out.destination}"
        prev = notified.get(key)
        if max_price is not None and t.eur > max_price:
            if prev is not None and t.eur > prev * 1.15:
                notified.pop(key)  # reparti à la hausse : la prochaine baisse sous le seuil sera annoncée
            continue
        if prev is None:
            reason = "nouveau" if max_price is None else f"sous {max_price:g} €"
        elif t.eur <= prev * (1 - drop):
            reason = f"−{round(prev - t.eur)} €"
        else:
            if t.eur > prev * 1.15:
                notified[key] = round(t.eur, 2)
            continue
        notified[key] = round(t.eur, 2)
        deals.append((t, reason))
    return deals[:MAX_DEALS_PER_MESSAGE]


def place(code: str, airports: dict) -> str:
    a = airports.get(code)
    name = a.get("name") if a else None
    return f"{escape(name)} ({code})" if name and name != code else code


def leg_line(arrow: str, leg: Leg, settings: dict) -> str:
    parts = [f"{arrow} {fmt_day(leg.date)}" + (f" {leg.time}" if leg.time else "")]
    if leg.airline:
        parts.append(escape(leg.airline))
    if leg.stops is not None:
        parts.append("direct" if leg.stops == 0 else f"{leg.stops} escale{'s' if leg.stops > 1 else ''}")
    parts.append(f"{round(leg.eur)} €")
    line = " · ".join(parts)
    if leg.market != "fr":
        m = MARKETS.get(leg.market)
        fee = f", frais {settings.get('fx_fee_pct', 2)} % inclus" if leg.currency != "EUR" else ""
        line += (f"\n   🌍 vendu en {m.name if m else leg.market.upper()} : "
                 f"{round(leg.price):,} {leg.currency}{fee}".replace(",", " "))
    if leg.link:
        label = "Google Flights" if leg.source == "google" else "Aviasales"
        line += f' · <a href="{escape(leg.link)}">{label}</a>'
    return line


def build_digest(alert: dict, deals: list[tuple[Trip, str]], res: dict, settings: dict, airports: dict) -> str:
    max_price = alert.get("max_price")
    head = f"✈️ <b>{len(deals)} bon{'s' if len(deals) > 1 else ''} plan{'s' if len(deals) > 1 else ''}"
    head += f" sous {max_price:g} €</b>" if max_price is not None else "</b>"
    lines = [head]
    foreign = False
    for i, (t, reason) in enumerate(deals, 1):
        lines.append("")
        lines.append(f"<b>{i}. {place(t.out.origin, airports)} → {place(t.out.destination, airports)} · "
                     f"{round(t.eur)} €</b> ({escape(reason)})")
        lines.append(leg_line("🛫", t.out, settings))
        if t.ret:
            nights = (date.fromisoformat(t.ret.date) - date.fromisoformat(t.out.date)).days
            lines.append(leg_line("🛬", t.ret, settings) + f" · {nights} nuit{'s' if nights > 1 else ''}")
        foreign = foreign or t.out.market != "fr" or (t.ret and t.ret.market != "fr")
    lines.append("")
    if any(t.ret for t, _ in deals):
        lines.append("ℹ️ Aller et retour sont deux billets séparés (souvent le moins cher en low-cost).")
    if foreign:
        lines.append("ℹ️ Achat depuis un autre pays : un VPN ou une adresse de facturation locale peuvent être demandés (à vérifier sur le site).")
    lines.append(f"#{alert['id']} · /voir {alert['id']} · /notif {alert['id']} off")
    return "\n".join(lines)


def is_quiet(settings: dict, hour: int) -> bool:
    quiet = settings.get("quiet")
    if not quiet:
        return False
    a, b = quiet
    return (a <= hour or hour < b) if a > b else (a <= hour < b)
