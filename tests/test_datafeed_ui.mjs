import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {
  ATTEST_SOURCE,
  RECORD_TYPES,
  approveLine,
  canSend,
  boxesLine,
  doneLine,
  historyMeta,
  leftOutLine,
  STATUS,
  confirmLabel,
  costLine,
  defaultImportName,
  filterCount,
  filterRows,
  historyLine,
  infoBoxes,
  manualRecords,
  matchLine,
  missingRequired,
  previewCandidate,
  rowSubtitle,
  stageable,
  summaryTiles,
  visibleFields,
} from '../frontend/datafeed.js';
import {lightFactRows, lightPullBoxes} from '../frontend/review.js';

const VOCAB = {
  actor_categories: [{code: 'company', label: 'Company / Corporate Actor'},
    {code: 'university_academic', label: 'University / Academic Institution'}],
  category_types: {company: [{code: 'small_mid_size', label: 'SME'}],
    university_academic: [{code: 'university_system', label: 'Main Institution'}]},
  sectors: [{code: 'WATER', label: 'Water'}, {code: 'AGRI', label: 'Agriculture'}],
  topics: [{code: 'WATER', label: 'Water', topic_id: 't1'}],
  regions: [{code: 'midwest_great_lakes', label: 'Midwest / Great Lakes', states: ['KS']}],
  event_types: [{code: 'summit', label: 'Summit'}],
  event_formats: [{code: 'hybrid', label: 'Hybrid'}],
  recurrence: [{code: 'annual', label: 'Annual'}],
  parent_links: [{code: 'unit_of', label: 'Unit of'}],
};
const FIELDS = [
  {key: 'name', header: 'Official name', required: true, categories: []},
  {key: 'actor_category', header: 'Actor Category', required: true, categories: []},
  {key: 'website', header: 'Website', required: false, categories: []},
  {key: 'ownership_and_size', header: 'Company: ownership and size', required: false,
    categories: ['company']},
  {key: 'geographic_focus', header: 'Investor or foundation: geographic focus', required: false,
    categories: ['investor', 'foundation_nonprofit']},
];
const ACTOR_ROW = {
  row_number: 2, status: 'new', errors: [], warnings: [], missing: [],
  match: {kind: 'new'}, values: {'Official name *': 'Prairie Water Lab'},
  payload: {name: 'Prairie Water Lab', actor_category: 'company', category_type: 'small_mid_size',
    city: 'Wichita', state_code: 'KS', country: 'United States', sector_codes: ['WATER', 'AGRI'],
    topic_code: 'WATER', website: 'https://pwl.example', source_url: 'https://pwl.example/about',
    light_pull_values: {funding_signal: 'USDA SBIR Phase I',
      recent_activity: {description: 'Pilot with K-State', date: '2026-05-14'},
      ownership_and_size: 'Private, 25 employees'}},
};

test('three record types, chosen from a dropdown', () => {
  assert.deepEqual(RECORD_TYPES.map(t => t.label), ['Actors / Organizations', 'People', 'Events']);
  const source = fs.readFileSync(new URL('../frontend/datafeed.js', import.meta.url), 'utf8');
  assert.match(source, /<select id="df-record-type"/);
  assert.match(source, /<select id="df-method"/);
  assert.doesNotMatch(source, /df-steps/);
  assert.deepEqual(Object.keys(STATUS), ['invalid', 'new', 'existing', 'possible', 'waiting']);
});

test('summary tiles show every count the preview needs, and flag problems', () => {
  const tiles = summaryTiles({total: 8, valid: 5, needs_correction: 3, new: 2, existing_matches: 1,
    possible_duplicates: 1, already_waiting: 1, missing_optional: 4});
  assert.deepEqual(tiles.map(t => [t.label, t.value]), [
    ['Records', 8], ['Valid', 5], ['Need correction', 3], ['New', 2], ['Existing matches', 1],
    ['Possible duplicates', 1], ['Already in Review Results', 1], ['Missing optional info', 4]]);
  assert.equal(tiles.find(t => t.key === 'needs_correction').tone, 'error');
  assert.equal(summaryTiles({}).find(t => t.key === 'needs_correction').tone, '');
});

test('records already waiting in Review are not counted as sent', () => {
  const counts = {valid: 5, already_waiting: 2};
  assert.equal(stageable(counts), 3);
  assert.equal(confirmLabel(counts), 'Send 3 records to Review Results');
  assert.equal(confirmLabel({valid: 1}), 'Send 1 record to Review Results');
});

test('filters split the preview by status', () => {
  const rows = [{status: 'new'}, {status: 'invalid'}, {status: 'invalid'}, {status: 'possible'}];
  assert.equal(filterRows(rows, 'all').length, 4);
  assert.equal(filterCount(rows, 'invalid'), 2);
  assert.equal(filterCount(rows, 'waiting'), 0);
});

test('the import name defaults to the file name or a dated manual entry', () => {
  assert.equal(defaultImportName({file: {name: 'Kansas_water-actors.xlsx'}}), 'Kansas water actors');
  assert.equal(defaultImportName({file: null}, new Date('2026-10-26T12:00:00Z')),
    'Manual entry 10/26/2026');
});

test('a match is described with its strength and reason; a new record says nothing', () => {
  assert.equal(matchLine({kind: 'new'}), '');
  assert.equal(matchLine({kind: 'existing', entity_id: 'a', name: 'ADM', score: 1,
    reason: 'same website (adm.com)'}), 'Same as “ADM” (100%) - same website (adm.com)');
  assert.match(matchLine({kind: 'possible', entity_id: 'a', name: 'ADM', score: 0.917}),
    /^Close to “ADM” \(92%\)/);
});

test('the manual form shows a category-specific box only for its categories', () => {
  assert.deepEqual(visibleFields(FIELDS, '').map(f => f.key), ['name', 'actor_category', 'website']);
  assert.ok(visibleFields(FIELDS, 'company').some(f => f.key === 'ownership_and_size'));
  assert.ok(visibleFields(FIELDS, 'foundation_nonprofit').some(f => f.key === 'geographic_focus'));
  assert.ok(!visibleFields(FIELDS, 'company').some(f => f.key === 'geographic_focus'));
});

test('manual records send only known, filled fields, as text', () => {
  assert.deepEqual(missingRequired(FIELDS, {name: ' '}), ['Official name', 'Actor Category']);
  assert.deepEqual(manualRecords([{name: 'X', website: '', bogus: 'y', sectors: ['Water', 'AGRI']}],
    [...FIELDS, {key: 'sectors'}]), [{name: 'X', sectors: 'Water; AGRI'}]);
});

test('the preview row uses labels, never codes', () => {
  assert.equal(rowSubtitle(ACTOR_ROW, 'actor', VOCAB), 'Company / Corporate Actor · SME · Wichita, KS');
  const event = {payload: {event_type: 'summit', start_date: '2027-04-02', end_date: '2027-04-03',
    location: 'Wichita, KS'}};
  assert.equal(rowSubtitle(event, 'event', VOCAB), 'Summit · 04/02/2027 - 04/03/2027 · Wichita, KS');
  assert.equal(rowSubtitle({payload: {role: 'Professor', affiliation: 'Univ'}}, 'person', VOCAB),
    'Professor · Univ');
});

test('information boxes group a record the way Review does, with a derived region', () => {
  const boxes = infoBoxes(ACTOR_ROW, 'actor', VOCAB, [{key: 'category_type', header: 'Category Type'}]);
  assert.deepEqual(boxes.map(b => b.title), ['Identity', 'Classification', 'Location',
    'Sector and topic', 'Parent', 'Source']);
  const location = boxes.find(b => b.title === 'Location').items;
  assert.equal(location.find(i => i.label === 'region').value, 'Midwest / Great Lakes');
  assert.equal(boxes.find(b => b.title === 'Sector and topic').items[0].value, 'Water, Agriculture');
  const pending = infoBoxes({payload: {actor_category: 'company'}}, 'actor', VOCAB, []);
  assert.equal(pending[1].items[1].value, 'Pending Classification');
  const noHost = infoBoxes({payload: {name: 'E'}}, 'event', VOCAB, []);
  assert.equal(noHost[0].items[2].value, 'No confirmed host');
});

test('supplied Light Pull values render through Review\'s own boxes', () => {
  const boxes = lightPullBoxes(previewCandidate(ACTOR_ROW), 'company');
  const funding = boxes.common.find(r => r.key === 'funding_signal');
  assert.equal(funding.value, 'USDA SBIR Phase I');
  assert.equal(funding.origin, 'uploaded_document');
  assert.equal(boxes.specific.find(r => r.key === 'ownership_and_size').value,
    'Private, 25 employees');
});

test('the AI completion states its cost before anything is spent', () => {
  assert.equal(costLine({organisations: []}),
    'Every record already has all its boxes; nothing to read.');
  assert.equal(costLine({organisations: [{}, {}, {}], estimated_usd: 0.13,
    per_organisation_usd: 0.0423, basis: 'average of 17 earlier reads'}),
  '3 organizations to read · about $0.13 ($0.042 each: average of 17 earlier reads)');
});

test('import history says what Review decided', () => {
  assert.equal(historyLine({staged: 5, already_awaiting_review: 1, rows_invalid: 2,
    counts: {pending: 2, approved_new: 1, matched_existing: 1, rejected: 1, deferred: 0}}),
  '5 staged · 2 awaiting Review · 1 approved and added · 1 matched to existing · 1 rejected · '
  + '1 already in Review Results · 2 failed validation');
});

test('the page never writes records itself and confirms explicitly', () => {
  const source = fs.readFileSync(new URL('../frontend/datafeed.js', import.meta.url), 'utf8');
  // Only its own /api/datafeed routes; confirming is a separate, explicit request.
  for (const call of source.matchAll(/api\(`?"?(\/api\/[^"`$]+)/g)) {
    assert.match(call[1], /^\/api\/datafeed\//);
  }
  assert.match(source, /\/confirm`, \{\s*method: "POST"/);
  assert.match(source, /accept_left_out: accept/);
  assert.match(source, /confirmed: agree/);
});

test('the page is in the navigation, between Discovery and Review', () => {
  const index = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  // The COMPASS navigation (2026-10-29): [id, label], an icon per id.
  assert.match(index, /\["discovery","Monitor and Update"\],\["datafeed","Data Feed"\],\["review","Review Results"\]/);
  assert.match(index, /datafeed:svg\(/);
  assert.match(index, /import \{createDataFeedPage\} from "\.\/datafeed\.js\?v=\d+[a-z]";/);
  assert.match(index, /<link rel="stylesheet" href="\/datafeed\.css\?v=\d+[a-z]"\/>/);
  // datafeed.js imports review.js under the same version as the page, so it loads once.
  const version = index.match(/review\.js\?v=(\w+)/)[1];
  const source = fs.readFileSync(new URL('../frontend/datafeed.js', import.meta.url), 'utf8');
  assert.match(source, new RegExp(`review\\.js\\?v=${version}`));
});

test('sentences agree in number and keep their spaces', () => {
  assert.equal(leftOutLine(1), '1 record needs correction and will not be sent. I understand; send the others.');
  assert.equal(leftOutLine(3).slice(0, 25), '3 records need correction');
  assert.equal(doneLine({staged: 1, import_name: 'K', left_out: 1}),
    '1 record now waits in Review Results as “Data Feed import · K”. 1 needed correction and was left out.');
  assert.equal(doneLine({staged: 2, import_name: 'K', already_awaiting_review: 2, left_out: 3}),
    '2 records now wait in Review Results as “Data Feed import · K”. 2 were already waiting in Review Results and '
    + 'not sent again. 3 needed correction and were left out.');
  assert.equal(doneLine({status: 'already_imported'}),
    'This exact file was imported before; nothing was sent twice.');
  const meta = historyMeta({record_type: 'event', method: 'upload', file_name: 'ev.csv',
    uploaded_at: '2026-10-26T12:00:00Z', uploaded_by: 'Ana Ruiz'});
  assert.match(meta, /^Events · ev\.csv · 10\/2[67]\/2026, \d{1,2}:\d{2} [AP]M/);       // date and time
  assert.match(meta, /Uploaded by Ana Ruiz \(as typed; no sign-in yet\) · Sent to Review Results$/);
  assert.match(historyMeta({record_type: 'actor', admission: 'verified'}),
    /Uploaded by Not recorded · Imported as Verified$/);
  assert.equal(boxesLine({name: 'ADM', boxes: ['a']}), 'ADM: 1 empty box');
  assert.equal(approveLine('0.12'), 'I approve spending up to $0.12 on this read.');
});

test('in Review, the empty boxes of an imported record were never looked for', () => {
  const facts = [{fact_key: 'funding_signal', fact_type: 'light_pull', layer: 1,
    collection_state: 'found', value: 'USDA grant'}];
  const imported = {reviewed_payload: {actor_category: 'company'},
    agent_metadata: {facts, data_feed: {import_name: 'K'}, light_pull_read: {}}};
  const row = key => lightFactRows(imported).find(r => r.key === key);
  assert.equal(row('funding_signal').value, 'USDA grant');
  assert.equal(row('recent_activity').state, 'Not Yet Collected');
  // Once the Light Pull has read its pages, an empty box is Not Found.
  imported.agent_metadata.light_pull_read = {read_at: '2026-10-26T12:00:00Z'};
  assert.equal(row('recent_activity').state, 'Not Found');
  // A discovery candidate keeps its own rule.
  assert.equal(lightFactRows({reviewed_payload: {actor_category: 'company'},
    agent_metadata: {facts}}).find(r => r.key === 'recent_activity').state, 'Not Found');
});

test('nothing is sent before the uploader is named and confirms the source', () => {
  const preview = {can_confirm: true, counts: {needs_correction: 0}};
  const base = {preview, name: 'Kansas', uploader: 'Ana Ruiz', attestSource: true,
    admission: 'review', attestAuthorized: false, accept: false};
  assert.ok(canSend(base));
  assert.ok(!canSend({...base, uploader: ' '}));
  assert.ok(!canSend({...base, attestSource: false}));
  assert.ok(!canSend({...base, admission: 'verified'}));              // needs the second attestation
  assert.ok(canSend({...base, admission: 'verified', attestAuthorized: true}));
  assert.ok(!canSend({...base, preview: {can_confirm: true, counts: {needs_correction: 2}}}));
  assert.match(ATTEST_SOURCE, /Compass import or a Notion CRM export/);
});

test('a Verified import says what was added and what waits in Review', () => {
  assert.equal(doneLine({admission: 'verified', verified: 2, uploaded_by: 'Ana Ruiz',
    held_for_review: [{row_number: 4, reason: 'x'}], left_out: 1}),
  "2 organizations were added to the directory as Verified, on Ana Ruiz's attestation. "
  + '1 record waits in Review Results. 1 needed correction and was left out.');
});
