import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseAlert, describeAlert, parseSettings, DEFAULT_SETTINGS } from '../src/parse.js';

const T = '2026-11-22';

test('dates + plusieurs lieux + nuits + max', () => {
  const r = parseAlert('/alerte de LYS,GVA vers BCN,LIS du 01/03 au 31/03 nuits 2-4 max 80', T);
  assert.deepEqual(r.alert.origins, ['LYS', 'GVA']);
  assert.deepEqual(r.alert.destinations, ['BCN', 'LIS']);
  assert.equal(r.alert.date_from, '2027-03-01');
  assert.equal(r.alert.date_to, '2027-03-31');
  assert.deepEqual(r.alert.nights, [2, 4]);
  assert.equal(r.alert.max_price, 80);
});

test('partout + weekends en mois', () => {
  const r = parseAlert('/alerte de Lyon vers partout week-ends mars, avril max 60€ direct', T);
  assert.ok(!r.errors, JSON.stringify(r.errors));
  assert.deepEqual(r.alert.destinations, []);
  assert.equal(r.alert.weekends, true);
  assert.deepEqual(r.alert.months, ['2027-03', '2027-04']);
  assert.equal(r.alert.date_to, '2027-04-30');
  assert.deepEqual(r.alert.nights, [1, 3]);
  assert.equal(r.alert.direct, true);
  assert.equal(r.alert.max_price, 60);
});

test('aller simple + créneau + prio + mois en cours', () => {
  const r = parseAlert('/alerte de LYS vers OPO en décembre aller simple depart 6-12 prio', T);
  assert.ok(!r.errors, JSON.stringify(r.errors));
  assert.equal(r.alert.one_way, true);
  assert.equal(r.alert.nights, null);
  assert.deepEqual(r.alert.dep_window, [6, 12]);
  assert.equal(r.alert.priority, true);
  assert.equal(r.alert.date_from, '2026-12-01');
  assert.equal(r.alert.date_to, '2026-12-31');
});

test('ville multi-aéroports + 3j + date texte', () => {
  const r = parseAlert('/alerte de paris vers londres du 5 mars au 20 mars 3j', T);
  assert.ok(!r.errors, JSON.stringify(r.errors));
  assert.deepEqual(r.alert.origins, ['CDG', 'ORY']);
  assert.equal(r.alert.date_from, '2027-03-05');
  assert.deepEqual(r.alert.nights, [3, 3]);
});

test('erreurs claires', () => {
  const r = parseAlert('/alerte vers zanzibarr', T);
  assert.ok(r.errors.some((e) => e.includes('départ')));
  assert.ok(r.errors.some((e) => e.includes('zanzibarr')));
});

test('description', () => {
  const r = parseAlert('/alerte de LYS vers BCN weekends mars max 50', T);
  assert.match(describeAlert(r.alert), /LYS → BCN · week-ends mars 2027 · 1-3 nuits · max 50 €/);
});

test('réglages', () => {
  const r = parseSettings('/reglages frais 1,5 gain 10 silence off exclure in br', DEFAULT_SETTINGS);
  assert.equal(r.settings.fx_fee_pct, 1.5);
  assert.equal(r.settings.min_gain_eur, 10);
  assert.equal(r.settings.quiet, null);
  assert.deepEqual(r.settings.excluded_markets, ['in', 'br']);
});

test('mois en cours : on part d\'aujourd\'hui', () => {
  const r = parseAlert('/alerte de LYS vers BCN en novembre', T);
  assert.equal(r.alert.date_from, T);
  assert.equal(r.alert.date_to, '2026-11-30');
});
