"""Moteur Flight Radar : lancé par GitHub Actions toutes les heures.

1. Lit les alertes sur le relais Cloudflare.
2. Balaye large avec Aviasales (cache gratuit), dans plusieurs pays.
3. Confirme les meilleures pistes sur Google Flights, en France puis dans les pays les plus prometteurs.
4. Apprend quels pays battent la France, enregistre l'historique et envoie les notifs Telegram.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from .api import Relay
from .fx import FX
from .markets import MARKETS, rank_markets, record
from .notify import build_message, is_deal, is_quiet, should_notify
from .planner import Quote, months_to_scan, paris_now, quote_ok, route_combos
from .sources.google import Blocked, GoogleFlights
from .sources.travelpayouts import Travelpayouts, load_airports

log = logging.getLogger("flight-radar")

NORMAL_INTERVAL = timedelta(hours=3) - timedelta(minutes=10)
TP_MARKETS = ["fr"]                      # le cache Aviasales est identique quel que soit le marché (testé le 22/11/2026)
EXPLORE_EVERY = timedelta(days=7)         # balayage complet de tous les pays
MAX_TP_CALLS_PER_ALERT = 40
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


def is_due(alert: dict, res: dict, now: datetime) -> bool:
    if not alert.get("active", True):
        return False
    last = res.get("last_check")
    if not last or alert.get("priority"):
        return True
    return now - datetime.fromisoformat(last) >= NORMAL_INTERVAL


def scan_aviasales(alert: dict, ctx: Ctx) -> list[Quote]:
    quotes: list[Quote] = []
    calls = 0
    dests = alert["destinations"] or [None]
    for month in months_to_scan(alert, ctx.today):
        for origin in alert["origins"]:
            for dest in dests:
                for market in TP_MARKETS:
                    if calls >= MAX_TP_CALLS_PER_ALERT or not ctx.tp.enabled:
                        return quotes
                    calls += 1
                    found = ctx.tp.search(origin, dest, month, alert.get("one_way", False),
                                          alert.get("direct", False), market, ctx.fx, ctx.fee)
                    quotes.extend(q for q in found if quote_ok(alert, q, ctx.today)
                                  and (not alert["destinations"] or q.destination in alert["destinations"]
                                       or ctx.airports.get(q.destination, {}).get("city") in alert["destinations"]))
    return quotes


def cheapest_by_combo(quotes: list[Quote]) -> list[Quote]:
    best: dict[tuple, Quote] = {}
    for q in quotes:
        if q.combo not in best or q.eur < best[q.combo].eur:
            best[q.combo] = q
    return sorted(best.values(), key=lambda q: q.eur)


def check_google(alert: dict, combos: list[tuple], res: dict, ctx: Ctx, budget: int) -> list[Quote]:
    """Interroge Google pour chaque combinaison : France d'abord, puis les pays les mieux classés."""
    quotes: list[Quote] = []
    used = 0
    excluded = ctx.settings.get("excluded_markets") or []
    per_search = int(ctx.settings.get("markets_per_search", 3))
    explored_at = res.get("explored_at")
    explore = not explored_at or datetime.now(timezone.utc) - datetime.fromisoformat(explored_at) >= EXPLORE_EVERY

    for idx, (origin, dest, out_s, ret_s) in enumerate(combos):
        route = f"{origin}-{dest}"
        country = ctx.airports.get(dest, {}).get("country")
        ranked = rank_markets(ctx.stats, route, country, excluded)
        markets = ranked if (explore and idx == 0) else ranked[:per_search]
        fr_quote = None
        for code in ["fr", *markets]:
            if used >= budget or not ctx.google.available:
                return quotes
            used += 1
            q = ctx.google.search(origin, dest, out_s, ret_s, MARKETS[code], alert.get("direct", False),
                                  alert.get("dep_window"), ctx.fx, ctx.fee)
            if code == "fr":
                fr_quote = q
                if q is None:
                    break  # pas de vol (ou pas de réponse) : inutile d'essayer les autres pays
            if q is None:
                continue
            quotes.append(q)
            if code != "fr" and fr_quote is not None:
                gain = fr_quote.eur - q.eur
                record(ctx.stats, route, code, gain >= 1, max(gain, 0))
        if explore and idx == 0 and fr_quote is not None:
            res["explored_at"] = datetime.now(timezone.utc).isoformat()
    return quotes


def eligible_quotes(quotes: list[Quote], min_gain: float) -> list[Quote]:
    """Un pays étranger n'est retenu que s'il fait gagner au moins `min_gain` € par rapport à la France."""
    google = [q for q in quotes if q.source == "google"]
    if not google:
        return cheapest_by_combo(quotes)
    fr = {q.combo: q.eur for q in google if q.market == "fr"}
    keep = [q for q in google if q.market == "fr" or (q.combo in fr and fr[q.combo] - q.eur >= min_gain)]
    return cheapest_by_combo(keep)


def process_alert(alert: dict, res: dict, ctx: Ctx, budget: int) -> dict | None:
    """Traite une alerte, met à jour `res` et renvoie éventuellement un message à envoyer."""
    tp_quotes = scan_aviasales(alert, ctx) if ctx.tp.enabled else []
    tp_best = cheapest_by_combo(tp_quotes)
    k = 4 if alert.get("priority") else 3

    combos: list[tuple] = [q.combo for q in tp_best if len(q.destination) == 3][:k]
    if alert["destinations"]:
        # Rotation sur toutes les dates possibles, pour couvrir ce que le cache Aviasales ne connaît pas.
        all_combos = route_combos(alert, ctx.today)
        if all_combos:
            n = k if not combos else 2
            cursor = res.get("cursor", 0) % len(all_combos)
            target = len(combos) + n
            for c in (all_combos[cursor:] + all_combos[:cursor]):
                if len(combos) >= target:
                    break
                if c not in combos:
                    combos.append(c)
            res["cursor"] = (cursor + n) % len(all_combos)

    google_quotes = check_google(alert, combos, res, ctx, budget) if combos else []
    pool = eligible_quotes(tp_quotes + google_quotes, float(ctx.settings.get("min_gain_eur", 15)))
    res["last_check"] = datetime.now(timezone.utc).isoformat()
    if not pool:
        return None

    best = pool[0]
    res["top"] = [q.to_dict() for q in pool[:5]]
    res["best"] = best.to_dict()

    today_s = ctx.today.isoformat()
    hist = [h for h in res.get("history", []) if h[0] != today_s]
    prev_today = next((h[1] for h in res.get("history", []) if h[0] == today_s), None)
    day_min = round(min(best.eur, prev_today) if prev_today is not None else best.eur, 2)
    hist.append([today_s, day_min])
    res["history"] = hist[-HISTORY_DAYS:]

    notify, reason = should_notify(alert, best.eur, res, ctx.settings)
    if not notify:
        return None
    res["notified_eur"] = round(best.eur, 2)
    fr_eur = next((q.eur for q in google_quotes if q.market == "fr" and q.combo == best.combo), None)
    text = build_message(alert, best, reason, fr_eur, ctx.settings,
                         is_deal(best.eur, res["history"][:-1]), ctx.airports)
    return {"text": text}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
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
    due = [a for a in alerts if is_due(a, results.setdefault(a["id"], {}), now)]
    due.sort(key=lambda a: (not a.get("priority"), results[a["id"]].get("last_check") or ""))
    log.info("%d alerte(s), %d à vérifier ce passage", len(alerts), len(due))

    errors: list[str] = []
    messages: list[dict] = []
    google = GoogleFlights(max_requests=int(os.environ.get("GOOGLE_MAX_REQUESTS", "80")))
    tp = Travelpayouts(os.environ.get("TRAVELPAYOUTS_TOKEN"))
    if not tp.token:
        errors.append("Pas de token Travelpayouts : seules les alertes avec destination précise sont cherchées (Google).")

    if due:
        fx = FX.load()
        airports = load_airports()
        ctx = Ctx(settings, stats, fx, tp, google, airports, paris_now().date())
        for i, alert in enumerate(due):
            remaining = max(google.max_requests - google.requests, 0)
            budget = max(4, remaining // (len(due) - i))
            try:
                msg = process_alert(alert, results[alert["id"]], ctx, budget)
            except Blocked as e:
                errors.append(f"Google Flights a bloqué les requêtes ({e}) : on réessaiera au prochain passage.")
                log.warning("Google bloqué : %s", e)
                msg = None
            except Exception as e:  # une alerte en erreur ne doit pas casser les autres
                log.exception("alerte %s en erreur", alert["id"])
                errors.append(f"{alert['id']} : {type(e).__name__} {e}")
                msg = None
            if msg:
                messages.append(msg)
                log.info("notif prête pour %s", alert["id"])

    errors.extend(tp.errors)
    blocked_streak = (prev_run.get("blocked_streak", 0) + 1) if google.status == "bloqué" else 0
    if blocked_streak == 3:
        messages.append({"text": "⚠️ Google Flights bloque le moteur depuis 3 passages. Les alertes continuent "
                                 "avec Aviasales ; si ça dure, baisse le nombre de pays testés (/reglages pays 2)."})
    if google.status == "format changé ?" and prev_run.get("google_status") != "format changé ?":
        messages.append({"text": "⚠️ Google Flights a changé son format : il faudra mettre à jour la bibliothèque "
                                 "faster-flights (fichier checker/requirements.txt)."})

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
    log.info("terminé : %d requête(s) Google (%s), %d Aviasales, %d notif(s)",
             google.requests, google.status, tp.calls, len(messages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
