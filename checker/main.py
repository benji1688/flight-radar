"""Moteur Flight Radar : lancé par GitHub Actions toutes les heures.

Principe : l'aller et le retour sont cherchés séparément (deux allers simples), trajet par trajet.
1. Aviasales (cache gratuit) repère les destinations et les dates prometteuses.
2. Google Flights vérifie chaque trajet au prix réel, avec le créneau horaire propre à chaque jour.
   Les prix trouvés sont gardés en mémoire : à chaque passage, le moteur complète les trajets manquants
   et rafraîchit ceux des meilleures combinaisons.
3. Pour les meilleurs trajets, il compare les pays de vente (classement appris au fil des passages).
4. Il combine allers et retours, enregistre l'historique et envoie les bons plans sur Telegram.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from .api import Relay
from .destinations import DOMESTIC_KEEP, POPULAR
from .fx import FX
from .markets import MARKETS, rank_markets, record
from .notify import build_digest, is_quiet, select_deals
from .planner import (Leg, Trip, best_trips, d, leg_key, months_between, out_dates, out_ok, out_window,
                      paris_now, ret_dates, ret_ok, ret_window)
from .sources.google import Blocked, GoogleFlights
from .sources.travelpayouts import Travelpayouts, load_airports

log = logging.getLogger("flight-radar")

NORMAL_INTERVAL = timedelta(minutes=40)   # passage toutes les 15 min : alertes normales ≈ 1 passage sur 3
TP_EVERY = timedelta(hours=6)          # rafraîchissement du repérage Aviasales
TOP_TTL_PRIO = timedelta(hours=1)      # fraîcheur exigée pour les meilleurs trajets
TOP_TTL = timedelta(hours=2)
LEG_TTL = timedelta(hours=24)          # au-delà, un trajet est revérifié quand il reste du budget
EXPLORE_EVERY = timedelta(days=7)      # tour complet de tous les pays pour la meilleure combinaison
MAX_DESTS = 45
HISTORY_DAYS = 180


class Ctx:
    def __init__(self, settings, stats, fx, tp, google, airports, today):
        self.settings = settings
        self.stats = stats
        self.fx = fx
        self.tp = tp
        self.google = google
        self.airports = airports
        self.today = today
        self.fee = float(settings.get("fx_fee_pct", 2))
        self.now = datetime.now(timezone.utc)
        self.empty_keys: list[str] = []


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def age(ts: str | None, now: datetime) -> timedelta:
    return now - datetime.fromisoformat(ts) if ts else timedelta.max


def is_due(alert: dict, res: dict, now: datetime) -> bool:
    if not alert.get("active", True):
        return False
    last = res.get("last_check")
    if not last or alert.get("priority"):
        return True
    return now - datetime.fromisoformat(last) >= NORMAL_INTERVAL


# ── Mémoire des trajets ─────────────────────────────────────────────────
# res["legs"][clé] = {"at": date de vérif FR, "fr": trajet FR ou None (aucun vol), "mk": {pays: trajet ou {"none"}}}

def best_leg(entry: dict, min_gain: float) -> Leg | None:
    """Prix retenu pour un trajet : la France, sauf si un autre pays fait gagner au moins min_gain/2."""
    fr = Leg.from_dict(entry["fr"]) if entry.get("fr") else None
    if fr is None:
        return None
    best = fr
    for m in (entry.get("mk") or {}).values():
        if m and "eur" in m and m["eur"] <= fr.eur - min_gain / 2 and m["eur"] < best.eur:
            best = Leg.from_dict(m)
    return best


def known_legs(store: dict, keys: list[str], min_gain: float) -> list[Leg]:
    out = []
    for k in keys:
        e = store.get(k)
        if e:
            leg = best_leg(e, min_gain)
            if leg:
                out.append(leg)
    return out


# ── Repérage Aviasales ──────────────────────────────────────────────────

def domestic(alert: dict, dest: str, ctx: Ctx) -> bool:
    """Destination dans le même pays que le départ (exclue des alertes « partout »), sauf la Corse.
    Les escales en France restent permises."""
    if dest in DOMESTIC_KEEP:
        return False
    countries = {ctx.airports.get(o, {}).get("country") for o in alert["origins"]} - {None, ""}
    if not countries:
        countries = {"fr"}
    return ctx.airports.get(dest, {}).get("country") in countries


def tp_discovery(alert: dict, res: dict, ctx: Ctx, outs: list[str], rets: list[str]) -> dict:
    tp = res.get("tp") or {}
    if not ctx.tp.enabled or age(tp.get("at"), ctx.now) < TP_EVERY:
        return tp
    direct = alert.get("direct", False)
    out_legs: list[Leg] = []
    targets = alert["destinations"] or [None]
    for o in alert["origins"]:
        for dest in targets:
            for m in months_between(outs[0], outs[-1]):
                out_legs += [x for x in ctx.tp.one_way(o, dest, m, direct, ctx.fx, ctx.fee)
                             if out_ok(alert, x, ctx.today) and x.destination not in alert["origins"]]
    dest_out: dict[str, float] = {}
    for x in out_legs:
        dest_out[x.destination] = min(dest_out.get(x.destination, 1e9), x.eur)
    ranked = sorted(dest_out, key=dest_out.get)[:15]
    ret_legs: list[Leg] = []
    if rets and not alert.get("one_way"):
        for dest in ranked:
            for o in alert["origins"]:
                for m in months_between(rets[0], rets[-1]):
                    ret_legs += [x for x in ctx.tp.one_way(dest, o, m, direct, ctx.fx, ctx.fee) if ret_ok(alert, x)]
    dest_ret: dict[str, float] = {}
    for x in ret_legs:
        dest_ret[x.origin] = min(dest_ret.get(x.origin, 1e9), x.eur)
    score = {dst: v + dest_ret.get(dst, v) for dst, v in dest_out.items()}
    tp = {"at": iso_now(), "score": {k: round(v, 1) for k, v in score.items()},
          "out": [x.to_dict() for x in sorted(out_legs, key=lambda x: x.eur)[:200]],
          "ret": [x.to_dict() for x in sorted(ret_legs, key=lambda x: x.eur)[:200]]}
    res["tp"] = tp
    return tp


# ── Choix des trajets à vérifier sur Google ─────────────────────────────

def plan_queue(alert: dict, store: dict, dests: list[str], outs: list[str], rets: list[str],
               top: list[Trip], ctx: Ctx) -> list[tuple[str, str, str, str]]:
    """File ordonnée de trajets (sens, départ, arrivée, date) à demander à Google ce passage."""
    max_price = alert.get("max_price")
    min_gain = float(ctx.settings.get("min_gain_eur", 15))
    top_ttl = TOP_TTL_PRIO if alert.get("priority") else TOP_TTL
    queue: list[tuple] = []
    seen: set[str] = set()

    def push(kind, o, dst, day):
        k = leg_key(o, dst, day)
        if k not in seen:
            seen.add(k)
            queue.append((kind, o, dst, day))

    # 1. Rafraîchir les trajets des meilleures combinaisons
    for t in top[:3]:
        for leg, kind in ((t.out, "out"), (t.ret, "ret")):
            if leg and age(store.get(leg.key, {}).get("at"), ctx.now) >= top_ttl:
                push(kind, leg.origin, leg.destination, leg.date)

    # 2. Compléter les trajets jamais vérifiés, une destination après l'autre, à tour de rôle
    def cheapest(keys):
        return min((x.eur for x in known_legs(store, keys, min_gain)), default=None)

    per_dest = []
    for dst in dests:
        okeys = [(o, dst, day) for o in alert["origins"] if o != dst for day in outs]
        rkeys = [(dst, o, day) for o in alert["origins"] if o != dst for day in rets]
        min_out = cheapest([leg_key(*k) for k in okeys])
        min_ret = cheapest([leg_key(*k) for k in rkeys])
        all_out_checked = all(leg_key(*k) in store for k in okeys)
        all_ret_checked = bool(rkeys) and all(leg_key(*k) in store for k in rkeys)
        # Destination sans intérêt : aucun vol, ou un seul trajet déjà au-dessus du budget.
        if all_out_checked and min_out is None:
            continue
        if max_price is not None and all_out_checked and min_out is not None and min_out >= max_price:
            continue
        if max_price is not None and all_ret_checked and min_ret is not None and min_ret >= max_price:
            continue
        todo_out = [("out", *k) for k in okeys if leg_key(*k) not in store]
        # Avec un prix max, les retours ne sont cherchés qu'une fois un aller abordable trouvé.
        worth_ret = not alert.get("one_way") and (max_price is None or (min_out is not None and min_out < max_price))
        todo_ret = [("ret", *k) for k in rkeys if leg_key(*k) not in store] if worth_ret else []
        per_dest.append((todo_out, todo_ret))
    for _ in range(200):
        if not any(o or r for o, r in per_dest):
            break
        for todo_out, todo_ret in per_dest:
            if todo_out:
                push(*todo_out.pop(0))
            if todo_ret:
                push(*todo_ret.pop(0))

    # 3. Revérifier les trajets anciens (les plus vieux d'abord)
    # (un trajet « sans vol » est revérifié au bout de 3 jours : de nouveaux vols ont pu ouvrir)
    for _, k in sorted((store[k]["at"], k) for k in store
                       if age(store[k].get("at"), ctx.now) >= (LEG_TTL if store[k].get("fr") else 3 * LEG_TTL)):
        o, rest = k.split(">")
        dst, day = rest.split("@")
        push("out" if o in alert["origins"] else "ret", o, dst, day)
    return queue


def leg_window(alert: dict, leg_origin: str, day: str, ctx: Ctx):
    if leg_origin in alert["origins"]:
        return out_window(alert, d(day), ctx.today)
    return ret_window(alert, None, d(day))


def query_leg(o: str, dst: str, day: str, alert: dict, store: dict, ctx: Ctx) -> None:
    window = leg_window(alert, o, day, ctx)
    if window is False:
        store[leg_key(o, dst, day)] = {"at": iso_now(), "fr": None, "mk": {}}
        return
    leg = ctx.google.search_leg(o, dst, day, MARKETS["fr"], alert.get("direct", False), window or None,
                                ctx.fx, ctx.fee, alert.get("max_layover"))
    key = leg_key(o, dst, day)
    entry = store.setdefault(key, {})
    entry.update({"at": iso_now(), "fr": leg.to_dict() if leg else None})
    entry.setdefault("mk", {})
    if getattr(ctx.google, "last_empty", False):
        ctx.empty_keys.append(key)   # à oublier si Google s'avère bloqué (réponse vide ≠ aucun vol)


def compare_markets(trips: list[Trip], alert: dict, store: dict, res: dict, ctx: Ctx, budget: int) -> int:
    """Teste les autres pays de vente sur les trajets des meilleures combinaisons. Renvoie le nombre de requêtes."""
    used = 0
    excluded = ctx.settings.get("excluded_markets") or []
    per_search = int(ctx.settings.get("markets_per_search", 3))
    explore = age(res.get("explored_at"), ctx.now) >= EXPLORE_EVERY
    top_ttl = TOP_TTL_PRIO if alert.get("priority") else TOP_TTL
    for idx, t in enumerate(trips[:2]):
        for leg in (t.out, t.ret):
            if leg is None:
                continue
            entry = store.get(leg.key) or {}
            fr = entry.get("fr")
            if not fr:
                continue
            route = f"{leg.origin}-{leg.destination}"
            ranked = rank_markets(ctx.stats, route, ctx.airports.get(leg.destination, {}).get("country"), excluded)
            markets = ranked if (explore and idx == 0) else ranked[:per_search]
            mk = entry.setdefault("mk", {})
            window = leg_window(alert, leg.origin, leg.date, ctx)
            for code in markets:
                prev = mk.get(code)
                if prev and age(prev.get("at"), ctx.now) < top_ttl:
                    continue
                if used >= budget or not ctx.google.available:
                    return used
                used += 1
                q = ctx.google.search_leg(leg.origin, leg.destination, leg.date, MARKETS[code],
                                          alert.get("direct", False), window or None, ctx.fx, ctx.fee,
                                          alert.get("max_layover"))
                if q is None:
                    mk[code] = {"none": True, "at": iso_now()}
                    continue
                mk[code] = {**q.to_dict(), "at": iso_now()}
                gain = fr["eur"] - q.eur
                record(ctx.stats, route, code, gain >= 1, max(gain, 0))
        if explore and idx == 0:
            res["explored_at"] = iso_now()
    return used


def tp_trips(alert: dict, tp: dict, google_dests: set[str], today) -> list[Trip]:
    outs = [x for x in (Leg.from_dict(y) for y in tp.get("out", []))
            if x.destination not in google_dests and out_ok(alert, x, today)]
    rets = [x for x in (Leg.from_dict(y) for y in tp.get("ret", []))
            if x.origin not in google_dests and ret_ok(alert, x)]
    return best_trips(alert, outs, rets)


def best_per_destination(trips: list[Trip]) -> list[Trip]:
    seen, out = set(), []
    for t in trips:
        if t.out.destination not in seen:
            seen.add(t.out.destination)
            out.append(t)
    return out


def process_alert(alert: dict, res: dict, ctx: Ctx, budget: int) -> dict | None:
    """Traite une alerte, met à jour `res` et renvoie éventuellement un message à envoyer."""
    min_gain = float(ctx.settings.get("min_gain_eur", 15))
    outs = out_dates(alert, ctx.today)
    rets = [] if alert.get("one_way") else ret_dates(alert, outs)
    res["last_check"] = iso_now()
    if not outs:
        return None

    # Mémoire : on oublie les trajets passés ou qui ne correspondent plus à l'alerte.
    store = res.setdefault("legs", {})
    allowed = set(outs) | set(rets)
    for k in list(store):
        if k.split("@")[1] not in allowed:
            del store[k]

    tp = tp_discovery(alert, res, ctx, outs, rets)
    if alert["destinations"]:
        dests = [x for x in alert["destinations"] if x not in alert["origins"]]
    else:
        score = tp.get("score", {})
        pool = set(score) | {x for x in POPULAR if x not in alert["origins"]}
        pool = {x for x in pool if not domestic(alert, x, ctx)}
        dests = sorted(pool, key=lambda x: (score.get(x, 1e6), x))[:MAX_DESTS]

    def current_trips() -> list[Trip]:
        out_keys = [leg_key(o, dst, day) for dst in dests for o in alert["origins"] for day in outs]
        ret_keys = [leg_key(dst, o, day) for dst in dests for o in alert["origins"] for day in rets]
        return best_trips(alert, known_legs(store, out_keys, min_gain), known_legs(store, ret_keys, min_gain))

    # Par petits lots : la file est recalculée après chaque lot pour tenir compte des prix trouvés
    # (une destination trop chère est abandonnée, ses retours ne sont pas cherchés).
    market_budget = budget // 4
    used = 0
    try:
        while used < budget - market_budget and ctx.google.available:
            trips = current_trips()
            queue = plan_queue(alert, store, dests, outs, rets, best_per_destination(trips), ctx)
            if not queue:
                break
            for _, o, dst, day in queue[:8]:
                if used >= budget - market_budget or not ctx.google.available:
                    break
                query_leg(o, dst, day, alert, store, ctx)
                used += 1
        trips = current_trips()
        compare_markets(best_per_destination(trips), alert, store, res, ctx, budget - used)
    except Blocked as e:
        # Google refuse cette machine : on garde ce qui a été trouvé, le prochain passage reprendra.
        log.warning("Google bloqué pendant %s : %s", alert["id"], e)
        if not getattr(ctx.google, "empty_ok", True):
            for k in ctx.empty_keys:
                if k in store and not store[k].get("fr"):
                    del store[k]
    trips = current_trips()

    single = len(dests) == 1
    shown = trips if single else best_per_destination(trips)
    google_dests = {t.out.destination for t in trips}
    estimates = [t for t in best_per_destination(tp_trips(alert, tp, google_dests, ctx.today))
                 if alert["destinations"] or not domestic(alert, t.out.destination, ctx)] if tp else []
    res["top"] = [t.to_dict() for t in shown[:8]] + [t.to_dict() for t in estimates[:4]]
    res["coverage"] = {"legs_known": len(store),
                       "legs_total": len(dests) * len(alert["origins"]) * (len(outs) + len(rets)),
                       "dests": len(dests)}
    if shown:
        res["best"] = shown[0].to_dict()
        today_s = ctx.today.isoformat()
        hist = [h for h in res.get("history", []) if h[0] != today_s]
        prev_today = next((h[1] for h in res.get("history", []) if h[0] == today_s), None)
        hist.append([today_s, round(min(shown[0].eur, prev_today) if prev_today is not None else shown[0].eur, 2)])
        res["history"] = hist[-HISTORY_DAYS:]
    elif estimates:
        res["best"] = estimates[0].to_dict()
    else:
        res.pop("best", None)
        return None

    pool = (shown if not single else trips[:1]) + estimates
    deals = select_deals(alert, best_per_destination(sorted(pool, key=lambda t: t.eur)), res, ctx.settings)
    if not deals:
        return None
    return {"text": build_digest(alert, deals, res, ctx.settings, ctx.airports)}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("primp").setLevel(logging.WARNING)
    worker_url = os.environ.get("WORKER_URL")
    api_key = os.environ.get("API_KEY")
    if not worker_url or not api_key:
        log.error("WORKER_URL ou API_KEY manquant : lance d'abord le workflow « Déployer le bot ».")
        return 1

    relay = Relay(worker_url, api_key)
    state = relay.state()
    if state.get("owner") is None:
        log.info("Personne n'a encore écrit au bot : envoie /start sur Telegram.")
    alerts = state.get("alerts", [])
    settings = state.get("settings", {})
    results = state.get("results", {})
    stats = state.get("stats", {})
    prev_run = state.get("run") or {}

    now = datetime.now(timezone.utc)
    force = os.environ.get("FORCE") == "true"  # lancement manuel : toutes les alertes actives sont vérifiées
    due = [a for a in alerts if is_due(a, results.setdefault(a["id"], {}), now)
           or (force and a.get("active", True))]
    due.sort(key=lambda a: (not a.get("priority"), results[a["id"]].get("last_check") or ""))
    log.info("%d alerte(s), %d à vérifier ce passage", len(alerts), len(due))

    errors: list[str] = []
    messages: list[dict] = []
    google = GoogleFlights(max_requests=int(os.environ.get("GOOGLE_MAX_REQUESTS", "10")), delay=(2.0, 4.0))
    tp = Travelpayouts(os.environ.get("TRAVELPAYOUTS_TOKEN"))
    if not tp.token:
        errors.append("Pas de token Travelpayouts : les alertes « vers partout » se limitent à la liste de destinations par défaut.")

    if due:
        fx = FX.load()
        airports = load_airports()
        ctx = Ctx(settings, stats, fx, tp, google, airports, paris_now().date())
        # Une alerte déjà entièrement vérifiée n'a besoin que de rafraîchir ses meilleurs prix :
        # le gros du budget va aux alertes qui ont encore des trajets à découvrir.
        def weight(a):
            cov = results[a["id"]].get("coverage") or {}
            remaining = (cov.get("legs_total") or 1) - (cov.get("legs_known") or 0)
            return (2 if a.get("priority") else 1) * (4 if remaining > 0 else 1)
        weights = [weight(a) for a in due]
        for i, alert in enumerate(due):
            remaining = max(google.max_requests - google.requests, 0)
            budget = max(2, remaining * weights[i] // max(sum(weights[i:]), 1))
            res = results[alert["id"]]
            try:
                detail = relay.legs(alert["id"])
            except Exception as e:
                log.warning("mémoire des trajets illisible pour %s : %s", alert["id"], e)
                detail = {}
            res["legs"], res["tp"] = detail.get("legs", {}), detail.get("tp", {})
            before = json.dumps(detail, sort_keys=True)
            try:
                msg = process_alert(alert, res, ctx, budget)
            except Exception as e:  # une alerte en erreur ne doit pas casser les autres
                log.exception("alerte %s en erreur", alert["id"])
                errors.append(f"{alert['id']} : {type(e).__name__} {e}")
                msg = None
            # La mémoire détaillée est stockée à part, pour garder « results » léger pour le bot.
            after = {"legs": res.pop("legs", {}), "tp": res.pop("tp", {})}
            if json.dumps(after, sort_keys=True) != before:   # écriture seulement si quelque chose a changé
                relay.save_legs(alert["id"], after)
            cov = res.get("coverage", {})
            log.info("%s : %s/%s trajets vérifiés sur %s destination(s)", alert["id"],
                     cov.get("legs_known"), cov.get("legs_total"), cov.get("dests"))
            if msg:
                messages.append(msg)

    errors.extend(tp.errors)
    if google.status == "bloqué":
        errors.append("Google Flights a refusé cette machine GitHub : reprise au prochain passage (autre machine).")
    blocked_streak = (prev_run.get("blocked_streak", 0) + 1) if google.status == "bloqué" else 0
    if blocked_streak == 12:
        messages.append({"text": "⚠️ Google Flights bloque le moteur depuis 3 heures. Les estimations Aviasales "
                                 "continuent ; si ça dure plus d'une journée, préviens Claude."})
    if google.requests >= 10 and google.empty >= google.requests * 0.8:
        errors.append("Google Flights renvoie presque toujours des réponses vides : la bibliothèque faster-flights "
                      "est peut-être à mettre à jour.")

    quiet = is_quiet(settings, paris_now().hour)
    for m in messages:
        m["silent"] = quiet

    run = {
        "at": now.isoformat(),
        "alerts_checked": len(due),
        "google_requests": google.requests,
        "google_status": google.status,
        "tp_calls": tp.calls,
        "blocked_streak": blocked_streak,
        "errors": errors[-5:],
    }
    relay.save(results, stats, run)
    relay.notify(messages)
    log.info("terminé : %d requête(s) Google (%s, %d vides), %d Aviasales, %d notif(s)",
             google.requests, google.status, google.empty, tp.calls, len(messages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
