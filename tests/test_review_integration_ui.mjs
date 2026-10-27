import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createReviewPage} from '../frontend/review.js';

// Exercise the merged component, not just its standalone validators. Effects
// stay disabled: these renders must never fetch a live queue or write decisions.
function renderReview(kind, pipeline = {}) {
  const candidate = {candidate_id: 'candidate', display_name: 'Example Lab',
    entity_type: 'actor', status: 'pending_review', source_run_id: 'run',
    reviewed_payload: {name: 'Example Lab', actor_category: 'company'},
    original_payload: {}, editable_fields: [], top_matches: [],
    agent_metadata: {source_table: 'review_item', review_kind: kind, pipeline}};
  const data = {candidates: [candidate], counts: {}, source_maps: [], run_groups: [],
    sync_warnings: [], last_sync: [], admission_configured: false};
  let slot = 0;
  // useState slots in call order: 0 filters, 1 the open run, 2 data,
  // 3 selected id, 4 selected record, 5 draft.
  const state = new Map([[2, data], [3, candidate.candidate_id], [4, candidate],
    [5, candidate.reviewed_payload]]);
  const flatten = value => Array.isArray(value) ? value.map(flatten).join('')
    : value == null || value === false ? '' : typeof value === 'function' ? '[handler]' : String(value);
  const Review = createReviewPage({
    html: (strings, ...values) => strings.reduce((out, text, i) => out + text + flatten(values[i]), ''),
    useState: initial => { const i = slot++; return [state.has(i) ? state.get(i) : initial, () => {}]; },
    useEffect() {}, useRef: initial => ({current: initial}),
  });
  return Review();
}

test('a location review renders its own decision form inside the redesigned workspace', () => {
  const output = renderReview('geocode_failed');
  assert.match(output, /review-workspace/);
  assert.match(output, /Location review/);
  assert.match(output, /Keep unlocated/);
  assert.doesNotMatch(output, /<footer class="review-footer"/);
});

test('legacy and newly proposed relationships render the correct separate actions', () => {
  const legacy = renderReview('relationship_review', {legacy_relationship_type: 'parent_of'});
  assert.match(legacy, /Legacy relationship/);
  assert.match(legacy, /Approve with source/);
  assert.doesNotMatch(legacy, /<footer class="review-footer"/);
  const modern = renderReview('relationship_review', {proposed_relationship_type: 'funded_by',
    source_url: 'https://example.org/source'});
  assert.doesNotMatch(modern, /Legacy relationship/);
  assert.match(modern, /<footer class="review-footer"/);
  assert.match(modern, /Confirm the link/);
});

test('category confirmations coexist with the normal actor decision footer', () => {
  const output = renderReview('category_doubt');
  assert.match(output, /Category reviews/);
  assert.match(output, /Example Lab/);
  assert.match(output, /<footer class="review-footer"/);
});

test('keep both is offered only for location fact conflicts and pending updates', () => {
  for (const kind of ['fact_conflict', 'pending_update']) {
    assert.match(renderReview(kind, {field_key: 'location'}), /Keep both locations/);
    assert.doesNotMatch(renderReview(kind, {field_key: 'funding_signal'}), /Keep both locations/);
  }
  assert.doesNotMatch(renderReview('category_doubt', {field_key: 'location'}), /Keep both locations/);
});
