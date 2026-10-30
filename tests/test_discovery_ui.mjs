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

test('the per-run ceiling and the schedule are checked before sending', async () => {
  const {scheduleEnd, scheduleProblems, previewProblems, frequencyOptions, DURATION_PRESETS} =
    await import('../frontend/discovery.js');
  assert.ok(draftProblems(form({cap: 0}), OPTIONS).cap);
  assert.ok(draftProblems(form({cap: 51}), OPTIONS).cap);
  // Frequency, Start Date and Duration start on their placeholders and must be chosen;
  // Duration only for a recurring request, which begins on its start date.
  assert.deepEqual(Object.keys(scheduleProblems({cadence: '', startDate: '', duration: ''})),
    ['frequency', 'start']);
  assert.ok(draftProblems(form({cadence: 'weekly', duration: ''}), OPTIONS).duration);
  assert.equal(draftProblems(form({cadence: 'once', duration: ''}), OPTIONS).duration, undefined);
  assert.equal(scheduleProblems({cadence: 'once', startDate: '2026-10-01', duration: ''},
    '2026-10-14').start, 'Choose today or a later date.');
  assert.equal(scheduleEnd({cadence: 'monthly', startDate: '2026-10-14', duration: '6m'}), '2027-04-14');
  assert.equal(scheduleEnd({cadence: 'once', startDate: '2026-10-14', duration: '6m'}), '2026-10-14');
  assert.deepEqual(DURATION_PRESETS.map((d) => d.label), ['1 month', '3 months', '6 months', '12 months']);
  // Events and organizations offer Daily, people do not; only what the database accepts.
  assert.deepEqual(frequencyOptions('event'), ['once', 'daily', 'weekly', 'monthly']);
  assert.deepEqual(frequencyOptions('person'), ['once', 'weekly', 'monthly']);
  assert.deepEqual(frequencyOptions('actor', ['once', 'weekly', 'monthly']), ['once', 'weekly', 'monthly']);
  // A preview needs no schedule.
  assert.deepEqual(previewProblems({title: 'x', frequency: 'y', start: 'z'}), {title: 'x'});
});

test('a request that will not run again says why', () => {
  assert.equal(nextRunLabel({next_run: null, skip_reason: 'paused'}), 'Paused');
  assert.equal(nextRunLabel({next_run: null, skip_reason: 'expired'}), 'Period over');
  assert.match(nextRunLabel({next_run: '2026-10-21'}), /^10\/21\/2026$/);
});

test('the page writes nothing itself: every call goes to /api/discovery', () => {
  const source = fs.readFileSync(new URL('../frontend/discovery.js', import.meta.url), 'utf8');
  const urls = [...source.matchAll(/api\(`?["'`]([^"'`$]+)/g)].map((m) => m[1]);
  assert.ok(urls.length >= 4);
  for (const url of urls) assert.ok(url.startsWith('/api/discovery/'), url);
});

test('Discovery is in the main navigation', () => {
  const index = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  // The COMPASS navigation (2026-10-29): [id, label], an icon per id.
  assert.match(index, /\["discovery","Monitor and Update"\]/);
  assert.match(index, /discovery:svg\(/);
  assert.match(index, /display:tab==="discovery"/);
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
  const {OUTCOME_LABELS, RESULT_GROUPS, outcomeSummary, factLine, boxLabel, findingsIn} =
    await import('../frontend/discovery.js');
  // Every outcome actor_updates.classify can return has a label.
  for (const key of ['new', 'changed', 'additional', 'corroborated', 'conflict', 'protected',
    'unchanged', 'not_found', 'not_yet_collected']) {
    assert.ok(OUTCOME_LABELS[key], key);
  }
  assert.deepEqual(RESULT_GROUPS.map((g) => g.id),
    ['new', 'changed', 'additional', 'conflicts', 'confirmed', 'missing', 'no_change']);
  assert.equal(outcomeSummary({changed: 2, new: 1, conflicts: 1}),
    '1 new · 2 changed · 1 conflicts requiring review');
  assert.equal(outcomeSummary({}), '');
  assert.equal(outcomeSummary({additional: 2}), '2 additional details');
  const findings = [{field: 'a', group: 'new'}, {field: 'b', group: 'conflicts'}];
  assert.deepEqual(findingsIn(findings, 'conflicts').map((f) => f.field), ['b']);
  assert.equal(findingsIn(findings, 'all').length, 2);
  assert.equal(factLine({date: 'Aug. 12, 2026', description: 'Hosted GridFuture.'}),
    'Aug. 12, 2026 — Hosted GridFuture.');
  assert.equal(factLine('"$2M grant."'), '$2M grant.');
  assert.equal(factLine(null), '');
  assert.equal(factLine({city: 'Austin', country: 'US', is_multi_location: false}), 'Austin · US');
  assert.equal(factLine({employees: 600, customers: 2000, carried_over: ['customers']}),
    '600 · 2000 (kept from earlier reading: Customers)');
  assert.equal(boxLabel('funding_signal'), 'Funding');
  assert.equal(boxLabel('topic_mandate_program'), 'Topic mandate program');
});

test('an update offers two choices, four kinds of information, and sends the backend words', async () => {
  const {ACTOR_UPDATE_SCOPES, UPDATE_KINDS, INFORMATION_FOCUS, UPDATE_FREQUENCIES,
    UPDATE_DURATIONS, UPDATE_QUESTION_EXAMPLE, focusCategories, updateChoiceProblem, updateRequestBody} =
    await import('../frontend/discovery.js');
  assert.deepEqual(UPDATE_KINDS.map((k) => k.label), ['General Update', 'Specific Changes']);
  assert.equal(UPDATE_KINDS[0].hint, 'Check the selected organizations for new, missing, or outdated information.');
  assert.equal(UPDATE_KINDS[1].hint, 'Look for updates about a particular topic or type of information.');
  assert.deepEqual(INFORMATION_FOCUS.map((x) => x.label), ['Research, Projects & Technology',
    'Funding & Partnerships', 'Organization & Activities', 'Locations & Operations']);
  // The four cover the seven backend change categories, each exactly once.
  assert.deepEqual(INFORMATION_FOCUS.flatMap((x) => x.categories).sort(),
    ['category', 'funding', 'geography', 'organization', 'partnerships', 'products', 'research']);
  assert.equal(UPDATE_QUESTION_EXAMPLE,
    'Has this organization launched any new battery storage projects or partnerships?');
  // Saved requests keep reading back in every backend scope.
  assert.deepEqual(ACTOR_UPDATE_SCOPES.map((s) => s.id),
    ['general', 'topic', 'missing', 'outdated', 'specific']);
  // No "Once": a one-time check is the separate Run now.
  assert.deepEqual(UPDATE_FREQUENCIES.map((f) => [f.id, f.label]), [['weekly', 'Every Week'],
    ['biweekly', 'Every 2 Weeks'], ['monthly', 'Every Month'], ['quarterly', 'Every 3 Months']]);
  assert.deepEqual(UPDATE_DURATIONS.map((d) => d.months), [1, 3, 6, 12]);
  assert.deepEqual(focusCategories(['locations', 'research']), ['research', 'products', 'geography']);

  const form = {kind: 'general', interests: ['funding'], focus: 'desalination', topic: 'WATER', depth: 'light'};
  // General reads every box of the category: new, missing and out of date alike;
  // the chosen information is read first, and the question belongs to Specific.
  assert.deepEqual(updateRequestBody(form), {scope: 'general', depth: 'light', topic: 'WATER',
    categories: ['funding', 'partnerships']});
  assert.deepEqual(updateRequestBody({...form, interests: []}), {scope: 'general', depth: 'light', topic: 'WATER'});
  assert.deepEqual(updateRequestBody({...form, kind: 'specific'}), {scope: 'specific', depth: 'light',
    topic: 'WATER', categories: ['funding', 'partnerships'], focus: 'desalination'});
  // Only a question: every box, steered by its words (a sector is needed for "topic").
  assert.deepEqual(updateRequestBody({...form, kind: 'specific', interests: []}),
    {scope: 'topic', depth: 'light', topic: 'WATER', focus: 'desalination'});
  assert.deepEqual(updateRequestBody({...form, kind: 'specific', interests: [], topic: ''}),
    {scope: 'general', depth: 'light', focus: 'desalination'});
  assert.equal(updateChoiceProblem({...form, kind: 'specific', interests: [], focus: '  '}),
    'Choose the information you are interested in, or write a topic or question.');
  assert.equal(updateChoiceProblem({...form, kind: 'general', interests: [], focus: ''}), '');
});

test('a schedule first runs one interval after today, never today, and ends after the duration', async () => {
  const {updateSchedule} = await import('../frontend/discovery.js');
  assert.deepEqual(updateSchedule('2026-10-20', 'weekly', 3),
    {start_date: '2026-10-27', end_date: '2027-01-20', problem: ''});
  assert.equal(updateSchedule('2026-10-20', 'biweekly', 1).start_date, '2026-11-03');
  assert.equal(updateSchedule('2026-10-20', 'monthly', 6).start_date, '2026-11-20');
  assert.equal(updateSchedule('2026-10-20', 'quarterly', 12).start_date, '2027-01-20');
  // Calendar months, short months clamped.
  assert.equal(updateSchedule('2027-01-31', 'monthly', 3).start_date, '2027-02-28');
  // Twelve months stay within the 365-day ceiling.
  assert.equal(updateSchedule('2026-10-20', 'weekly', 12).end_date, '2027-10-20');
  assert.match(updateSchedule('2026-10-20', 'quarterly', 1).problem, /needs longer than 1 month/);
  assert.equal(updateSchedule('2026-10-20', 'quarterly', 3).problem, '');
});

test('the request preview reads as one plain sentence', async () => {
  const {updateSummary, estimateLine} = await import('../frontend/discovery.js');
  const form = {kind: 'specific', interests: ['research', 'funding'], focus: '', depth: 'light',
    cadence: 'weekly', months: 3};
  assert.equal(updateSummary({form, count: 4}), 'Check these organizations every week for three months, '
    + 'starting next week. Look for updates on research, projects and technology and funding and '
    + 'partnerships using Light Refresh.');
  assert.equal(updateSummary({form: {...form, kind: 'general', interests: [], cadence: 'monthly', months: 6}, count: 1}),
    'Check this organization every month for six months, starting next month. Look for new, missing, '
    + 'or outdated information using Light Refresh.');
  assert.equal(updateSummary({form: {...form, kind: 'general', interests: ['locations']}, count: 3}),
    'Check these organizations every week for three months, starting next week. Look for new, missing, '
    + 'or outdated information (locations and operations first) using Light Refresh.');
  assert.equal(updateSummary({form: {...form, interests: [], focus: 'battery storage'}, count: 2, runNow: true}),
    'Check these organizations now, once. Look for updates about “battery storage”, using Light Refresh.');
  assert.equal(estimateLine({expected_usd: 0.04}, 13), 'About $0.04 a check; about $0.52 over 13 checks.');
  assert.equal(estimateLine({expected_usd: null, typical_usd: null, per_actor_cap_usd: 0.15}),
    'No past checks to estimate from yet; each organization costs at most $0.15 a check.');
  assert.equal(estimateLine(null), '');
});

test('the cost line states the cap and only history that exists', async () => {
  const {costLine} = await import('../frontend/discovery.js');
  assert.equal(costLine({cap_usd: 0.15, runs: 0, typical_usd: null}),
    'No update has run yet, so there is no history; never more than $0.15.');
  assert.equal(costLine({cap_usd: 0.15, runs: 4, low_usd: 0.02, typical_usd: 0.03, high_usd: 0.05}),
    'Usually $0.03 (4 past reads, $0.02–$0.05); never more than $0.15.');
  assert.equal(costLine(null), '');
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

test('an update request is sent as one actor, the picked actors, or a group with a sector', async () => {
  const {updateRequestDraft} = await import('../frontend/discovery.js');
  const form = {kind: 'specific', interests: ['funding'], focus: '', topic: '', depth: 'light',
    cadence: 'monthly', months: 3};
  const today = '2026-10-20';
  assert.deepEqual(updateRequestDraft({mode: 'one', form, selected: {actor_id: 'a1'}, today}), {
    scope: 'specific', depth: 'light', categories: ['funding', 'partnerships'], cadence: 'monthly',
    actor_ids: ['a1'], max_actors_per_run: 1, start_date: '2026-11-20', end_date: '2027-01-20'});
  const picked = [{actor_id: 'a1'}, {actor_id: 'a2'}];
  // Run now is a one-time request that starts today; a run never reads more than were picked.
  const now = updateRequestDraft({mode: 'several', form, picked, today, runNow: true});
  assert.deepEqual([now.actor_ids, now.max_actors_per_run, now.cadence, now.start_date, now.end_date],
    [['a1', 'a2'], 2, 'once', undefined, undefined]);
  // No user-set limits: the backend's own safeguards apply to a group.
  const grouped = updateRequestDraft({mode: 'several', form, useGroup: true, today,
    group: {sector: 'WATER', category: '', state: 'CA'}});
  assert.deepEqual([grouped.group, grouped.actor_ids, grouped.max_actors_per_run, grouped.max_usd_per_run],
    [{sector: 'WATER', state: 'CA'}, undefined, undefined, undefined]);
});

test('saved requests and their runs read back in plain words', async () => {
  const {updateRequestScope, actorResultLine} = await import('../frontend/discovery.js');
  // Requests saved before the two-choice form still read back.
  assert.equal(updateRequestScope({update_options: {scope: 'missing', category: 'company',
    max_actors_per_run: 5}, sector_codes: ['WATER'], state_code: 'CA', max_usd_per_run: 1.5},
  [{code: 'WATER', name: 'Water'}]),
  'Missing information · Water · Company · CA');
  assert.equal(updateRequestScope({update_options: {scope: 'general', max_actors_per_run: 1},
    actor_names: ['CPower Energy'], max_usd_per_run: 0.15}),
  'General Update · CPower Energy');
  assert.equal(updateRequestScope({update_options: {scope: 'specific', categories: ['funding', 'partnerships'],
    focus: 'battery storage'}, actor_names: ['A', 'B']}),
  'Specific Changes (Funding & Partnerships) · A, B · “battery storage”');
  assert.equal(actorResultLine({name: 'CPower', ok: true, counts: {new: 2, changed: 1},
    review_items: 1, spent_usd: 0.031}), 'CPower: 2 new · 1 changed · 1 to Review Results · $0.03');
  assert.equal(actorResultLine({name: 'X', ok: false, error: 'site could not be read'}),
    'X: not updated — site could not be read');
  assert.equal(actorResultLine({name: 'Y', ok: true, counts: {}, spent_usd: 0}),
    'Y: nothing new · $0.00');
});

test('hub fit and named organisations read back in plain words', async () => {
  const {hubSummary, relatedLine} = await import('../frontend/discovery.js');
  assert.equal(hubSummary({ok: true, memberships: [
    {name: 'Bay Hub', fit: 'fits', preserved: false},
    {name: 'Far Hub', fit: 'outside_radius', preserved: true}], proposals: []}),
  'In Bay Hub (fits), Far Hub (now outside its radius — kept, for a person to look at, GHUS membership)');
  assert.equal(hubSummary({ok: true, memberships: [], proposals: [
    {name: 'Delta Hub', distance_miles: 12.5}], note: null}),
  'Newly fits Delta Hub (12.5 mi) — proposed to Review Results when written, never assigned directly');
  assert.equal(hubSummary({ok: true, memberships: [], proposals: [],
    note: 'In no hub, and no hub of its sector contains it today. It stays eligible.'}),
  'In no hub, and no hub of its sector contains it today. It stays eligible.');
  assert.equal(relatedLine({name: 'NSF', relation: 'funder', status: 'on_map'}),
    'NSF · funder · In the directory — the link goes to Review Results when written');
  assert.equal(relatedLine({name: 'Acme', relation: 'member', status: 'not_on_map'}),
    'Acme · member · Not in the directory');
});

test('update runs are one list: name, actors, when, status and what each found', async () => {
  const {updateRunList, updateCountsLine} = await import('../frontend/discovery.js');
  const listing = {
    requests: [
      {subscription_id: 's1', title: 'Specific topic: 3 actors', status: 'expired', cadence: 'once',
        start_date: '2026-10-19', actor_names: ['Chevron', 'ExxonMobil', 'Shell'],
        update_options: {scope: 'topic'}, runs: [{collection_run_id: 'r1', started_at: '2026-10-19T19:48:45',
          status: 'succeeded', found_count: 13, review_item_count: 0}]},
      {subscription_id: 's2', title: 'Water every week', status: 'active', cadence: 'weekly',
        start_date: '2026-10-27', end_date: '2027-01-20', next_run: '2026-10-27',
        sector_codes: ['WATER'], update_options: {scope: 'general'}, runs: []},
      // A test fixture on an inactive sector: counted by the page, not listed.
      {subscription_id: 's3', title: 'General update: 3 actors', status: 'expired', test_sector: true, runs: []},
    ],
    one_time: [{run_id: 'u1', name: 'CPower Energy', started_at: '2026-10-19T14:14:31',
      status: 'succeeded', scope: 'general', topic_name: 'Energy Transition',
      counts: {changed: 4, confirmed: 2, missing: 2}}],
  };
  const rows = updateRunList(listing, [{code: 'WATER', name: 'Water'}]);
  assert.deepEqual(rows.map((row) => row.key), ['s2', 's1', 'u1']);
  const [weekly, topic, single] = rows;
  assert.equal(weekly.actors, 'Group: Water');
  assert.equal(weekly.result, 'Not run yet');
  assert.match(weekly.schedule, /^Every week until .* · next /);
  assert.equal(topic.actors, 'Chevron, ExxonMobil, Shell');
  assert.equal(topic.result, '13 new or updated · 0 to Review Results');
  assert.equal(topic.statusLabel, 'Finished');
  assert.equal(single.schedule, 'One-time update · Energy Transition');
  assert.equal(single.result, '4 updated · 2 confirmed · 2 not found');
  assert.equal(updateCountsLine({}), 'Nothing new');
});

test('a page read from another source says which', async () => {
  const {sourceLabel} = await import('../frontend/discovery.js');
  assert.equal(sourceLabel('official_parent'), "its parent organization's official site");
  assert.equal(sourceLabel('government'), 'a government site');
  assert.equal(sourceLabel('official'), '');
  assert.equal(sourceLabel(undefined), '');
});

test('run now writes, says what it wrote, and opens Review - no findings table', async () => {
  const {writtenLine, openInReview, OPEN_IN_REVIEW} = await import('../frontend/discovery.js');
  assert.equal(writtenLine({new: 4, not_found: 7}), '4 new · 7 not found');
  assert.equal(writtenLine({changed: 1, additional: 1, conflict: 1}), '1 updated · 1 more detail · 1 to review');
  assert.equal(writtenLine({}), 'nothing new');
  const seen = [];
  globalThis.window = new EventTarget();
  globalThis.CustomEvent = class extends Event { constructor(type, init) { super(type); this.detail = init?.detail; } };
  window.addEventListener(OPEN_IN_REVIEW, (event) => seen.push(event.detail));
  openInReview({actor_id: 'a1', name: 'CPower Energy'});
  assert.deepEqual(seen, [{actor_id: 'a1', name: 'CPower Energy'}]);
  const source = (await import('node:fs')).readFileSync(new URL('../frontend/discovery.js', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /<table class="actor-boxes">/);
  delete globalThis.window;
});

test('events and people have their own request forms; organizations keep theirs', async () => {
  const {DISCOVERY_KINDS, blankEntityForm, entityDraftPayload, entityDraftProblems,
    entitySummary, entityResultFacts} = await import('../frontend/discovery.js');
  assert.deepEqual(DISCOVERY_KINDS.map((k) => k.label), ['Organizations', 'Events', 'People']);

  // Nothing is assumed about the schedule: each field starts on its placeholder.
  const blank = blankEntityForm('2026-10-23', 'event');
  assert.deepEqual([blank.cadence, blank.startDate, blank.duration], ['', '', '']);
  const event = {...blank, title: 'Water reuse events',
    sector: 'ENERGY', focusTerms: ['water reuse'], areaKind: 'state', state: 'TX',
    dateFrom: '2027-03-01', dateTo: '2027-06-30', eventTypes: ['conference'],
    cadence: 'once', startDate: '2026-10-23'};
  assert.deepEqual(entityDraftPayload(event), {
    title: 'Water reuse events', sector_codes: ['ENERGY'], focus_terms: ['water reuse'],
    start_date: '2026-10-23', end_date: '2026-10-23', cadence: 'once',
    discovery_entity: 'event',
    discovery_options: {date_from: '2027-03-01', date_to: '2027-06-30', event_types: ['conference']},
    state_code: 'TX'});
  assert.deepEqual(entityDraftProblems(event, OPTIONS), {});
  assert.match(entitySummary({...entityDraftPayload(event)}, OPTIONS),
    /^Once, on 10\/23\/2026: find conferences on water reuse in Texas taking place from 03\/01\/2027 to 06\/30\/2027\.$/);
  assert.equal(entityDraftProblems({...event, dateTo: '2027-01-01'}, OPTIONS).dates,
    'The range ends before it starts.');

  // People: one question in the person's own words; the backend reads it into searches.
  const {PEOPLE_QUESTION, blankPeopleForm, peopleDraftPayload, peopleDraftProblems, statesForRegion} =
    await import('../frontend/discovery.js');
  assert.equal(PEOPLE_QUESTION, 'Who would you like to find?');
  const people = blankPeopleForm();
  assert.deepEqual([people.sector, people.region, people.state, people.cadence, people.startDate, people.duration],
    ['ANY', '', '', '', '', '']);
  assert.deepEqual(Object.keys(peopleDraftProblems(people)), ['brief', 'frequency', 'start']);
  const asked = {...people, brief: ' Battery storage professors at Texas universities. ', region: 'northeast',
    state: 'TX', cadence: 'monthly', startDate: '2026-10-23', duration: '3m'};
  assert.deepEqual(peopleDraftProblems(asked), {});
  assert.deepEqual(peopleDraftPayload(asked), {
    title: '', sector_codes: ['ANY'], focus_terms: [], start_date: '2026-10-23', end_date: '2027-01-23',
    cadence: 'monthly', discovery_entity: 'person',
    discovery_options: {brief: 'Battery storage professors at Texas universities.'}, state_code: 'TX'});
  assert.equal(peopleDraftPayload({...asked, state: ''}).region_code, 'northeast');
  // A region narrows the states offered.
  const regions = {states: [{code: 'TX', name: 'Texas'}, {code: 'NY', name: 'New York'}],
    regions: [{code: 'northeast', name: 'Northeast', states: ['NY']}]};
  assert.deepEqual(statesForRegion(regions, 'northeast').map((s) => s.code), ['NY']);
  assert.deepEqual(statesForRegion(regions, '').map((s) => s.code), ['TX', 'NY']);

  assert.deepEqual(entityResultFacts({start_date: '2027-03-10', event_type: 'Summit', city: 'Austin', state: 'TX',
    completeness: 'complete'}), [['Date', '03/10/2027'], ['Type', 'Summit'], ['Place', 'Austin, TX'],
    ['Completeness', 'Complete']]);
  // The organization form still sends exactly what it sent before.
  assert.equal('discovery_entity' in draftPayload(form()), false);
  // One submission button everywhere: Create Request, which runs at once when it starts today.
  const page = fs.readFileSync(new URL('../frontend/discovery.js', import.meta.url), 'utf8');
  assert.doesNotMatch(page, /Save request/);
  assert.equal((page.match(/"Create Request"/g) || []).length, 4);
  assert.match(page, /const started = payload\.start_date === today;/);
  for (const placeholder of ['Select frequency\u2026', 'Select a date\u2026', 'Select duration\u2026']) {
    assert.ok(page.includes(placeholder), placeholder);
  }
  // End date: Save appears only once it changes; finished requests are read-only.
  assert.match(page, /\$\{changed && html`<button class="btn"/);
  assert.match(page, /const editable = \(request\.status === "active" \|\| request\.status === "paused"\) && request\.cadence !== "once";/);
});

test('a request that ran, or whose period is over, offers Run again; a running one says Running', async () => {
  const {runButtonLabel, requestStatus, STATUS_LABELS} = await import('../frontend/discovery.js');
  assert.equal(runButtonLabel({status: 'active', next_run: '2026-11-01', runs: []}), 'Run now');
  assert.equal(runButtonLabel({status: 'active', next_run: '2026-11-01',
    runs: [{status: 'succeeded'}]}), 'Run again');
  const over = {status: 'active', next_run: null, skip_reason: 'expired', runs: []};
  assert.equal(runButtonLabel(over), 'Run again');
  // Nothing more is scheduled, so it does not say "Scheduled".
  assert.equal(STATUS_LABELS[requestStatus(over)], 'Period over');
  assert.equal(STATUS_LABELS[requestStatus({...over, runs: [{status: 'running'}]})], 'Running');
  const source = fs.readFileSync(new URL('../frontend/discovery.js', import.meta.url), 'utf8');
  assert.match(source, /\["us", "All United States"\]/);
  assert.doesNotMatch(source, /Whole United States|How detailed should the update be/);
});

test('every date on the platform is MM/DD/YYYY', async () => {
  const {usDate, usDateTime} = await import('../frontend/dates.js');
  assert.equal(usDate('2026-10-26'), '10/26/2026');
  assert.equal(usDate(new Date(2027, 0, 5)), '01/05/2027');
  assert.match(usDateTime('2026-10-26T17:38:00'), /^10\/26\/2026, 5:38 PM$/);
  assert.equal(usDateTime('2026-10-26'), '10/26/2026');
  assert.equal(usDate(''), '');
  assert.equal(usDate('not a date'), 'not a date');
});

test('an update says when it proposed a Category Type, and never sets one', async () => {
  const {typeProposalLine} = await import('../frontend/discovery.js');
  assert.equal(typeProposalLine(null), '');
  assert.match(typeProposalLine({category_type: 'professional_network', type_label: 'Professional Network'}),
    /point to Professional Network — proposed to Review Results when written, never set directly/);
  assert.match(typeProposalLine({category_type: 'not_applicable', type_label: 'Not Applicable'}),
    /point to Not Applicable/);
});

test('Organizations Update: one list, checked by default, never twice, with a header checkbox', async () => {
  const {addOrganization, selectionState, selectionLine, lastCheckedLabel, directoryStatus} =
    await import('../frontend/discovery.js');
  const bio = {actor_id: 'a', name: 'BioSTL', status: 'verified', last_checked: '2026-10-28'};
  const ceg = {actor_id: 'b', name: 'Clean Energy Group', status: 'parked', last_checked: null};
  let list = addOrganization(addOrganization([], bio), ceg);
  assert.equal(addOrganization(list, bio), list);                // no duplicate
  assert.deepEqual(list.map((r) => r.checked), [true, true]);
  assert.equal(selectionState(list), 'all');
  assert.equal(selectionLine(list), '2 organizations selected.');
  list = list.map((r) => (r.actor.actor_id === 'b' ? {...r, checked: false} : r));
  assert.equal(selectionState(list), 'some');                   // partially selected
  assert.equal(selectionLine(list), '1 organization selected.');
  assert.equal(lastCheckedLabel('2026-10-28'), '28 October 2026');
  assert.equal(lastCheckedLabel(null), 'Not recorded');
  assert.deepEqual([directoryStatus(bio), directoryStatus(ceg)], ['Verified', 'Parked']);
});

test('Organizations Update sends only the checked organizations, one option and one schedule', async () => {
  const {orgUpdatePayload, orgUpdateProblems, frequencyOptions, SPECIFIC_PLACEHOLDER} =
    await import('../frontend/discovery.js');
  const list = [{actor: {actor_id: 'a'}, checked: true}, {actor: {actor_id: 'b'}, checked: false}];
  const form = {cadence: 'monthly', startDate: '2026-11-02', duration: '3m'};
  assert.deepEqual(frequencyOptions('update'), ['once', 'weekly', 'monthly']);
  assert.deepEqual(orgUpdatePayload({list, kind: 'general', interests: ['funding'], form, requester: 'me@um6p.ma'}), {
    actor_ids: ['a'], max_actors_per_run: 1, depth: 'light', cadence: 'monthly',
    start_date: '2026-11-02', end_date: '2027-02-02', scope: 'general',
    categories: ['funding', 'partnerships'], requested_by: 'me@um6p.ma'});
  const specific = orgUpdatePayload({list, kind: 'specific', focus: ' Battery storage pilots since 2025. ',
    form: {cadence: 'once', startDate: '2026-11-02', duration: ''}});
  assert.equal(specific.scope, 'topic');
  assert.equal(specific.focus, 'Battery storage pilots since 2025.');
  assert.equal(specific.end_date, '2026-11-02');
  // Create Request waits for a checked organization, the description and the schedule.
  const blank = {cadence: '', startDate: '', duration: ''};
  assert.deepEqual(Object.keys(orgUpdateProblems({list: [], kind: 'specific', focus: '', form: blank})),
    ['organizations', 'focus', 'frequency', 'start']);
  assert.deepEqual(orgUpdateProblems({list, kind: 'general', focus: '', form}, '2026-10-30'), {});
  assert.ok(orgUpdateProblems({list, kind: 'general', form: {...form, duration: ''}}).duration);
  assert.match(SPECIFIC_PLACEHOLDER, /capabilities in another sector/);
});

test('requests stay with whoever made them; older ones without a requester stay shared', async () => {
  const {visibleRequests} = await import('../frontend/discovery.js');
  const rows = [{id: 1, requested_by: 'me@um6p.ma'}, {id: 2, requested_by: 'other@um6p.ma'},
    {id: 3, requested_by: null}, {id: 4, requested_by: 'actor_updates_page'}];
  assert.deepEqual(visibleRequests(rows, 'ME@um6p.ma').map((r) => r.id), [1, 3, 4]);
  assert.deepEqual(visibleRequests(rows, '').map((r) => r.id), [3, 4]);
});

test('the Monitor page leads with New Request, Organizations Update, Requests and keeps no run list', async () => {
  const page = fs.readFileSync(new URL('../frontend/discovery.js', import.meta.url), 'utf8');
  const order = ['setView("new")}>New Request<', 'setView("actors")}>Organizations Update<',
    'setView("requests")}>Requests ('].map((s) => page.indexOf(s));
  assert.ok(order.every((i) => i > 0) && order[0] < order[1] && order[1] < order[2]);
  const code = page.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  for (const gone of ['One actor', 'Several actors', 'Save schedule', 'Update runs']) {
    assert.ok(!code.includes(gone), gone);
  }
  assert.ok(page.includes('Existing directory information remains unchanged until you verify the proposed updates.'));
  assert.ok(page.includes('You’ll receive an email notification when your results are ready in Review Results.'));
});
