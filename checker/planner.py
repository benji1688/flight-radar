"""Règles de dates et d'horaires d'une alerte, appliquées trajet par trajet (aller, puis retour).

Le moteur cherche l'aller et le retour séparément (deux allers simples), ce qui permet :
- d'appliquer un créneau horaire différent selon le jour (jeudi après 18 h, vendredi après 12 h…) ;
- de connaître l'heure exacte du retour (lundi avant 6 h…) ;
- de combiner librement les dates et même deux compagnies ou deux pays de vente différents.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

# Week-end « classique » quand aucune règle de jour n'est donnée.
WEEKEND_OUT = {3, 4, 5}   # jeudi, vendredi, samedi
WEEKEND_RET = {5, 6, 0}   # samedi, dimanche, lundi


@dataclass
class Leg:
    """Un trajet simple (aller ou retour) à une date donnée, au meilleur prix trouvé."""
    origin: str
    destination: str
    date: str
    price: float
    currency: str
    eur: float
    market: str
    source: str            # "google" ou "aviasales"
    airline: str = ""
    stops: int | None = None
    time: str | None = None   # "HH:MM" au départ
    link: str = ""

    @property
    def key(self) -> str:
        return leg_key(self.origin, self.destination, self.date)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["eur"] = round(self.eur, 2)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Leg":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


@dataclass
class Trip:
    out: Leg
    ret: Leg | None
    extra: dict = field(default_factory=dict)

    @property
    def eur(self) -> float:
        return self.out.eur + (self.ret.eur if self.ret else 0)

    @property
    def source(self) -> str:
        return "google" if self.out.source == "google" and (not self.ret or self.ret.source == "google") else "aviasales"

    def to_dict(self) -> dict:
        o, r = self.out, self.ret
        return {
            "origin": o.origin, "destination": o.destination,
            "out_date": o.date, "out_time": o.time, "out_airline": o.airline, "out_stops": o.stops,
            "out_market": o.market, "out_price": o.price, "out_currency": o.currency, "out_eur": round(o.eur, 2),
            "out_link": o.link,
            "ret_date": r.date if r else None, "ret_time": r.time if r else None,
            "ret_airline": r.airline if r else None, "ret_stops": r.stops if r else None,
            "ret_market": r.market if r else None, "ret_price": r.price if r else None,
            "ret_currency": r.currency if r else None, "ret_eur": round(r.eur, 2) if r else None,
            "ret_link": r.link if r else None,
            "eur": round(self.eur, 2), "source": self.source,
            # compatibilité avec l'affichage du bot
            "market": o.market if (not r or r.market == o.market) else "mix",
            "link": o.link,
            **self.extra,
        }


def leg_key(origin: str, destination: str, day: str) -> str:
    return f"{origin}>{destination}@{day}"


def d(s: str) -> date:
    return date.fromisoformat(s[:10])


def _rules(raw) -> dict[int, list] | None:
    if not raw:
        return None
    return {int(k): v for k, v in raw.items()}


def in_window(hhmm: str | None, window: list | None) -> bool:
    if not window or not hhmm:
        return True
    h = int(hhmm[:2]) + int(hhmm[3:5]) / 60
    return window[0] <= h <= window[1]


def nights_range(alert: dict) -> tuple[int, int]:
    if alert.get("nights"):
        return tuple(alert["nights"])
    if alert.get("out_dates") or alert.get("ret_dates"):
        return (1, 10)
    if alert.get("out_rules") or alert.get("ret_rules"):
        return (1, 5)   # même week-end : jeudi → lundi au plus
    return (1, 3) if alert.get("weekends") else (2, 7)


def months_ok(alert: dict, day: date) -> bool:
    months = alert.get("months") or []
    return not months or day.strftime("%Y-%m") in months


# ── Aller ────────────────────────────────────────────────────────────────

def out_window(alert: dict, day: date, today: date):
    """Créneau horaire autorisé pour un aller ce jour-là, ou False si le jour est exclu."""
    if day <= today or day < d(alert["date_from"]) or day > d(alert["date_to"]):
        return False
    if alert.get("out_dates"):
        if day.isoformat() not in alert["out_dates"]:
            return False
    elif not months_ok(alert, day):
        return False
    rules = _rules(alert.get("out_rules"))
    if rules is not None:
        if day.weekday() not in rules:
            return False
        return rules[day.weekday()] or alert.get("dep_window")
    if alert.get("weekends") and day.weekday() not in WEEKEND_OUT:
        return False
    return alert.get("dep_window")


def out_dates(alert: dict, today: date) -> list[str]:
    start = max(d(alert["date_from"]), today + timedelta(days=1))
    end = d(alert["date_to"])
    days, cur = [], start
    while cur <= end:
        if out_window(alert, cur, today) is not False:
            days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def layover_unknown(alert: dict, leg: Leg) -> bool:
    """Aviasales ne donne pas la durée des escales : avec une limite d'escale, on ne garde que ses vols directs."""
    return bool(alert.get("max_layover")) and leg.source == "aviasales" and leg.stops not in (None, 0)


def out_ok(alert: dict, leg: Leg, today: date) -> bool:
    w = out_window(alert, d(leg.date), today)
    if w is False:
        return False
    if (alert.get("direct") and leg.stops not in (None, 0)) or layover_unknown(alert, leg):
        return False
    return in_window(leg.time, w or None)


# ── Retour ───────────────────────────────────────────────────────────────

def ret_window(alert: dict, out_day: date | None, day: date):
    """Créneau autorisé pour un retour ce jour-là (False si exclu). out_day=None : test sans aller précis."""
    if alert.get("ret_dates"):
        if day.isoformat() not in alert["ret_dates"]:
            return False
    rules = _rules(alert.get("ret_rules"))
    if rules is not None:
        if day.weekday() not in rules:
            return False
    elif alert.get("weekends") and not alert.get("ret_dates") and day.weekday() not in WEEKEND_RET:
        return False
    if out_day is not None:
        lo, hi = nights_range(alert)
        if not lo <= (day - out_day).days <= hi:
            return False
    if rules is not None:
        return rules[day.weekday()] or alert.get("ret_window")
    return alert.get("ret_window")


def ret_dates(alert: dict, outs: list[str]) -> list[str]:
    days = set()
    for o in outs:
        od = d(o)
        lo, hi = nights_range(alert)
        for n in range(lo, hi + 1):
            day = od + timedelta(days=n)
            if ret_window(alert, od, day) is not False:
                days.add(day.isoformat())
    return sorted(days)


def ret_ok(alert: dict, leg: Leg) -> bool:
    w = ret_window(alert, None, d(leg.date))
    if w is False:
        return False
    if (alert.get("direct") and leg.stops not in (None, 0)) or layover_unknown(alert, leg):
        return False
    return in_window(leg.time, w or None)


def pair_ok(alert: dict, out: Leg, ret: Leg) -> bool:
    return ret_window(alert, d(out.date), d(ret.date)) is not False


def months_between(first: str, last: str) -> list[str]:
    a, b = d(first), d(last)
    months, cur = [], date(a.year, a.month, 1)
    while cur <= b:
        months.append(cur.strftime("%Y-%m"))
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return months


def best_trips(alert: dict, outs: list[Leg], rets: list[Leg]) -> list[Trip]:
    """Meilleure combinaison aller + retour pour chaque (départ, destination, dates)."""
    if alert.get("one_way"):
        return sorted((Trip(o, None) for o in outs), key=lambda t: t.eur)
    by_route: dict[tuple, list[Leg]] = {}
    for r in rets:
        by_route.setdefault((r.destination, r.origin), []).append(r)
    trips = []
    for o in outs:
        for r in by_route.get((o.origin, o.destination), []):
            if pair_ok(alert, o, r):
                trips.append(Trip(o, r))
    return sorted(trips, key=lambda t: t.eur)


def paris_now() -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Paris"))
