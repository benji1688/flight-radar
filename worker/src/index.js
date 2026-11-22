// Relais Flight Radar : bot Telegram (réponses instantanées) + API privée pour le moteur GitHub.
// Stockage dans Cloudflare KV, une clé par type de donnée pour éviter les écrasements croisés :
//   owner, alerts, seq, settings  → écrits par le bot
//   results, stats, run           → écrits par le moteur

import { parseAlert, parseSettings, describeAlert, DEFAULT_SETTINGS } from './parse.js';

const json = (o, status = 200) => new Response(JSON.stringify(o), {
  status, headers: { 'content-type': 'application/json; charset=utf-8' },
});

async function sha256hex(s) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function getJSON(env, key, fallback) {
  const v = await env.STATE.get(key, 'json');
  return v === null ? fallback : v;
}
const putJSON = (env, key, v) => env.STATE.put(key, JSON.stringify(v));

export const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

async function tg(env, method, payload) {
  const r = await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return r.json().catch(() => ({}));
}

async function send(env, chatId, text, silent = false) {
  // Telegram limite un message à 4096 caractères.
  const chunks = [];
  let cur = '';
  for (const line of text.split('\n')) {
    if ((cur + line).length > 3900) { chunks.push(cur); cur = ''; }
    cur += `${line}\n`;
  }
  if (cur.trim()) chunks.push(cur);
  for (const c of chunks) {
    await tg(env, 'sendMessage', {
      chat_id: chatId, text: c, parse_mode: 'HTML',
      disable_web_page_preview: true, disable_notification: silent,
    });
  }
}

function parisToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Paris' }).format(new Date());
}

const HELP = `<b>✈️ Flight Radar</b>

<b>Créer une alerte</b>
<code>/alerte de LYS,GVA vers BCN,LIS du 01/03 au 31/03 nuits 2-4 max 80</code>
<code>/alerte de lyon vers partout weekends mars,avril max 60</code>
<code>/alerte de LYS vers OPO en mai aller-simple depart 6-12 direct prio</code>
<code>/alerte de lyon vers partout en decembre,janvier depart jeu apres 18, ven apres 12 retour sam, dim, lun avant 6 max 100</code>
<code>/alerte de lyon vers partout aller 30/12 ou 31/12 retour 02/01 ou 03/01</code>

Mots compris : <i>de, vers (ou partout), du … au …, en mars, weekends mars,avril, nuits 2-4, max 80, direct, aller-simple, prio</i>
Horaires : <i>depart 6-12</i>, ou par jour : <i>depart jeu apres 18, ven 12-20</i> · <i>retour dim, lun avant 6</i>
Dates précises : <i>aller 30/12 ou 31/12 retour 02/01</i>
Villes connues : lyon, geneve, paris, londres, milan… Sinon code aéroport à 3 lettres.

<b>Gérer</b>
/liste — tes alertes et leur meilleur prix
/voir a3 — détail, top 5 et historique
/pause a3 · /reprise a3 — arrêter / relancer les recherches
/notif a3 off · /notif a3 on — couper / remettre les notifs
/prio a3 — vérifier à chaque passage (sinon toutes les 3 h)
/suppr a3 — supprimer
/go — lancer une recherche tout de suite

<b>Pays et réglages</b>
/pays — classement des pays les moins chers
/reglages — voir les réglages
<code>/reglages frais 2 gain 15 baisse 5 silence 23-7 pays 3</code>
<code>/reglages exclure in,br</code> · <code>/reglages inclure in</code>
/statut — dernier passage du moteur`;

// Lance tout de suite le workflow « Chercher les prix » sur GitHub (nécessite le secret GH_TOKEN).
async function triggerSearch(env) {
  if (!env.GH_TOKEN || !env.GH_REPO) return { ok: false, reason: 'token' };
  const last = await env.STATE.get('last_go');
  if (last && Date.now() - Number(last) < 90_000) return { ok: false, reason: 'recent' };
  const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/check.yml/dispatches`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${env.GH_TOKEN}`,
      accept: 'application/vnd.github+json',
      'x-github-api-version': '2022-11-28',
      'user-agent': 'flight-radar-bot',
      'content-type': 'application/json',
    },
    body: JSON.stringify({ ref: 'main' }),
  });
  if (r.status !== 204) return { ok: false, reason: `GitHub a répondu ${r.status}` };
  await env.STATE.put('last_go', String(Date.now()));
  return { ok: true };
}

const GO_SETUP = `Pour lancer une recherche depuis Telegram, il faut une clé GitHub (une seule fois, 3 min) :
1. github.com → photo de profil → <b>Settings</b> → <b>Developer settings</b> → <b>Personal access tokens</b> → <b>Fine-grained tokens</b> → <b>Generate new token</b>
2. Nom : flight-radar · Expiration : 1 an · <b>Only select repositories</b> → flight-radar
3. <b>Permissions</b> → <b>Actions</b> : <b>Read and write</b> → <b>Generate token</b>, copie-le
4. Dans le dépôt : Settings → Secrets and variables → Actions → New repository secret, nom <code>GH_DISPATCH_TOKEN</code>
5. Actions → <b>Déployer le bot</b> → Run workflow

En attendant, le moteur passe tout seul toutes les 15 minutes.`;

function fmtEur(n) { return `${Math.round(n)} €`; }

const JOURS = ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.'];
const MOIS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
function fmtDay(isoDate) {
  const dt = new Date(`${isoDate}T12:00:00Z`);
  return `${JOURS[dt.getUTCDay()]} ${dt.getUTCDate()} ${MOIS[dt.getUTCMonth()]}`;
}

async function handleCommand(env, chatId, text) {
  const [rawCmd, ...rest] = text.trim().split(/\s+/);
  const cmd = rawCmd.toLowerCase().replace(/@\w+$/, '');
  const arg = (rest[0] || '').toLowerCase();
  const alerts = await getJSON(env, 'alerts', []);
  const findAlert = () => alerts.find((a) => a.id === arg);

  switch (cmd) {
    case '/start':
    case '/aide':
    case '/help':
      return send(env, chatId, HELP);

    case '/alerte': {
      const r = parseAlert(text, parisToday());
      if (r.errors) return send(env, chatId, `❌ ${r.errors.map(esc).join('\n❌ ')}\n\nTape /aide pour des exemples.`);
      const seq = (await getJSON(env, 'seq', 0)) + 1;
      const alert = { id: `a${seq}`, created: new Date().toISOString(), active: true, notify: true, ...r.alert };
      alerts.push(alert);
      await putJSON(env, 'seq', seq);
      await putJSON(env, 'alerts', alerts);
      const go = await triggerSearch(env);
      const next = go.ok ? '🚀 Recherche lancée : premiers résultats dans 2 à 3 minutes (/voir ' + alert.id + ').'
        : 'Première recherche au prochain passage du moteur (≤ 15 min).';
      return send(env, chatId, `✅ Alerte <b>${alert.id}</b> créée\n${esc(describeAlert(alert))}\n\n${next}`);
    }

    case '/liste': {
      if (!alerts.length) return send(env, chatId, 'Aucune alerte. Crée-en une avec /alerte (exemples : /aide).');
      const results = await getJSON(env, 'results', {});
      const lines = alerts.map((a) => {
        const r = results[a.id];
        const status = !a.active ? '⏸️ ' : (!a.notify ? '🔕 ' : '');
        const best = r && r.best ? ` — <b>${fmtEur(r.best.eur)}</b> (${esc(r.best.origin)}→${esc(r.best.destination)}, ${fmtDay(r.best.out_date)}${r.best.ret_date ? ` → ${fmtDay(r.best.ret_date)}` : ''})` : ' — pas encore de prix';
        return `${status}<b>${a.id}</b> ${esc(describeAlert(a))}${best}`;
      });
      return send(env, chatId, lines.join('\n\n'));
    }

    case '/voir': {
      const a = findAlert();
      if (!a) return send(env, chatId, 'Alerte introuvable. Exemple : /voir a1');
      const r = (await getJSON(env, 'results', {}))[a.id];
      let msg = `<b>${a.id}</b> ${esc(describeAlert(a))}\n`;
      if (!r) return send(env, chatId, `${msg}\nPas encore de recherche.`);
      msg += `Dernière recherche : ${esc((r.last_check || '').replace('T', ' ').slice(0, 16))} UTC\n`;
      if (r.coverage) {
        const c = r.coverage;
        msg += `Trajets vérifiés : ${c.legs_known}/${c.legs_total} sur ${c.dests} destination(s)\n`;
      }
      if (r.top && r.top.length) {
        msg += '\n<b>Meilleurs prix</b>\n';
        r.top.forEach((q, i) => {
          const est = q.source === 'aviasales' ? ' <i>(estimation Aviasales)</i>' : '';
          msg += `\n${i + 1}. <b>${fmtEur(q.eur)}</b> ${esc(q.origin)} → ${esc(q.destination)}${est}\n`;
          msg += `   🛫 ${fmtDay(q.out_date)}${q.out_time ? ` ${esc(q.out_time)}` : ''}${q.out_airline ? ` · ${esc(q.out_airline)}` : ''}`;
          if (q.out_eur !== undefined && q.ret_date) msg += ` · ${fmtEur(q.out_eur)}`;
          if (q.out_market && q.out_market !== 'fr') msg += ` · vente ${esc(q.out_market.toUpperCase())}`;
          if (q.out_link || q.link) msg += ` · <a href="${esc(q.out_link || q.link)}">lien</a>`;
          if (q.ret_date) {
            msg += `\n   🛬 ${fmtDay(q.ret_date)}${q.ret_time ? ` ${esc(q.ret_time)}` : ''}${q.ret_airline ? ` · ${esc(q.ret_airline)}` : ''}`;
            if (q.ret_eur !== undefined && q.ret_eur !== null) msg += ` · ${fmtEur(q.ret_eur)}`;
            if (q.ret_market && q.ret_market !== 'fr') msg += ` · vente ${esc(q.ret_market.toUpperCase())}`;
            if (q.ret_link) msg += ` · <a href="${esc(q.ret_link)}">lien</a>`;
          }
          msg += '\n';
        });
      }
      if (r.history && r.history.length) {
        const h = r.history.slice(-14);
        const prices = h.map((x) => x[1]);
        msg += `\n<b>Historique (meilleur prix du jour)</b>\n${h.map((x) => `${x[0].slice(5)} : ${fmtEur(x[1])}`).join('\n')}\nMin ${fmtEur(Math.min(...prices))} · Max ${fmtEur(Math.max(...prices))}`;
      }
      return send(env, chatId, msg);
    }

    case '/pause':
    case '/reprise':
    case '/prio':
    case '/suppr':
    case '/notif': {
      const a = findAlert();
      if (!a) return send(env, chatId, `Alerte introuvable. Exemple : ${cmd} a1`);
      let msg;
      if (cmd === '/pause') { a.active = false; msg = `⏸️ ${a.id} en pause (plus de recherche).`; }
      if (cmd === '/reprise') { a.active = true; msg = `▶️ ${a.id} relancée.`; }
      if (cmd === '/prio') { a.priority = !a.priority; msg = a.priority ? `⚡ ${a.id} vérifiée à chaque passage.` : `${a.id} repasse en vérification toutes les 3 h.`; }
      if (cmd === '/notif') {
        const v = (rest[1] || '').toLowerCase();
        a.notify = v ? !['off', 'non', '0'].includes(v) : !a.notify;
        msg = a.notify ? `🔔 Notifs activées pour ${a.id}.` : `🔕 Notifs coupées pour ${a.id} (le suivi des prix continue).`;
      }
      if (cmd === '/suppr') {
        alerts.splice(alerts.indexOf(a), 1);
        await env.STATE.delete(`legs:${a.id}`);
        msg = `🗑️ ${a.id} supprimée.`;
      }
      await putJSON(env, 'alerts', alerts);
      return send(env, chatId, msg);
    }

    case '/go':
    case '/chercher': {
      const go = await triggerSearch(env);
      if (go.ok) return send(env, chatId, '🚀 Recherche lancée sur toutes tes alertes actives. Résultats dans 2 à 3 minutes (/liste, /voir).');
      if (go.reason === 'token') return send(env, chatId, GO_SETUP);
      if (go.reason === 'recent') return send(env, chatId, 'Une recherche vient d\'être lancée, attends 2 minutes.');
      return send(env, chatId, `❌ Impossible de lancer la recherche (${esc(go.reason)}). Vérifie le secret GH_DISPATCH_TOKEN.`);
    }

    case '/pays': {
      const stats = await getJSON(env, 'stats', {});
      const all = stats._all || {};
      const rows = Object.entries(all)
        .filter(([m]) => m !== 'fr')
        .map(([m, s]) => ({ m, ...s, rate: s.tries ? s.wins / s.tries : 0 }))
        .sort((x, y) => y.rate - x.rate || y.wins - x.wins);
      if (!rows.length) return send(env, chatId, 'Pas encore de statistiques : il faut quelques passages du moteur.');
      const lines = rows.map((s) => `<b>${s.m.toUpperCase()}</b> : moins cher que la France ${s.wins}/${s.tries} fois${s.wins ? ` · gain moyen ${fmtEur(s.gain_sum / s.wins)}` : ''}`);
      const settings = await getJSON(env, 'settings', DEFAULT_SETTINGS);
      const ex = (settings.excluded_markets || []).length ? `\n\nExclus : ${settings.excluded_markets.join(', ').toUpperCase()}` : '';
      return send(env, chatId, `<b>🌍 Pays de vente qui battent la France</b>\n${lines.join('\n')}${ex}`);
    }

    case '/reglages': {
      const current = { ...DEFAULT_SETTINGS, ...(await getJSON(env, 'settings', {})) };
      let s = current; let note = '';
      if (rest.length) {
        const r = parseSettings(text, current);
        if (r.errors.length) return send(env, chatId, `❌ ${r.errors.join('\n')}\nExemple : /reglages frais 2 gain 15 silence 23-7`);
        s = r.settings;
        await putJSON(env, 'settings', s);
        note = '✅ Réglages enregistrés\n\n';
      }
      return send(env, chatId, `${note}<b>Réglages</b>
Frais de change de ta carte : ${s.fx_fee_pct} %
Gain minimum pour proposer un autre pays : ${s.min_gain_eur} €
Nouvelle notif si le prix baisse d'au moins : ${s.drop_pct} %
Notifs silencieuses : ${s.quiet ? `${s.quiet[0]}h-${s.quiet[1]}h` : 'jamais'}
Pays testés en plus de la France : ${s.markets_per_search}
Pays exclus : ${(s.excluded_markets || []).join(', ').toUpperCase() || 'aucun'}`);
    }

    case '/statut': {
      const run = await getJSON(env, 'run', null);
      if (!run) return send(env, chatId, 'Le moteur n\'a pas encore tourné. Il passe toutes les 15 minutes (onglet Actions sur GitHub).');
      return send(env, chatId, `<b>Dernier passage</b> : ${esc(run.at.replace('T', ' ').slice(0, 16))} UTC
Alertes vérifiées : ${run.alerts_checked}
Requêtes Google Flights : ${run.google_requests} (${esc(run.google_status)})
Requêtes Aviasales : ${run.tp_calls}
Prochain passage automatique : dans 15 min au plus (/go pour lancer tout de suite)${run.errors && run.errors.length ? `\n\n⚠️ ${run.errors.map(esc).join('\n⚠️ ')}` : ''}`);
    }

    default:
      return send(env, chatId, 'Commande inconnue. Tape /aide.');
  }
}

async function handleUpdate(update, env) {
  const msg = update.message || update.edited_message;
  if (!msg || !msg.text) return;
  const chatId = msg.chat.id;
  let owner = await getJSON(env, 'owner', null);
  if (owner === null) {
    // Le premier qui écrit au bot en devient le propriétaire. Les autres sont ignorés.
    owner = chatId;
    await putJSON(env, 'owner', owner);
  }
  if (chatId !== owner) return;
  if (!msg.text.startsWith('/')) return send(env, chatId, 'Tape /aide pour voir les commandes.');
  await handleCommand(env, chatId, msg.text);
}

export default {
  // Horloge Cloudflare (plus ponctuelle que celle de GitHub) : relance le moteur toutes les 15 min
  // si la clé GitHub est configurée.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerSearch(env).catch((e) => console.log('cron', e && e.stack)));
  },

  async fetch(req, env) {
    const url = new URL(req.url);

    if (url.pathname === '/telegram' && req.method === 'POST') {
      const expected = await sha256hex(env.API_KEY);
      if (req.headers.get('X-Telegram-Bot-Api-Secret-Token') !== expected) return new Response('forbidden', { status: 403 });
      try {
        await handleUpdate(await req.json(), env);
      } catch (e) {
        console.log('update error', e && e.stack);
      }
      return new Response('ok');
    }

    if (url.pathname.startsWith('/api/')) {
      if (req.headers.get('authorization') !== `Bearer ${env.API_KEY}`) return json({ error: 'unauthorized' }, 401);

      if (url.pathname === '/api/state' && req.method === 'GET') {
        const [owner, alerts, settings, results, stats, run] = await Promise.all([
          getJSON(env, 'owner', null), getJSON(env, 'alerts', []), getJSON(env, 'settings', {}),
          getJSON(env, 'results', {}), getJSON(env, 'stats', {}), getJSON(env, 'run', null),
        ]);
        return json({ owner, alerts, settings: { ...DEFAULT_SETTINGS, ...settings }, results, stats, run });
      }

      if (url.pathname === '/api/results' && req.method === 'PUT') {
        const body = await req.json();
        // On ne garde que les résultats des alertes qui existent encore.
        const ids = new Set((await getJSON(env, 'alerts', [])).map((a) => a.id));
        const results = Object.fromEntries(Object.entries(body.results || {}).filter(([id]) => ids.has(id)));
        await Promise.all([
          putJSON(env, 'results', results),
          putJSON(env, 'stats', body.stats || {}),
          putJSON(env, 'run', body.run || null),
        ]);
        return json({ ok: true });
      }

      // Mémoire détaillée des trajets d'une alerte : stockée telle quelle, sans être relue par le bot
      // (le JSON peut peser plusieurs centaines de Ko).
      const legsMatch = url.pathname.match(/^\/api\/legs\/(a\d+)$/);
      if (legsMatch) {
        const key = `legs:${legsMatch[1]}`;
        if (req.method === 'GET') {
          return new Response((await env.STATE.get(key)) || '{}', { headers: { 'content-type': 'application/json' } });
        }
        if (req.method === 'PUT') {
          await env.STATE.put(key, await req.text());
          return json({ ok: true });
        }
      }

      if (url.pathname === '/api/notify' && req.method === 'POST') {
        const owner = await getJSON(env, 'owner', null);
        if (owner === null) return json({ error: 'no owner yet' }, 409);
        const body = await req.json();
        for (const m of body.messages || []) await send(env, owner, m.text, !!m.silent);
        return json({ ok: true, sent: (body.messages || []).length });
      }

      return json({ error: 'not found' }, 404);
    }

    return new Response('Flight Radar : relais en ligne ✈️');
  },
};
