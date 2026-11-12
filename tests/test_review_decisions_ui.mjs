// Review decisions after the GHUS feedback of 11 Nov 2026 (12 Nov 2026).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {blockedReason, canSubmitReview, verifyKind} from '../frontend/review.js';

const component = fs.readFileSync(new URL('../frontend/review.js', import.meta.url), 'utf8');

test('Verify adds a record as new unless it is marked the same as a duplicate', () => {
  assert.equal(verifyKind('new'), 'new');
  assert.equal(verifyKind('reject'), 'new');
  assert.equal(verifyKind('defer'), 'new');
  assert.equal(verifyKind('same_existing'), 'same_existing');
  assert.equal(verifyKind('keep_both'), 'keep_both');
  // The platform's duplicate list carries the one-click choice.
  assert.match(component, />Same record</);
});

test('the Decision box no longer repeats Reject and Park', () => {
  assert.doesNotMatch(component, /<span>Decision<\/span>/);
  assert.doesNotMatch(component, /FIELDS\.rejectionReason\}<\/span>/);
  assert.match(component, /onClick=\$\{\(\) => decide\("reject"\)\}/);
  assert.match(component, /onClick=\$\{\(\) => decide\("defer"\)\}/);
});

test('rejecting and parking never wait on an unfinished edit', () => {
  const candidate = {status: 'pending_review'};
  const draftErrors = {next_date: 'Use MM/DD/YYYY.'};
  assert.equal(canSubmitReview({candidate, reviewer: 'R', decisionKind: 'new', admissionConfigured: true, draftErrors}), false);
  assert.match(component, /\["reject", "defer"\]\.includes\(decisionKind\)\s*\? \{\} : validateReviewDraft/);
});

test('when Save Edits and Verify wait, the page says why in words', () => {
  assert.equal(blockedReason({}), '');
  assert.match(blockedReason({next_date: 'Use MM/DD/YYYY.'}), /: Use MM\/DD\/YYYY\.$/);
  assert.match(component, /To save or verify, fix: /);
});

test('GHUS Notes typed in Review are kept as a draft until the decision', () => {
  assert.match(component, /keepNotesDraft\(selected\.candidate_id, e\.target\.value\)/);
  assert.match(component, /notesDraft\(candidate\.candidate_id\) \?\?/);
});

// ------------------------------------------- every box editable (12 Nov 2026)
import {changedOnly, profilePrefill, EDIT_AS} from '../frontend/review.js';

test('every box of an event card is editable, starting with what the card shows', () => {
  const candidate = {
    entity_type: 'event',
    editable_fields: ['name', 'audience', 'sector', 'event_format', 'organizer', 'um6p_ocp_involvement'],
    original_payload: {audience: 'Founders and investors', event_format: 'in person',
      um6p_ocp_status: "not found in what's been read"},
    agent_metadata: {sector_codes: []},
  };
  const filled = profilePrefill(candidate, {name: 'Beyond Africa'});
  assert.equal(filled.audience, 'Founders and investors');
  assert.equal(filled.event_format, 'In person');           // capitalised as shown
  assert.equal(filled.um6p_ocp_involvement, undefined);      // never the map's "not found" wording
  assert.equal(EDIT_AS.person.work_evidence, 'relevant_work');
});

test('an untouched box is not sent as a reviewer edit', () => {
  const prefill = {audience: 'Founders and investors'};
  assert.deepEqual(changedOnly({name: 'X', audience: 'Founders and investors'}, prefill), {name: 'X'});
  assert.deepEqual(changedOnly({audience: 'Students'}, prefill), {audience: 'Students'});
});
