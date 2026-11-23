// Parseur des commandes /alerte et /reglages, écrites en français libre.
// Exemples acceptés :
//   /alerte de LYS,GVA vers BCN,LIS du 01/03 au 31/03 nuits 2-4 max 80
//   /alerte de lyon vers partout weekends mars,avril max 60 direct
//   /alerte de LYS vers OPO en mai aller-simple depart 6-12 prio

const MONTHS = {
  janvier: 1, janv: 1, jan: 1,
  fevrier: 2, fevr: 2, fev: 2,
  mars: 3, mar: 3,
  avril: 4, avr: 4,
  mai: 5,
  juin: 6,
  juillet: 7, juil: 7,
  aout: 8,
  septembre: 9, sept: 9, sep: 9,
  octobre: 10, oct: 10,
  novembre: 11, nov: 11,
  decembre: 12, dec: 12,
};

export const MONTH_LABELS = ['', 'janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];

// Villes courantes → aéroports. Pour le reste, utiliser le code IATA à 3 lettres.
export const CITIES = {
  lyon: ['LYS'], geneve: ['GVA'], grenoble: ['GNB'], 'saint-etienne': ['EBU'],
  paris: ['CDG', 'ORY'], beauvais: ['BVA'], marseille: ['MRS'], nice: ['NCE'],
  toulouse: ['TLS'], bordeaux: ['BOD'], nantes: ['NTE'], lille: ['LIL'],
  montpellier: ['MPL'], strasbourg: ['SXB'], bale: ['BSL'], mulhouse: ['BSL'],
  barcelone: ['BCN'], madrid: ['MAD'], seville: ['SVQ'], valence: ['VLC'], malaga: ['AGP'],
  palma: ['PMI'], lisbonne: ['LIS'], porto: ['OPO'], faro: ['FAO'],
  rome: ['FCO', 'CIA'], milan: ['MXP', 'LIN', 'BGY'], naples: ['NAP'], venise: ['VCE'],
  londres: ['LHR', 'LGW', 'STN', 'LTN'], dublin: ['DUB'], edimbourg: ['EDI'],
  amsterdam: ['AMS'], bruxelles: ['BRU', 'CRL'], berlin: ['BER'], munich: ['MUC'],
  vienne: ['VIE'], prague: ['PRG'], budapest: ['BUD'], cracovie: ['KRK'], varsovie: ['WAW', 'WMI'],
  copenhague: ['CPH'], stockholm: ['ARN'], oslo: ['OSL'], helsinki: ['HEL'],
  athenes: ['ATH'], istanbul: ['IST', 'SAW'], marrakech: ['RAK'], casablanca: ['CMN'],
  tunis: ['TUN'], alger: ['ALG'], dubrovnik: ['DBV'], split: ['SPU'], malte: ['MLA'],
  'new-york': ['JFK', 'EWR'], montreal: ['YUL'], tokyo: ['HND', 'NRT'], bangkok: ['BKK'],
};

// Jours au format Python (lundi = 0), utilisés par le moteur.
const DAYS = {
  lun: 0, lundi: 0, mar: 1, mardi: 1, mer: 2, mercredi: 2, jeu: 3, jeudi: 3,
  ven: 4, vendredi: 4, sam: 5, samedi: 5, dim: 6, dimanche: 6,
};
export const DAY_LABELS = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'];

const ANYWHERE = new Set(['partout', '*', 'nimporte', "n'importe", 'importe', 'tout']);

const KEYWORDS = new Set([
  'de', 'depuis', 'vers', 'pour', 'a', 'du', 'au', 'jusqu', "jusqu'au", 'en',
  'weekend', 'weekends', 'we', 'week-end', 'week-ends', 'max', 'budget', 'nuit', 'nuits',
  'sejour', 'jours', 'direct', 'aller-simple', 'simple', 'as', 'depart', 'retour', 'prio', 'aller',
  'escale', 'escales',
]);

// Durée d'escale : "2h", "2", "1h30", "90min" → heures.
export function parseHours(tok) {
  const m = (tok || '').match(/^(\d{1,2})(?:h(\d{2})?)?$|^(\d{2,3})min$/);
  if (!m) return null;
  if (m[3]) return Number(m[3]) / 60;
  return Number(m[1]) + (m[2] ? Number(m[2]) / 60 : 0);
}

export function normalize(s) {
  return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[’`]/g, "'").trim();
}

function pad(n) { return String(n).padStart(2, '0'); }
export function iso(y, m, d) { return `${y}-${pad(m)}-${pad(d)}`; }
function lastDay(y, m) { return new Date(Date.UTC(y, m, 0)).getUTCDate(); }

function todayParts(today) {
  const [y, m, d] = today.split('-').map(Number);
  return { y, m, d };
}

// Mois sans année → prochaine occurrence (le mois en cours compte).
function monthYear(m, today) {
  const t = todayParts(today);
  return m >= t.m ? t.y : t.y + 1;
}

function parseMonthToken(tok, today) {
  const t = tok.replace(/\.$/, '');
  if (MONTHS[t]) { const m = MONTHS[t]; return { y: monthYear(m, today), m }; }
  let r = t.match(/^(\d{1,2})[/-](\d{4})$/);
  if (r) return { y: Number(r[2]), m: Number(r[1]) };
  return null;
}

// Renvoie { date, used } (used = nombre de tokens consommés) ou null.
function parseDateAt(tokens, i, today) {
  const tok = tokens[i];
  if (!tok) return null;
  let r = tok.match(/^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?$/);
  if (r) {
    const d = Number(r[1]); const m = Number(r[2]);
    let y = r[3] ? Number(r[3]) : null;
    if (y !== null && y < 100) y += 2000;
    if (y === null) {
      const t = todayParts(today);
      y = t.y;
      if (iso(y, m, d) < today) y += 1;
    }
    if (m < 1 || m > 12 || d < 1 || d > lastDay(y, m)) return null;
    return { date: iso(y, m, d), used: 1 };
  }
  // "5 mars [2027]"
  if (/^\d{1,2}$/.test(tok) && MONTHS[(tokens[i + 1] || '').replace(/\.$/, '')]) {
    const d = Number(tok); const m = MONTHS[tokens[i + 1].replace(/\.$/, '')];
    let used = 2; let y;
    if (/^\d{4}$/.test(tokens[i + 2] || '')) { y = Number(tokens[i + 2]); used = 3; } else {
      const t = todayParts(today); y = t.y; if (iso(y, m, d) < today) y += 1;
    }
    if (d < 1 || d > lastDay(y, m)) return null;
    return { date: iso(y, m, d), used };
  }
  return null;
}

function parseRange(tok) {
  // "6-12", "6h-12h", "2-4", "3"
  const r = tok.replace(/h/g, '').match(/^(\d{1,2})(?:-(\d{1,2}))?$/);
  if (!r) return null;
  const a = Number(r[1]); const b = r[2] !== undefined ? Number(r[2]) : a;
  return [Math.min(a, b), Math.max(a, b)];
}

// Créneau horaire : "18-24", "18h-23h", "apres 18", "avant 6", "6h".
function parseWindowAt(tokens, i) {
  const t = tokens[i] || '';
  const hour = /^\d{1,2}h?$/.test(tokens[i + 1] || '') ? parseInt(tokens[i + 1], 10) : null;
  if (hour !== null && hour <= 24 && (t === 'apres' || t === 'des')) return { win: [hour, 24], used: 2 };
  if (hour !== null && hour <= 24 && t === 'avant') return { win: [0, hour], used: 2 };
  const r = t.replace(/h/g, '').match(/^(\d{1,2})-(\d{1,2})$/);
  if (r) {
    const a = Number(r[1]); const b = Number(r[2]);
    if (a <= 24 && b <= 24) return { win: [Math.min(a, b), Math.max(a, b)], used: 1 };
  }
  const one = t.match(/^(\d{1,2})h$/);
  if (one) { const a = Number(one[1]); return { win: [a, Math.min(a + 1, 24)], used: 1 }; }
  return null;
}

// Après "depart"/"aller"/"retour" : jours (avec créneau), dates précises, ou créneau seul.
function parseLegSpec(tokens, i, today) {
  const spec = { rules: null, dates: [], window: null };
  let j = i;
  while (j < tokens.length) {
    const t = tokens[j];
    if ([',', 'et', 'ou', 'le', 'les', 'puis'].includes(t)) { j++; continue; }
    if (DAYS[t] !== undefined) {
      spec.rules = spec.rules || {};
      const w = parseWindowAt(tokens, j + 1);
      spec.rules[DAYS[t]] = w ? w.win : null;
      j += 1 + (w ? w.used : 0);
      continue;
    }
    const dt = /^\d{1,2}[/.]\d{1,2}([/.]\d{2,4})?$/.test(t) ? parseDateAt(tokens, j, today) : null;
    if (dt) { spec.dates.push(dt.date); j += dt.used; continue; }
    const w = parseWindowAt(tokens, j);
    if (w) { spec.window = w.win; j += w.used; continue; }
    break;
  }
  return { spec, next: j, used: j - i };
}

function parsePlaces(list) {
  const out = []; const errors = [];
  for (const raw of list) {
    const p = raw.trim();
    if (!p || p === ',' || p === 'ou' || p === 'et' || p === '/') continue;
    if (ANYWHERE.has(p)) { out.push('*'); continue; }
    if (CITIES[p]) { out.push(...CITIES[p]); continue; }
    if (/^[a-z]{3}$/.test(p)) { out.push(p.toUpperCase()); continue; }
    errors.push(raw);
  }
  return { places: [...new Set(out)], errors };
}

function isKeyword(tok) {
  return KEYWORDS.has(tok) || /^\d+(€|e|eur)$/.test(tok);
}

export function parseAlert(text, today) {
  const norm = normalize(text)
    .replace(/^\/alerte(@\w+)?/, '')
    .replace(/aller[\s-]simple/g, 'aller-simple')
    .replace(/week[\s-]?ends?/g, 'weekends')
    .replace(/n'importe(\s+ou)?/g, 'partout')
    .replace(/sans[\s-]escales?/g, 'direct')
    .replace(/jusqu'?au/g, 'au')
    .replace(/,/g, ' , ')
    .replace(/\s+/g, ' ')
    .trim();
  const tokens = norm ? norm.split(' ') : [];

  const a = {
    origins: [], destinations: [], date_from: null, date_to: null, months: [],
    weekends: false, nights: null, one_way: false, direct: false, max_price: null,
    dep_window: null, ret_window: null, priority: false,
    out_rules: null, ret_rules: null, out_dates: null, ret_dates: null, max_layover: null,
  };
  const errors = [];
  let destSet = false;

  const collect = (start) => {
    const list = []; let j = start;
    while (j < tokens.length && !(isKeyword(tokens[j]) && tokens[j] !== ',')) { list.push(tokens[j]); j++; }
    return { list, next: j };
  };

  let i = 0;
  while (i < tokens.length) {
    const tok = tokens[i];
    if (tok === 'de' || tok === 'depuis') {
      const { list, next } = collect(i + 1);
      const { places, errors: e } = parsePlaces(list);
      a.origins.push(...places.filter((p) => p !== '*'));
      e.forEach((x) => errors.push(`Lieu inconnu : « ${x} » (mets le code aéroport à 3 lettres)`));
      i = next; continue;
    }
    if (tok === 'vers' || tok === 'pour' || tok === 'a') {
      const { list, next } = collect(i + 1);
      const { places, errors: e } = parsePlaces(list);
      destSet = true;
      if (places.includes('*')) a.destinations = [];
      else a.destinations.push(...places);
      e.forEach((x) => errors.push(`Lieu inconnu : « ${x} » (mets le code aéroport à 3 lettres)`));
      i = next; continue;
    }
    if (tok === 'du' || tok === 'au') {
      const r = parseDateAt(tokens, i + 1, today);
      if (!r) { errors.push(`Date illisible après « ${tok} » (format JJ/MM ou JJ/MM/AAAA)`); i += 2; continue; }
      if (tok === 'du') a.date_from = r.date; else a.date_to = r.date;
      i += 1 + r.used; continue;
    }
    if (tok === 'weekends' || tok === 'we' || tok === 'en') {
      if (tok !== 'en') a.weekends = true;
      let j = i + 1;
      while (j < tokens.length) {
        if (tokens[j] === ',' || tokens[j] === 'et' || tokens[j] === 'ou') { j++; continue; }
        const mm = parseMonthToken(tokens[j], today);
        if (!mm) break;
        a.months.push(`${mm.y}-${pad(mm.m)}`);
        j++;
      }
      i = j; continue;
    }
    if (tok === 'escale' || tok === 'escales') {
      let j = i + 1;
      if (['max', 'maximum', 'de', 'moins', 'courte', 'courtes'].includes(tokens[j])) j++;
      if (tokens[j] === 'de') j++;
      const h = parseHours(tokens[j]);
      if (h !== null && h > 0) { a.max_layover = h; i = j + 1; continue; }
      errors.push('Durée d\'escale illisible (ex. escale max 2h)');
      i = j; continue;
    }
    if (tok === 'max' || tok === 'budget') {
      const n = parseFloat((tokens[i + 1] || '').replace(/(€|eur|e)$/, ''));
      if (Number.isFinite(n)) { a.max_price = n; i += 2; } else { errors.push('Prix max illisible'); i += 1; }
      continue;
    }
    let m = tok.match(/^<?(\d+)(€|e|eur)$/);
    if (m || (tok === '<' && /^\d+/.test(tokens[i + 1] || ''))) {
      a.max_price = Number(m ? m[1] : parseInt(tokens[i + 1], 10));
      i += m ? 1 : 2; continue;
    }
    if (tok === 'nuit' || tok === 'nuits' || tok === 'sejour' || tok === 'jours') {
      const r = parseRange(tokens[i + 1] || '');
      if (r) { a.nights = r; i += 2; continue; }
      i += 1; continue;
    }
    m = tok.match(/^(\d{1,2}(?:-\d{1,2})?)(n|nuits?|j|jours?)?$/);
    if (m && (m[2] || ['nuit', 'nuits', 'jours', 'j'].includes(tokens[i + 1]))) {
      a.nights = parseRange(m[1]);
      i += m[2] ? 1 : 2; continue;
    }
    if (tok === 'direct') { a.direct = true; i++; continue; }
    if (tok === 'aller-simple' || tok === 'as' || tok === 'simple') { a.one_way = true; i++; continue; }
    if (tok === 'depart' || tok === 'retour' || tok === 'aller') {
      const { spec, next, used } = parseLegSpec(tokens, i + 1, today);
      if (!used) { errors.push(`Rien de compris après « ${tok} » (ex. ${tok} jeu apres 18, ven apres 12 · ${tok} 30/12,31/12 · ${tok} 6-12)`); i += 1; continue; }
      const side = tok === 'retour' ? 'ret' : 'out';
      if (spec.rules) a[`${side}_rules`] = { ...(a[`${side}_rules`] || {}), ...spec.rules };
      if (spec.dates.length) a[`${side}_dates`] = [...(a[`${side}_dates`] || []), ...spec.dates].sort();
      if (spec.window) a[side === 'ret' ? 'ret_window' : 'dep_window'] = spec.window;
      i = next; continue;
    }
    if (tok === 'prio') { a.priority = true; i++; continue; }
    if (tok === ',') { i++; continue; }
    errors.push(`Mot non compris : « ${tok} »`);
    i++;
  }

  a.origins = [...new Set(a.origins)];
  a.destinations = [...new Set(a.destinations)];
  a.months = [...new Set(a.months)].sort();

  if (!a.origins.length) errors.push('Il manque le départ (ex. « de LYS »)');
  if (!destSet) errors.push('Il manque la destination (ex. « vers BCN » ou « vers partout »)');

  // Période
  if (a.out_dates && a.out_dates.length && !a.date_from && !a.months.length) {
    a.date_from = a.out_dates[0];
    a.date_to = a.out_dates[a.out_dates.length - 1];
  }
  if (a.months.length) {
    const [fy, fm] = a.months[0].split('-').map(Number);
    const [ly, lm] = a.months[a.months.length - 1].split('-').map(Number);
    a.date_from = a.date_from || iso(fy, fm, 1);
    a.date_to = a.date_to || iso(ly, lm, lastDay(ly, lm));
  }
  if (!a.date_from && !a.date_to) {
    a.date_from = addDays(today, 1);
    a.date_to = addDays(today, 90);
  } else if (!a.date_from) {
    a.date_from = addDays(today, 1);
  } else if (!a.date_to) {
    a.date_to = addDays(a.date_from, 30);
  }
  if (a.date_from < today) a.date_from = today;
  if (a.date_to < a.date_from) errors.push('La date de fin est avant la date de début');
  if (daysBetween(a.date_from, a.date_to) > 330) errors.push('Période trop longue (11 mois maximum)');

  const flexible = a.out_rules || a.ret_rules || a.out_dates || a.ret_dates;
  if (a.one_way) a.nights = null;
  else if (!a.nights && !flexible) a.nights = a.weekends ? [1, 3] : [2, 7];
  if (a.ret_dates && a.out_dates && a.ret_dates[0] <= a.out_dates[0]) errors.push('Le retour doit être après l\'aller');

  if (errors.length) return { errors };
  return { alert: a };
}

export function addDays(isoDate, n) {
  const d = new Date(`${isoDate}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function daysBetween(a, b) {
  return Math.round((new Date(`${b}T12:00:00Z`) - new Date(`${a}T12:00:00Z`)) / 86400000);
}

function fmtDate(isoDate) {
  const [y, m, d] = isoDate.split('-').map(Number);
  return `${d} ${MONTH_LABELS[m]} ${y}`;
}

export function fmtHours(h) {
  const m = Math.round(h * 60);
  return m % 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m / 60}h`;
}

export function describeAlert(a) {
  const parts = [];
  parts.push(`${a.origins.join(',')} → ${a.destinations.length ? a.destinations.join(',') : 'partout'}`);
  if (a.months && a.months.length) {
    const labels = a.months.map((s) => { const [y, m] = s.split('-').map(Number); return `${MONTH_LABELS[m]} ${y}`; });
    parts.push(`${a.weekends ? 'week-ends ' : ''}${labels.join(', ')}`);
  } else if (!a.out_dates) {
    parts.push(`${a.weekends ? 'week-ends du ' : 'du '}${fmtDate(a.date_from)} au ${fmtDate(a.date_to)}`);
  }
  if (a.one_way) parts.push('aller simple');
  else if (a.nights) parts.push(a.nights[0] === a.nights[1] ? `${a.nights[0]} nuit(s)` : `${a.nights[0]}-${a.nights[1]} nuits`);
  const fmtWin = (w) => (!w ? '' : (w[1] >= 24 ? ` après ${w[0]}h` : (w[0] === 0 ? ` avant ${w[1]}h` : ` ${w[0]}h-${w[1]}h`)));
  const fmtRules = (r) => Object.keys(r).map(Number).sort((x, y) => ((x + 6) % 7) - ((y + 6) % 7))
    .map((k) => `${DAY_LABELS[k]}${fmtWin(r[k])}`).join(', ');
  const fmtDates = (ds) => ds.map((x) => { const [, m, dd] = x.split('-').map(Number); return `${dd}/${String(m).padStart(2, '0')}`; }).join(' ou ');
  if (a.out_rules) parts.push(`aller ${fmtRules(a.out_rules)}`);
  if (a.out_dates) parts.push(`aller le ${fmtDates(a.out_dates)}`);
  if (a.ret_rules) parts.push(`retour ${fmtRules(a.ret_rules)}`);
  if (a.ret_dates) parts.push(`retour le ${fmtDates(a.ret_dates)}`);
  if (a.max_price) parts.push(`max ${a.max_price} €`);
  if (a.direct) parts.push('direct');
  if (a.max_layover) parts.push(`escale ≤ ${fmtHours(a.max_layover)}`);
  if (a.dep_window) parts.push(`départ${fmtWin(a.dep_window)}`);
  if (a.ret_window) parts.push(`retour${fmtWin(a.ret_window)}`);
  if (a.priority) parts.push('⚡ prio');
  return parts.join(' · ');
}

export function parseSettings(text, current) {
  const s = { ...current };
  const t = normalize(text).replace(/^\/reglages(@\w+)?/, '').replace(/,/g, '.').trim();
  const errors = [];
  let m;
  if ((m = t.match(/frais\s+(\d+(?:\.\d+)?)/))) s.fx_fee_pct = Number(m[1]);
  if ((m = t.match(/gain\s+(\d+(?:\.\d+)?)/))) s.min_gain_eur = Number(m[1]);
  if ((m = t.match(/baisse\s+(\d+(?:\.\d+)?)/))) s.drop_pct = Number(m[1]);
  if (/silence\s+(off|non|aucun)/.test(t)) s.quiet = null;
  else if ((m = t.match(/silence\s+(\d{1,2})h?-(\d{1,2})h?/))) s.quiet = [Number(m[1]), Number(m[2])];
  if ((m = t.match(/pays\s+(\d+)/))) s.markets_per_search = Math.max(1, Math.min(8, Number(m[1])));
  if ((m = t.match(/exclure\s+([a-z ,]+)/))) s.excluded_markets = m[1].split(/[ ,]+/).filter((x) => x.length === 2);
  if ((m = t.match(/inclure\s+([a-z ,]+)/))) {
    const inc = m[1].split(/[ ,]+/).filter((x) => x.length === 2);
    s.excluded_markets = (s.excluded_markets || []).filter((x) => !inc.includes(x));
  }
  if (JSON.stringify(s) === JSON.stringify(current) && t) errors.push('Réglage non compris');
  return { settings: s, errors };
}

export const DEFAULT_SETTINGS = {
  fx_fee_pct: 2,
  min_gain_eur: 15,
  drop_pct: 5,
  quiet: [23, 7],
  markets_per_search: 3,
  excluded_markets: [],
};
