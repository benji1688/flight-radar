"""Transforme une alerte en combinaisons de dates à chercher et filtre les résultats selon ses critères."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

# Week-end : départ jeudi, vendredi ou samedi ; retour samedi, dimanche ou lundi.
WEEKEND_OUT = {3, 4, 5}
WEEKEND_RET = {5, 6, 0}


@dataclass
class Quote:
    origin: str
    destination: str
    out_date: str
    ret_date: str | None
    price: float          # dans la devise d'origine
    currency: str
    eur: float            # prix effectif en euros (frais de change inclus)
    market: str           # pays de vente
    source: str           # "google" ou "aviasales"
    airline: str = ""
    stops: int | None = None
    out_time: str | None = None   # "HH:MM"
    ret_time: str | None = None
    link: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def combo(self) -> tuple:
        return (self.origin, self.destination, self.out_date, self.ret_date)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["eur"] = round(self.eur, 2)
        return d


def d(s: str) -> date:
    return date.fromisoformat(s[:10])


def months_ok(alert: dict, day: date) -> bool:
    months = alert.get("months") or []
    return not months or day.strftime("%Y-%m") in months


def in_window(hhmm: str | None, window: list | None) -> bool:
    if not window or not hhmm:
        return True
    h = int(hhmm[:2]) + int(hhmm[3:5]) / 60
    return window[0] <= h <= window[1]


def date_ok(alert: dict, out_s: str, ret_s: str | None, today: date) -> bool:
    out = d(out_s)
    if out < today or out < d(alert["date_from"]) or out > d(alert["date_to"]):
        return False
    if not months_ok(alert, out):
        return False
    if alert.get("one_way"):
        return ret_s is None
    if ret_s is None:
        return False
    ret = d(ret_s)
    nights = (ret - out).days
    lo, hi = alert.get("nights") or [1, 30]
    if not lo <= nights <= hi:
        return False
    if alert.get("weekends") and (out.weekday() not in WEEKEND_OUT or ret.weekday() not in WEEKEND_RET):
        return False
    return True


def quote_ok(alert: dict, q: Quote, today: date) -> bool:
    if not date_ok(alert, q.out_date, q.ret_date, today):
        return False
    if alert.get("direct") and q.stops not in (None, 0):
        return False
    if not in_window(q.out_time, alert.get("dep_window")):
        return False
    if not in_window(q.ret_time, alert.get("ret_window")):
        return False
    return True


def date_combos(alert: dict, today: date) -> list[tuple[str, str | None]]:
    """Toutes les paires (aller, retour) compatibles avec l'alerte, les plus proches d'abord."""
    start = max(d(alert["date_from"]), today + timedelta(days=1))
    end = d(alert["date_to"])
    out: list[tuple[str, str | None]] = []
    day = start
    while day <= end:
        if months_ok(alert, day):
            if alert.get("one_way"):
                out.append((day.isoformat(), None))
            else:
                lo, hi = alert.get("nights") or [2, 7]
                for n in range(lo, hi + 1):
                    ret = day + timedelta(days=n)
                    if date_ok(alert, day.isoformat(), ret.isoformat(), today):
                        out.append((day.isoformat(), ret.isoformat()))
        day += timedelta(days=1)
    if alert.get("weekends"):
        # Le classique vendredi → dimanche passe en premier.
        out.sort(key=lambda c: (d(c[0]).weekday() != 4 or (c[1] and d(c[1]).weekday() != 6), c[0]))
    return out


def route_combos(alert: dict, today: date) -> list[tuple[str, str, str, str | None]]:
    """Combinaisons complètes pour les alertes à destinations connues (rotation entre passages)."""
    dates = date_combos(alert, today)
    combos = []
    for out_s, ret_s in dates:
        for o in alert["origins"]:
            for dst in alert["destinations"]:
                if o != dst:
                    combos.append((o, dst, out_s, ret_s))
    return combos


def months_to_scan(alert: dict, today: date) -> list[str]:
    start = max(d(alert["date_from"]), today)
    end = d(alert["date_to"])
    months = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        key = cur.strftime("%Y-%m")
        if not alert.get("months") or key in alert["months"]:
            months.append(key)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return months


def paris_now() -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Paris"))
