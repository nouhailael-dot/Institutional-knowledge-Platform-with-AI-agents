import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {
  NAVIGATE,
  STATE_LABELS,
  WINDOWS,
  directoryRows,
  mapState,
  monthRangeLabel,
  monthSpending,
  recentMaps,
  recentRequests,
  requestRows,
  requestState,
  sinceStart,
  summaryCounts,
} from '../frontend/dashboard.js';

const NOW = new Date('2026-11-02T12:00:00');
const epoch = (iso) => new Date(iso).getTime() / 1000;
const run = (over = {}) => ({status: 'succeeded', started_at: '2026-11-01T10:00:00Z',
  finished_at: '2026-11-01T10:05:00Z', review_item_count: 0, staged_count: 0, found_count: 0,
  spent_usd: '0.50', ...over});

test('the activity filter offers 7, 30, 60 and 90 days, and navigation is one event', () => {
  assert.deepEqual(WINDOWS, [7, 30, 60, 90]);
  assert.equal(NAVIGATE, 'ghus:navigate');
});

test('spending counts this month only, from the 1st, maps included', () => {
  const total = monthSpending({
    requests: [{runs: [run(), run({started_at: '2026-10-31T23:00:00Z', spent_usd: '9'})]}],
    updates: [{runs: [run({spent_usd: '0.25'})]}],
    oneTime: [{started_at: '2026-11-02 08:00:00', spent_usd: 0.05}],
    maps: [{created: epoch('2026-11-01T15:00:00'), spent_usd: 0.2},
      {created: epoch('2026-10-20T15:00:00'), spent_usd: 5}],
  }, NOW);
  assert.equal(total, 1);
  assert.equal(monthRangeLabel(NOW), 'November 1–2, 2026');
  assert.equal(monthRangeLabel(new Date('2026-12-01T09:00:00')), 'December 1, 2026');
});

test('maps: Pending Review while Review Results holds their records, newest five in the window', () => {
  assert.equal(mapState({status: 'done', pending_review: 3}), 'pending_review');
  assert.equal(mapState({status: 'done', pending_review: 0}), 'completed');
  assert.equal(mapState({status: 'running'}), 'in_progress');
  const maps = Array.from({length: 7}, (_, i) => ({id: `m${i}`, status: 'done',
    description: `Map ${i}\nmore words`, map_type: i === 6 ? 'people' : 'organizations',
    created: epoch(`2026-10-${String(25 + (i % 7)).padStart(2, '0')}T10:00:00`)}));
  maps.push({id: 'old', status: 'done', description: 'Old', created: epoch('2026-08-01T10:00:00')});
  const rows = recentMaps(maps, 30, NOW);
  assert.equal(rows.length, 5);
  assert.equal(rows[0].id, 'm6');
  assert.equal(rows[0].name, 'Map 6');
  assert.ok(!rows.some(r => r.id === 'old'));
  assert.equal(recentMaps(maps, 7, NOW).length, 5);
  assert.equal(rows[0].category, 'People');
});

test('request states use the platform words, newest activity first', () => {
  const scheduled = {subscription_id: 's', status: 'active', next_run: {date: '2026-11-09'}, runs: []};
  const running = {subscription_id: 'r', status: 'active', runs: [run({status: 'running', finished_at: null})]};
  const failed = {subscription_id: 'f', status: 'expired', runs: [run({status: 'failed'})]};
  const found = {subscription_id: 'n', status: 'expired', runs: [run({review_item_count: 2})]};
  const quiet = {subscription_id: 'q', status: 'expired', runs: [run()]};
  assert.equal(requestState(scheduled, 'monitor'), 'scheduled');
  assert.equal(requestState(running, 'monitor'), 'in_progress');
  assert.equal(requestState(failed, 'monitor'), 'attention');
  // Completed with limits still completed: not a request needing attention.
  assert.equal(requestState({...found, runs: [run({status: 'attention'})]}, 'monitor'), 'completed');
  assert.equal(requestState(found, 'monitor'), 'new_update');
  assert.equal(requestState(quiet, 'monitor'), 'completed');
  // Opened from the Dashboard after the run finished: no longer new.
  assert.equal(requestState(found, 'monitor', new Date('2026-11-01T11:00:00Z').getTime()), 'completed');
  // An organization update's findings are its new or updated boxes.
  assert.equal(requestState({...quiet, runs: [run({found_count: 4})]}, 'update'), 'new_update');
  for (const state of ['completed', 'pending_review', 'in_progress', 'new_update', 'scheduled']) {
    assert.ok(STATE_LABELS[state]);
  }
  assert.equal(STATE_LABELS.new_update, 'New Update');
});

test('summary counts: maps awaiting review, requests with new findings, requests needing attention', () => {
  const rows = requestRows({
    requests: [
      {subscription_id: 'a', title: 'Iowa', status: 'expired', created_at: '2026-10-01T00:00:00Z',
        runs: [run({review_item_count: 3})]},
      {subscription_id: 'b', title: 'Stuck', status: 'active', created_at: '2026-10-01T00:00:00Z',
        runs: [run({status: 'running', stalled: true, finished_at: null})]},
      {subscription_id: 'd', title: 'October', status: 'expired', created_at: '2026-10-01T00:00:00Z',
        runs: [run({review_item_count: 5, started_at: '2026-10-10T09:00:00Z', finished_at: '2026-10-10T09:05:00Z'})]},
    ],
    updates: [{subscription_id: 'c', title: 'BioSTL', status: 'expired', created_at: '2026-10-01T00:00:00Z',
      runs: [run({found_count: 2, started_at: '2026-11-02T09:00:00Z'})]}],
  }, {a: '2026-11-02T00:00:00Z'}, null, NOW);
  // 'd' found things in October and was never opened: older than a week, not new.
  assert.deepEqual(rows.map(r => r.id), ['c', 'a', 'b', 'd']);
  assert.equal(rows[3].state, 'completed');
  assert.equal(rows[0].type, 'Organization update');
  assert.equal(rows[1].type, 'Topic monitoring');
  assert.deepEqual(summaryCounts({maps: [{pending_review: 2}, {pending_review: 0}], rows}),
    {mapsPending: 1, newUpdates: 1, attention: 1});
  assert.equal(recentRequests(rows, 7, NOW).length, 3);
});

test('Directory activity reads as "Verified by me" and keeps five', () => {
  const rows = directoryRows(Array.from({length: 6}, (_, i) => ({entity_id: `e${i}`,
    entity_type: i === 0 ? 'person' : 'actor', name: `N${i}`,
    action: ['verified', 'parked', 'added', 'updated'][i % 4], decided_at: '2026-11-01T00:00:00Z'})));
  assert.equal(rows.length, 5);
  assert.deepEqual(rows.slice(0, 4).map(r => `${r.category} · ${r.action}`),
    ['Person · Verified by me', 'Organization · Parked by me', 'Organization · Added by me',
     'Organization · Updated by me']);
});

test('the page is navigation only and every destination listens for it', () => {
  const page = fs.readFileSync(new URL('../frontend/dashboard.js', import.meta.url), 'utf8');
  for (const words of ['Your COMPASS workspace at a glance.', 'My Spending This Month', 'My Recent Activity',
    'Recent Maps', 'Recent Requests', 'Recent Directory Activity', 'View all maps', 'View all requests',
    'Open Directory']) {
    assert.ok(page.includes(words), words);
  }
  assert.ok(!/method:\s*"POST"/.test(page), 'the Dashboard never starts or changes anything');
  const shell = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  assert.ok(shell.includes('window.addEventListener(NAVIGATE,go)'));
  assert.ok(shell.includes('restore(id);};'), 'Explore and Map opens the map');
  assert.ok(shell.includes('useFocus(focus,data?.actors,setSel)'), 'the Directory opens the record');
  const monitor = fs.readFileSync(new URL('../frontend/discovery.js', import.meta.url), 'utf8');
  assert.ok(monitor.includes('id=${"request-" + request.subscription_id}'), 'Requests scrolls to the request');
});

test('the Directory activity panel never asks for a typed name', async () => {
  const src = fs.readFileSync(new URL('../frontend/dashboard.js', import.meta.url), 'utf8');
  assert.doesNotMatch(src, /Type your name/);
  assert.doesNotMatch(src, /ghus\.review\.reviewer/);
  // 11 Nov 2026 (GHUS): like the other panels - activity, or nothing in the period.
  assert.doesNotMatch(src, /once sign-in is on/);
  assert.match(src, /!activity\.signedIn \? `Nothing in the last \$\{days\} days\.`/);
});

test('a request running now is on the Dashboard, even one made before the trial', async () => {
  const {sinceStart, requestRows, recentRequests} = await import('../frontend/dashboard.js');
  const start = '2026-11-10T00:00:00Z';
  const old = {subscription_id: 'un', title: 'UN events updates', created_at: '2026-10-20T00:00:00Z',
    status: 'active', starting: true, runs: []};
  const shown = sinceStart({requests: [old]}, start);
  assert.equal(shown.requests.length, 1);
  const rows = requestRows({requests: shown.requests});
  assert.equal(recentRequests(rows, 7).length, 1);
});

test('spending counts the whole month from the 1st, and Compass opens on the Dashboard', () => {
  const src = fs.readFileSync(new URL('../frontend/dashboard.js', import.meta.url), 'utf8');
  assert.match(src, /<span>\$\{monthRangeLabel\(now\)\}<\/span>/);
  assert.match(src, /const spent = monthSpending\(\{requests: data\.requests/);
  const page = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  assert.match(page, /const \[tab,setTab\]=useState\("dashboard"\)/);
});

test('the hosted trial starts the Dashboard clean: nothing before its start counts', () => {
  const start = '2026-11-10T00:00:00Z';
  const now = new Date('2026-11-12T12:00:00Z');
  const data = {
    requests: [
      {subscription_id: 'old', created_at: '2026-11-03T09:00:00Z', runs: [run({started_at: '2026-11-03T10:00:00Z', spent_usd: '4'})]},
      {subscription_id: 'both', created_at: '2026-11-03T09:00:00Z', runs: [
        run({started_at: '2026-11-11T10:00:00Z', spent_usd: '0.30'}), run({started_at: '2026-11-04T10:00:00Z', spent_usd: '2'})]},
      {subscription_id: 'new', created_at: '2026-11-11T09:00:00Z', runs: []},
    ],
    updates: [{subscription_id: 'u', created_at: '2026-11-02T09:00:00Z', runs: [run({started_at: '2026-11-05T10:00:00Z', status: 'failed'})]}],
    oneTime: [{started_at: '2026-11-09T23:00:00Z', spent_usd: 1}, {started_at: '2026-11-10T08:00:00Z', spent_usd: 0.2}],
    maps: [{created: epoch('2026-11-08T10:00:00Z'), spent_usd: 3}, {created: epoch('2026-11-11T10:00:00Z'), spent_usd: 0.1}],
  };
  const shown = sinceStart(data, start);
  assert.deepEqual(shown.requests.map(r => r.subscription_id), ['both', 'new']);
  assert.equal(shown.requests[0].runs.length, 1);
  assert.deepEqual(shown.updates, []);           // its failed run was before: no "Needing Attention"
  assert.equal(monthSpending(shown, now), 0.6);
  assert.equal(monthSpending(sinceStart(data, null), now), 11.1);   // no start: unchanged
  assert.equal(monthRangeLabel(now, start), 'November 10–12, 2026');
  assert.equal(monthRangeLabel(new Date('2026-12-02T12:00:00Z'), start), 'December 1–2, 2026');
});
