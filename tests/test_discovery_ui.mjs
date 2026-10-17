import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {
  CADENCE_LABELS,
  addMonths,
  areaLabel,
  draftPayload,
  draftProblems,
  nextRunLabel,
  requestSummary,
} from '../frontend/discovery.js';

const OPTIONS = {
  topics: [{topic_id: 't-energy', code: 'ENERGY', name: 'Energy Transition'}],
  regions: [{code: 'northeast', name: 'Northeast', states: ['NY', 'MA']}],
  states: [{code: 'TX', name: 'Texas'}],
  max_new_actors_per_run: 50,
};

function form(overrides = {}) {
  return {
    title: 'Energy organizations in the Northeast', sector: 'ENERGY',
    focusTerms: ['battery storage'], focusInput: '', areaKind: 'region',
    region: 'northeast', state: '', city: '', startDate: '2026-10-14',
    duration: '3m', endDate: '2027-01-14', cadence: 'weekly', cap: 10,
    ...overrides,
  };
}

test('every cadence the backend allows has a label', () => {
  for (const cadence of ['once', 'weekly', 'biweekly', 'monthly', 'quarterly']) {
    assert.ok(CADENCE_LABELS[cadence], cadence);
  }
});

test('durations are calendar months and never exceed a year', () => {
  assert.equal(addMonths('2026-10-14', 3), '2027-01-14');
  assert.equal(addMonths('2026-01-31', 1), '2026-02-28');
  assert.equal(addMonths('2028-02-29', 12), '2029-02-28');
});

test('the summary reads back exactly what was asked', () => {
  const text = requestSummary(draftPayload(form()), OPTIONS);
  assert.match(text, /Energy Transition organizations in the Northeast/);
  assert.match(text, /focused on battery storage/);
  assert.match(text, /every week/);
  assert.match(text, /At most 10 new organizations per run/);
});

test('a state with a city is named precisely; no area means the whole country', () => {
  assert.equal(areaLabel({state_code: 'TX', city: 'Houston'}, OPTIONS), 'Houston, TX');
  assert.equal(areaLabel({state_code: 'TX'}, OPTIONS), 'Texas');
  assert.equal(areaLabel({}, OPTIONS), 'the United States');
});

test('the payload carries only the chosen area', () => {
  const region = draftPayload(form());
  assert.equal(region.region_code, 'northeast');
  assert.equal(region.state_code, undefined);
  const state = draftPayload(form({areaKind: 'state', state: 'TX', city: ' Houston '}));
  assert.deepEqual([state.region_code, state.state_code, state.city], [undefined, 'TX', 'Houston']);
  const us = draftPayload(form({areaKind: 'us'}));
  assert.equal(us.region_code, undefined);
  assert.equal(us.state_code, undefined);
});

test('a one-off request ends the day it starts', () => {
  const payload = draftPayload(form({cadence: 'once'}));
  assert.equal(payload.end_date, payload.start_date);
});

test('a request without a topic or name is not sent', () => {
  const problems = draftProblems(form({title: ' ', sector: ''}), OPTIONS);
  assert.ok(problems.title);
  assert.ok(problems.sector);
  assert.deepEqual(draftProblems(form(), OPTIONS), {});
});

test('the per-run ceiling and the period are checked before sending', () => {
  assert.ok(draftProblems(form({cap: 0}), OPTIONS).cap);
  assert.ok(draftProblems(form({cap: 51}), OPTIONS).cap);
  assert.ok(draftProblems(form({endDate: '2026-10-01'}), OPTIONS).duration);
});

test('a request that will not run again says why', () => {
  assert.equal(nextRunLabel({next_run: null, skip_reason: 'paused'}), 'Paused');
  assert.equal(nextRunLabel({next_run: null, skip_reason: 'expired'}), 'Period over');
  assert.match(nextRunLabel({next_run: '2026-10-21'}), /Oct 21, 2026/);
});

test('the page writes nothing itself: every call goes to /api/discovery', () => {
  const source = fs.readFileSync(new URL('../frontend/discovery.js', import.meta.url), 'utf8');
  const urls = [...source.matchAll(/api\(`?["'`]([^"'`$]+)/g)].map((m) => m[1]);
  assert.ok(urls.length >= 4);
  for (const url of urls) assert.ok(url.startsWith('/api/discovery/'), url);
});

test('Discovery is in the main navigation', () => {
  const index = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  assert.match(index, /\["discovery","Discovery",/);
  assert.match(index, /discovery:"Discovery"/);
  assert.match(index, /createDiscoveryPage/);
});

test('a request with a running run is shown as running', async () => {
  const {isRunning} = await import('../frontend/discovery.js');
  assert.equal(isRunning({runs: [{status: 'running'}]}), true);
  assert.equal(isRunning({runs: [{status: 'succeeded'}]}), false);
  assert.equal(isRunning({}), false);
});

test('every excluded candidate is shown with a kind and its reason', async () => {
  const {exclusionKind, exclusionSummary, EXCLUSION_LABELS, scoreLine} = await import('../frontend/discovery.js');
  const rows = [
    {triage_verdict: 'rejected', score_band: 'auto_low', triage_reason: 'Score 0.30 is below 0.45.'},
    {triage_verdict: 'not_read', score_band: null, triage_reason: 'Not read: budget reached.'},
    {triage_verdict: 'superseded', score_band: null, triage_reason: 'Re-read on its official site.'},
    {triage_verdict: 'analysis_failed', score_band: 'analysis_failed', triage_reason: '403'},
    {triage_verdict: 'capped', score_band: null, triage_reason: 'Held back.'},
  ];
  assert.deepEqual(rows.map(exclusionKind), ['rejected', 'not_read', 'superseded', 'failed', 'capped']);
  for (const row of rows) assert.ok(EXCLUSION_LABELS[exclusionKind(row)]);
  assert.match(exclusionSummary(rows), /1 rejected/);
  assert.equal(scoreLine({fit_score: 0.925, priority: 0.71}), 'Relevance 0.93 · Engagement priority 0.71');
});

test('a result shows only the facts its page stated', async () => {
  const {resultFacts} = await import('../frontend/discovery.js');
  const facts = Object.fromEntries(resultFacts({
    city: null, state: 'New York', country: 'United States', category: 'innovation_platform',
    focus: 'Battery storage', activities: '', funding: null, why_matched: 'Runs storage pilots.',
  }));
  assert.deepEqual(Object.keys(facts), ['Location', 'Type', 'Focus', 'Why it matched']);
  assert.equal(facts.Location, 'New York');
  assert.equal(facts.Type, 'Innovation platform');
});

test('a run shows its cost per relevant actor, not only its total', async () => {
  const {costPerRelevantActor, formatUsd} = await import('../frontend/discovery.js');
  assert.equal(formatUsd(0.9412), '$0.94');
  assert.equal(costPerRelevantActor({spent_usd: 0.94, staged_count: 0, review_item_count: 8}), '$0.12');
  assert.equal(costPerRelevantActor({spent_usd: 1.0, staged_count: 2, review_item_count: 2}), '$0.25');
  assert.equal(costPerRelevantActor({spent_usd: 0.5, staged_count: 0, review_item_count: 0}), 'None kept');
  assert.equal(costPerRelevantActor({spent_usd: null, staged_count: 1}), '');
});

test('a brief in plain words becomes the fields the agent runs on', async () => {
  const {resolveDraft, briefTerms, briefTitle, briefMatches} = await import('../frontend/discovery.js');
  const brief = 'Energy organizations in the Northeast\nbattery storage\ngrid modernisation';
  // The first line names the request; it is never searched for.
  assert.deepEqual(briefTerms(brief), ['battery storage', 'grid modernisation']);
  assert.deepEqual(briefTerms('One line only, with commas'), []);
  assert.equal(briefTitle(brief), 'Energy organizations in the Northeast');
  assert.deepEqual(briefMatches(brief, OPTIONS), {sector: 'ENERGY', region: 'northeast', state: null});

  const blank = form({title: '', sector: '', focusTerms: [], areaKind: 'region', region: '', brief});
  const draft = resolveDraft(blank, OPTIONS);
  assert.equal(draft.title, 'Energy organizations in the Northeast');
  assert.equal(draft.sector, 'ENERGY');
  assert.equal(draft.areaKind, 'region');
  assert.equal(draft.region, 'northeast');
  assert.ok(draft.focusTerms.includes('battery storage'));
});

test('what a person typed always beats what the brief implies', async () => {
  const {resolveDraft} = await import('../frontend/discovery.js');
  const typed = form({brief: 'Water organizations in Texas', title: 'My own name',
    sector: 'ENERGY', focusTerms: ['battery storage'], areaKind: 'us', areaTouched: true});
  const draft = resolveDraft(typed, OPTIONS);
  assert.equal(draft.title, 'My own name');
  assert.equal(draft.sector, 'ENERGY');
  assert.deepEqual(draft.focusTerms, ['battery storage']);
  assert.equal(draft.areaKind, 'us');
});

test('a brief naming no known sector is refused, and says so', async () => {
  const {draftProblems} = await import('../frontend/discovery.js');
  const vague = form({title: '', sector: '', focusTerms: [], brief: 'interesting places near me'});
  const problems = draftProblems(vague, OPTIONS);
  assert.match(problems.brief, /Name one of the sectors/);
  assert.ok(problems.sector);
  // With a sector named, the same brief is accepted.
  assert.equal(draftProblems(form({title: '', sector: '', focusTerms: [],
    brief: 'Energy organizations, battery storage'}), OPTIONS).sector, undefined);
});

test('a long line is flagged: every word of it must appear on the page', async () => {
  const {termIsTooLong, termStems} = await import('../frontend/discovery.js');
  assert.deepEqual(termStems('battery storage'), ['batt', 'stor']);
  assert.equal(termIsTooLong('battery storage'), false);
  assert.equal(termIsTooLong('organizations that work on battery storage for rural utilities'), true);
  // Passed straight to .some/.map, which hand the callback the index too: the
  // index must not be read as a limit, or every first term looks too long.
  assert.equal(['battery storage', 'grid modernisation'].some(termIsTooLong), false);
  assert.deepEqual(['battery storage', 'grid modernisation'].map(termIsTooLong), [false, false]);
});


test('actor updates read back each outcome the backend reports', async () => {
  const {OUTCOME_LABELS, outcomeSummary, factLine, boxLabel, ACTOR_UPDATE_SCOPES} =
    await import('../frontend/discovery.js');
  for (const key of ['filled', 'updated', 'confirmed', 'unchanged', 'not stated', 'refused']) {
    assert.ok(OUTCOME_LABELS[key], key);
  }
  assert.equal(outcomeSummary({updated: 1, unchanged: 1}), '1 updated · 1 kept');
  assert.equal(outcomeSummary({}), '');
  assert.equal(factLine({date: 'Aug. 12, 2026', description: 'Hosted GridFuture.'}),
    'Aug. 12, 2026 — Hosted GridFuture.');
  assert.equal(factLine('"$2M grant."'), '$2M grant.');
  assert.equal(factLine(null), '');
  assert.equal(boxLabel('funding_signal'), 'Funding');
  assert.equal(boxLabel('topic_mandate_program'), 'Topic mandate program');
  assert.deepEqual(ACTOR_UPDATE_SCOPES.map((s) => s.id), ['funding_activity', 'connections', '']);
});

test('suggestions highlight what was typed, and the group narrows the search', async () => {
  const {highlightParts, actorSearchParams, groupCaption} = await import('../frontend/discovery.js');
  assert.deepEqual(highlightParts('CPower Energy', 'pow'), [
    {text: 'C', match: false}, {text: 'Pow', match: true}, {text: 'er Energy', match: false}]);
  assert.deepEqual(highlightParts('Water for Water', 'water').filter((p) => p.match).length, 2);
  assert.deepEqual(highlightParts('CMU CyLab', ''), [{text: 'CMU CyLab', match: false}]);
  assert.equal(actorSearchParams('cpo', {sector: 'ENERGY', everyone: true}),
    'q=cpo&sector=ENERGY&everyone=true');
  assert.equal(actorSearchParams('  ', {state: 'WI'}), 'state=WI');
  assert.equal(groupCaption(17, 12, {sector: 'WATER', category: 'research_center'},
    [{code: 'WATER', name: 'Water'}]), '17 actors · Water · Research centre · showing 12');
  assert.equal(groupCaption(1, 1, {}), '1 actor');
});
