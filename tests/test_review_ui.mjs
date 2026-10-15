import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {
  AUDIT_ONLY_FIELDS,
  DERIVED_FIELDS,
  actorReviewSummary,
  canSubmitReview,
  decisionOptions,
  deepPullFacts,
  diffFields,
  editableReviewPayload,
  factHistoryRows,
  filterReviewCandidates,
  formatFactValue,
  groupQueue,
  headerBadges,
  hubDropdownOptions,
  lightPullBoxes,
  isMigratedBaseline,
  lightFactRows,
  lightPullFacts,
  otherRelationships,
  REVIEW_REASON_LABELS,
  confidenceLabel,
  matchStrengthLabel,
  parentDisplay,
  pendingEdits,
  reviewFieldLabel,
  reviewReasonLabel,
  reviewRunLabel,
  reviewStatusLabel,
  runChip,
  SUBSCRIPTION_STATUS_LABELS,
  hubProposalPlace,
  requestedViaLabel,
  whyMatchedFact,
  thresholdLabel,
  subscriptionPeriodLabel,
  subscriptionScopeLabel,
  subscriptionStatusLabel,
  validateReviewDraft,
} from '../frontend/review.js';
import {
  CATEGORIES,
  COMMON_LIGHT_ROWS,
  COUNTRIES,
  MISSING,
  NOT_APPLICABLE,
  PARENT_LINK_TYPES,
  RETIRED_CATCH_ALL,
  isParentLink,
  isValidPair,
  linkTypeLabel,
  normalizeCountry,
  regionForState,
  sectorOptions,
  typeOptions,
} from '../frontend/taxonomy.js';
import {
  ACRONYMS,
  BADGES,
  REQUESTED_VIA,
  SECTIONS,
  SENTENCES,
  TITLE_CASE_GROUPS,
  TITLE_CASE_LOWER_WORDS,
} from '../frontend/labels.js';

const component = fs.readFileSync(new URL('../frontend/review.js', import.meta.url), 'utf8');

// ----------------------------------------------------------------- taxonomy

test('the catalog is the Intern Guide: 12 categories, 69 types, Not Applicable last', () => {
  assert.equal(CATEGORIES.length, 12);
  assert.equal(CATEGORIES.reduce((total, [, , types]) => total + types.length, 0), 69);
  for (const [code, label, types] of CATEGORIES) {
    assert.ok(label.length > 0, `${code} has no label`);
    assert.equal(types.at(-1)[0], NOT_APPLICABLE, `${code} must list Not Applicable last`);
    assert.equal(types.filter(([value]) => value === NOT_APPLICABLE).length, 1);
    // The Phase 5 catch-all is retired and must never be selectable.
    assert.equal(types.filter(([value]) => value === RETIRED_CATCH_ALL).length, 0);
    assert.equal(new Set(types.map(([value]) => value)).size, types.length);
  }
});

test('the Category Type dropdown depends on the chosen category, and cross pairs are invalid', () => {
  assert.deepEqual(typeOptions('research_center').map(o => o.value), [
    'independent_institute', 'nonprofit_operated', 'corporate_operated',
    'government_affiliated', 'not_applicable',
  ]);
  assert.deepEqual(typeOptions('innovation_platform').map(o => o.label), [
    'Incubator', 'Accelerator', 'Venture Studio', 'Not Applicable',
  ]);
  assert.deepEqual(typeOptions('nonexistent_category'), []);
  assert.equal(isValidPair('startup', 'university_spinout'), true);
  assert.equal(isValidPair('company', 'medical_school'), false);
  assert.equal(isValidPair('startup', RETIRED_CATCH_ALL), false);
});

test('changing the Actor Category clears an incompatible type after a confirmation', () => {
  // The control asks before it clears, because carrying a type across
  // categories would record a relationship that is not true.
  assert.match(component, /function editCategory\(value\)/);
  assert.match(component, /isValidPair\(value, currentType\)/);
  assert.match(component, /window\.confirm\(SENTENCES\.categoryChangeWarning\)/);
  assert.match(component, /category_type: ""/);
});

test('region is derived from the state, including DC and Washington State', () => {
  assert.equal(regionForState('DC'), 'Mid-Atlantic');
  assert.equal(regionForState('WA'), 'West Coast / Pacific');
  assert.equal(regionForState('Washington'), 'West Coast / Pacific');
  assert.equal(regionForState('CA', 'United States'), 'West Coast / Pacific');
  assert.equal(regionForState('TX'), 'South Central / Texas Gulf');
  // A missing state is unknown, not Not Applicable.
  assert.equal(regionForState(''), MISSING.notProvided);
  assert.equal(regionForState('Casablanca', 'Morocco'), 'Not Applicable (Non-US)');
});

test('the region control is read-only and never a hand-entered field', () => {
  assert.ok(DERIVED_FIELDS.has('region'));
  assert.match(component, /value=\$\{summary\.region\} readonly disabled aria-readonly="true"/);
});

// --------------------------------------------------------------- classification

test('a legacy NULL type reads Pending Classification, never Not Applicable', () => {
  const summary = actorReviewSummary({actor_category: 'company', category_type: null});
  assert.equal(summary.category_type, null);
  assert.equal(summary.category_type_label, MISSING.pending);
  assert.equal(summary.pending_classification, true);
  assert.notEqual(summary.category_type_label, MISSING.notApplicable);
});

test('actor summary labels the pair and reports missing location as Not Provided', () => {
  const summary = actorReviewSummary({
    actor_category: 'research_center', category_type: 'nonprofit_operated',
    location_city: 'Boston', state: 'MA', country: 'United States',
  });
  assert.equal(summary.actor_category_label, 'Research Center / Institute / Laboratory');
  assert.equal(summary.category_type_label, 'Nonprofit-Operated');
  assert.equal(summary.region, 'Northeast');
  assert.equal(summary.city, 'Boston');

  const sparse = actorReviewSummary({actor_category: 'company', actor_type: 'research institute'});
  assert.equal(sparse.city, MISSING.notProvided);
  assert.equal(sparse.state, MISSING.notProvided);
  assert.equal(sparse.country, MISSING.notProvided);
  // The legacy field is carried for the Audit panel only.
  assert.equal(sparse.legacy_actor_type, 'research institute');
});

test('a retired type still displays on the record that holds it', () => {
  const summary = actorReviewSummary({actor_category: 'company', category_type: RETIRED_CATCH_ALL});
  assert.equal(summary.category_type_retired, true);
  assert.equal(summary.category_type_label, 'Other (Retired)');
});

test('Not Applicable requires a one-line note, and a cross-category pair is refused', () => {
  const candidate = {entity_type: 'actor', editable_fields: ['name', 'actor_category', 'category_type', 'category_note']};
  assert.deepEqual(
    validateReviewDraft(candidate, {name: 'X', actor_category: 'company', category_type: NOT_APPLICABLE}),
    {category_note: 'Required when the type is Not Applicable.'},
  );
  assert.deepEqual(
    validateReviewDraft(candidate, {
      name: 'X', actor_category: 'company', category_type: NOT_APPLICABLE,
      category_note: 'Nothing listed fits.',
    }),
    {},
  );
  assert.deepEqual(
    validateReviewDraft(candidate, {name: 'X', actor_category: 'company', category_type: 'medical_school'}),
    {category_type: 'This type belongs to a different Actor Category.'},
  );
  assert.deepEqual(
    validateReviewDraft(candidate, {name: 'X', category_type: 'medical_school'}),
    {actor_category: 'Choose the Actor Category first.'},
  );
});

// ----------------------------------------------------------------- parent

test('no parent reads Not Available with an explanation, not a warning', () => {
  const display = parentDisplay({agent_metadata: {relationships: []}});
  assert.equal(display.hasParent, false);
  assert.equal(display.missing, MISSING.notAvailable);
  assert.match(display.tooltip, /Standalone actors are complete records/);
});

test('only Unit of and Operated by count as parenthood', () => {
  assert.deepEqual(PARENT_LINK_TYPES.map(o => o.value), ['unit_of', 'operated_by']);
  const candidate = {agent_metadata: {relationships: [
    {direction: 'outgoing', relationship_type: 'portfolio_of', counterpart_name: 'An Accelerator', source_url: 'https://example.org/a'},
    {direction: 'outgoing', relationship_type: 'unit_of', counterpart_name: 'Example University', source_url: 'https://example.org/u'},
    {direction: 'incoming', relationship_type: 'member_of', counterpart_name: 'A Consortium'},
  ]}};
  const parent = parentDisplay(candidate);
  assert.equal(parent.hasParent, true);
  assert.equal(parent.name, 'Example University');
  assert.equal(parent.linkType, 'Unit of');

  // Portfolio of and Member of are relationships, never parenthood.
  const others = otherRelationships(candidate);
  assert.deepEqual(others.map(edge => edge.label), ['Portfolio of', 'Member of']);
  assert.equal(others[1].counterpart, 'A Consortium');
  assert.equal(others[1].source, null);
});

// ------------------------------------------------------------ Light Pull facts

test('Light Pull rows follow the actor category and separate the kinds of missing', () => {
  const university = lightFactRows({reviewed_payload: {actor_category: 'university_academic'}});
  const keys = university.map(row => row.key);
  assert.ok(keys.includes('rankings'), 'universities show rankings');
  assert.ok(!keys.includes('published_stage_or_trl'), 'universities never show a TRL');
  assert.ok(keys.includes('topic_unit_and_work'));
  // No facts recorded at all means the layer has not run.
  assert.equal(university[0].state, MISSING.notYetChecked);

  const startup = lightFactRows({
    reviewed_payload: {actor_category: 'startup'},
    agent_metadata: {facts: [
      {fact_type: 'light_pull', layer: 1, fact_key: 'funding_signal', collection_state: 'not_found', value: null},
      {fact_type: 'light_pull', layer: 1, fact_key: 'published_stage_or_trl', value: 'TRL 4',
       source_url: 'https://example.org/trl', date_read: '2026-10-01', confidence: 'High', source_origin: 'newly_found'},
    ]},
  });
  const startupKeys = startup.map(row => row.key);
  assert.ok(startupKeys.includes('published_stage_or_trl'), 'startups show the TRL row');
  assert.ok(!startupKeys.includes('rankings'), 'startups never show rankings');
  const trl = startup.find(row => row.key === 'published_stage_or_trl');
  assert.equal(trl.value, 'TRL 4');
  assert.equal(trl.confidence, 'High');
  assert.equal(trl.source, 'https://example.org/trl');
  // The layer ran, so an absent row is Not Found rather than Not Yet Collected.
  assert.equal(startup.find(row => row.key === 'funding_signal').state, MISSING.notFound);
  assert.equal(startup.find(row => row.key === 'recent_activity').state, MISSING.notFound);
});

test('a nonprofit shows neither a TRL nor a ranking row', () => {
  const keys = lightFactRows({reviewed_payload: {actor_category: 'foundation_nonprofit'}})
    .map(row => row.key);
  assert.ok(!keys.includes('published_stage_or_trl'));
  assert.ok(!keys.includes('rankings'));
});

test('Light Pull is Layer 1 only and Deep Pull evidence stays separate', () => {
  const candidate = {agent_metadata: {facts: [
    {fact_type: 'light_pull', layer: 1, fact_key: 'funding_signal', collection_state: 'not_found', value: null},
    {fact_type: 'classification', layer: 1, fact_key: 'actor_category_type', value: {actor_category: 'company'}},
    {fact_type: 'deep_pull', layer: 2, fact_key: 'relevant_products', value: 'excluded from Light'},
  ]}};
  assert.deepEqual(lightPullFacts(candidate).map(fact => fact.fact_key), ['funding_signal']);
  assert.deepEqual(deepPullFacts(candidate).map(fact => fact.fact_key), ['relevant_products']);
  assert.equal(formatFactValue(null), 'No value recorded');
  // A recorded fact is shown to a reviewer, not to a developer. Light Pull
  // stores structured values, and dumping them as raw JSON put
  // `{ "reason": "Found by open-web discovery ..." }` on screen instead of the
  // sentence. A single meaningful sentence renders as itself; a small object
  // renders as labelled lines.
  assert.equal(formatFactValue({actor_category: 'company'}), 'Actor Category: company');
  assert.equal(formatFactValue({reason: 'Found by open-web discovery for hub X'}),
    'Found by open-web discovery for hub X');
  assert.equal(formatFactValue({state: 'not_yet_checked'}), 'State: not_yet_checked');
  assert.equal(formatFactValue(['AI', 'HEALTH']), 'AI, HEALTH');
  // Several scalars become one labelled line each, and empties are left out.
  assert.equal(formatFactValue({name: '', country: 'US', latitude: 37.3}),
    ['Country: US', 'Latitude: 37.3'].join('\n'));
});

test('history keeps superseded values alongside the current one', () => {
  const rows = factHistoryRows({
    reviewed_payload: {actor_category: 'company'},
    agent_metadata: {fact_history: [
      {fact_key: 'funding_signal', value: 'Series A', is_current: false, lifecycle_state: 'superseded', date_read: '2026-05-01'},
      {fact_key: 'funding_signal', value: 'Series B', is_current: true, date_read: '2026-09-01'},
    ]},
  });
  assert.equal(rows.length, 2);
  assert.equal(rows[0].isCurrent, false);
  assert.equal(rows[1].isCurrent, true);
  assert.equal(rows[0].label, 'Funding Signal');
});

// ------------------------------------------------------------- queue and runs

const candidates = [
  {candidate_id: 'a', display_name: 'Example Lab', entity_type: 'actor', status: 'pending_review',
   source_run_id: 'run-1', run_group_key: 'pre_redesign_backlog', review_reason: 'category_doubt',
   reviewed_payload: {description: 'Battery research', actor_category: 'research_center'}},
  {candidate_id: 'p', display_name: 'Sam Example', entity_type: 'person', status: 'approved',
   source_run_id: 'run-1', run_group_key: 'pre_redesign_backlog', reviewed_payload: {title: 'Director'}},
  {candidate_id: 'e', display_name: 'Water Summit', entity_type: 'event', status: 'rejected_by_reviewer',
   source_run_id: 'run-2', run_group_key: 'run-2', reviewed_payload: {location: 'Boston'}},
];

test('queue filters combine status, kind, run group, category, reason and text', () => {
  assert.deepEqual(filterReviewCandidates(candidates, {status: 'pending_review'}).map(x => x.candidate_id), ['a']);
  assert.deepEqual(filterReviewCandidates(candidates, {entity_type: 'person'}).map(x => x.candidate_id), ['p']);
  assert.deepEqual(filterReviewCandidates(candidates, {run_group: 'run-2'}).map(x => x.candidate_id), ['e']);
  assert.deepEqual(filterReviewCandidates(candidates, {run_group: 'pre_redesign_backlog'}).map(x => x.candidate_id), ['a', 'p']);
  assert.deepEqual(filterReviewCandidates(candidates, {review_reason: 'category_doubt'}).map(x => x.candidate_id), ['a']);
  assert.deepEqual(filterReviewCandidates(candidates, {actor_category: 'research_center'}).map(x => x.candidate_id), ['a']);
  assert.deepEqual(filterReviewCandidates(candidates, {search: 'battery'}).map(x => x.candidate_id), ['a']);
  assert.deepEqual(filterReviewCandidates(candidates, {status: 'all', entity_type: 'event', search: 'summit'}).map(x => x.candidate_id), ['e']);
});

test('the queue groups the pre-redesign backlog first, then one group per run', () => {
  const groups = groupQueue(candidates, [
    {key: 'pre_redesign_backlog', label: 'Pre-Redesign Backlog', is_backlog: true, trigger_label: null},
    {key: 'run-2', label: 'Open-web actor discovery', is_backlog: false, trigger_label: 'Manual'},
  ]);
  assert.deepEqual(groups.map(group => group.key), ['pre_redesign_backlog', 'run-2']);
  assert.deepEqual(groups[0].candidates.map(x => x.candidate_id), ['a', 'p']);
  assert.deepEqual(groups[1].candidates.map(x => x.candidate_id), ['e']);
  // A candidate whose group is not listed is surfaced, never silently dropped.
  const orphan = groupQueue([{candidate_id: 'z', run_group_key: 'missing'}], []);
  assert.deepEqual(orphan.map(group => group.key), ['unrecorded']);
});

test('run labels and chips hide raw UUIDs without changing the stored run id', () => {
  const source = {
    source_run_id: 'discovery:577bd0bd-263a-43a7-90f8-373f7cab65ae',
    source_description: 'Open-web actor discovery · dry_run · 577bd0bd-263a-43a7-90f8-373f7cab65ae',
    entity_type: 'actor', run_trigger: 'manual',
  };
  assert.equal(reviewRunLabel(source), 'Open-web actor discovery · dry_run');
  assert.equal(source.source_run_id, 'discovery:577bd0bd-263a-43a7-90f8-373f7cab65ae');
  assert.equal(runChip(source), 'Open-web actor discovery · dry_run · Manual');
  assert.equal(reviewRunLabel({description: 'v2-review:577bd0bd-263a-43a7-90f8-373f7cab65ae'}), 'Discovery Run');
});

test('the 965 migrated actors are labelled, with no invented reviewer or date', () => {
  assert.equal(isMigratedBaseline({source_run_id: 'existing_canonical_migration'}), true);
  assert.equal(isMigratedBaseline({run_trigger: 'migration'}), true);
  assert.equal(isMigratedBaseline({source_run_id: 'discovery:abc'}), false);
  assert.match(component, /SENTENCES\.migratedBaseline/);
});

// ------------------------------------------------------------------- badges

test('header badges carry the record kind, the review state and every reason', () => {
  const badges = headerBadges({
    entity_type: 'actor', status: 'pending_review', record_status: 'parked',
    review_reason: 'geocode_failed', duplicate_state: 'possible_duplicate',
  });
  assert.deepEqual(badges.map(badge => badge.label),
    ['Actor', 'Parked', 'Geocode Failed', 'Possible Duplicate']);
  assert.equal(reviewReasonLabel('hub_member_outside_radius'), 'Hub Member Outside Radius');
  assert.equal(reviewReasonLabel(''), '');
  assert.equal(reviewStatusLabel('rejected_by_reviewer'), 'Rejected');
});

// ---------------------------------------------------------------- decisions

test('only API-provided editable fields enter a decision payload', () => {
  const candidate = {editable_fields: ['name', 'description']};
  const payload = editableReviewPayload(candidate,
    {name: 'Reviewed Lab', description: 'Reviewed', source_id: 'forbidden', _judge: {score: 1}});
  assert.deepEqual(payload, {name: 'Reviewed Lab', description: 'Reviewed'});
});

test('decisions enforce a reviewer, a target and a fixed rejection reason', () => {
  const candidate = {status: 'pending_review'};
  for (const entity of ['actor', 'event', 'person']) {
    assert.deepEqual(decisionOptions(entity).map(x => x.value),
      ['same_existing', 'new', 'reject', 'defer']);
  }
  assert.equal(canSubmitReview({candidate, reviewer: 'R', decisionKind: 'new', admissionConfigured: true}), true);
  // Fail closed: no writer, no decision.
  assert.equal(canSubmitReview({candidate, reviewer: 'R', decisionKind: 'new', admissionConfigured: false}), false);
  // Never a defaulted or guessed reviewer.
  assert.equal(canSubmitReview({candidate, reviewer: '', decisionKind: 'new', admissionConfigured: true}), false);
  assert.equal(canSubmitReview({candidate, reviewer: 'R', decisionKind: 'same_existing', targetId: '', admissionConfigured: true}), false);
  assert.equal(canSubmitReview({candidate, reviewer: 'R', decisionKind: 'same_existing', targetId: 'id', admissionConfigured: true}), true);
  assert.equal(canSubmitReview({candidate, reviewer: 'R', decisionKind: 'reject', rejectionReason: 'Outside target geography', admissionConfigured: true}), true);
  assert.equal(canSubmitReview({candidate, reviewer: 'R', decisionKind: 'reject', rejectionReason: 'Other', rejectionOther: '', admissionConfigured: true}), false);
  assert.equal(canSubmitReview({candidate: {status: 'approved'}, reviewer: 'R', decisionKind: 'defer', admissionConfigured: true}), false);
  // A draft error blocks the decision too.
  assert.equal(canSubmitReview({candidate, reviewer: 'R', decisionKind: 'new', admissionConfigured: true, draftErrors: {name: 'Required.'}}), false);
});

test('the confirmation lists every pending edit, before and after', () => {
  const candidate = {
    editable_fields: ['name', 'actor_category', 'category_type'],
    reviewed_payload: {name: 'Old Name', actor_category: 'company', category_type: 'small_mid_size'},
  };
  assert.deepEqual(
    pendingEdits(candidate, {name: 'New Name', actor_category: 'company', category_type: 'public_company'}),
    [
      {field: 'name', before: 'Old Name', after: 'New Name'},
      {field: 'category_type', before: 'small_mid_size', after: 'public_company'},
    ],
  );
  assert.match(component, /function confirmText\(kind\)/);
  assert.match(component, /SENTENCES\.verifyConsequences/);
  assert.match(component, /SENTENCES\.noDeletion/);
});

test('inline length validation and explicit duplicate differences', () => {
  const candidate = {entity_type: 'actor', editable_fields: ['name'], field_constraints: {name: {max_length: 5}}};
  assert.deepEqual(validateReviewDraft(candidate, {name: '123456'}), {name: 'Maximum 5 characters.'});
  assert.deepEqual(diffFields({name: 'New'}, {payload: {name: 'Held'}}),
    [{field: 'name', candidate: 'New', existing: 'Held'}]);
});

// ----------------------------------------------------------------- layout

test('the six numbered boxes are present and the IDs live only in Audit', () => {
  for (const title of Object.values(SECTIONS)) {
    assert.ok(component.includes(title) || component.includes(`SECTIONS.${Object.keys(SECTIONS).find(k => SECTIONS[k] === title)}`),
      `missing section: ${title}`);
  }
  assert.match(component, /SECTIONS\.identity/);
  assert.match(component, /SECTIONS\.location/);
  assert.match(component, /SECTIONS\.sector/);
  assert.match(component, /SECTIONS\.facts/);
  assert.match(component, /SECTIONS\.duplicates/);
  assert.match(component, /SECTIONS\.audit/);
  // No raw identifiers in the main view: they appear once, inside the Audit panel.
  const auditPanel = component.split('review-audit')[1] || '';
  assert.match(auditPanel, /FIELDS\.candidateId/);
  assert.match(auditPanel, /FIELDS\.runId/);
  // The legacy actor_type is no longer a field a reviewer is shown or asked
  // about: not a control, not a box, not a row in the Audit panel. It stays in
  // the raw candidate data, and keeps a label so that a diff against an
  // existing record still reads properly rather than printing a raw column
  // name.
  assert.ok(AUDIT_ONLY_FIELDS.has('actor_type'));
  assert.ok(AUDIT_ONLY_FIELDS.has('actor_type_raw'));
  assert.doesNotMatch(auditPanel, /FIELDS\.legacyActorType/);
  assert.doesNotMatch(component, /summary\?\.legacy_actor_type/);
  assert.equal(reviewFieldLabel('actor_type'), 'Legacy Actor Type');
  assert.doesNotMatch(component, /class="review-provenance"/);
});

test('decisions, the sticky footer and the queue are reachable and keyboard-operable', () => {
  assert.match(component, /class="review-footer"/);
  assert.match(component, /BUTTONS\.verify/);
  assert.match(component, /BUTTONS\.park/);
  assert.match(component, /BUTTONS\.reject/);
  assert.match(component, /BUTTONS\.saveEdits/);
  assert.match(component, /request\(`\/api\/review\/candidates\/\$\{selectedId\}`\)/);
  assert.match(component, /request\(\s*`\/api\/review\/candidates\/\$\{selected\.candidate_id\}\/decision`/);
  assert.match(component, /window\.confirm/);
  assert.match(component, /target="_blank" rel="noreferrer"/);
  assert.match(component, /aria-pressed=/);
  assert.match(component, /aria-live="polite"/);
  assert.match(component, /aria-readonly="true"/);
});

test('every action is disabled while the canonical writer is unavailable', () => {
  assert.match(component, /const writerDown = !data\.admission_configured/);
  assert.match(component, /disabled=\$\{!pending \|\| busy \|\| writerDown\}/);
  assert.match(component, /SENTENCES\.writerUnavailable/);
});

test('Review is mounted and its navigation entry is present', () => {
  const page = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  assert.match(page, /\["review","Review","✓"\]/);
  assert.match(page, /display:tab==="review"/);
});

// ------------------------------------------------------- the label dictionary

test('no Review string is hard-coded outside the label dictionary', () => {
  // Every user-visible string in the component resolves through labels.js or
  // taxonomy.js, so a typo is fixed in one place.
  // (A ?v= suffix only versions the URL so browsers fetch new code.)
  assert.match(component, /from "\.\/labels\.js(\?v=\w+)?"/);
  assert.match(component, /from "\.\/taxonomy\.js(\?v=\w+)?"/);
  const titles = Object.values(SECTIONS);
  for (const title of titles) {
    assert.ok(!component.includes(`>${title}<`), `${title} is written inline instead of via SECTIONS`);
  }
});

test('every dictionary label is Title Case with the function words lower case', () => {
  for (const [group, entries] of Object.entries(TITLE_CASE_GROUPS)) {
    for (const [key, label] of Object.entries(entries)) {
      const words = label.split(/[\s/]+/).filter(Boolean);
      words.forEach((word, position) => {
        for (const part of word.split('-')) {
          const bare = part.replace(/[^A-Za-z&]/g, '');
          // "&" on its own is punctuation ("Identity & Classification"), not a word.
          if (!bare || !/[A-Za-z]/.test(bare)) continue;
          if (ACRONYMS.has(bare.toUpperCase())) {
            assert.equal(part, part.toUpperCase(), `${group}.${key}: ${part} is an acronym`);
            continue;
          }
          if (position > 0 && TITLE_CASE_LOWER_WORDS.has(bare.toLowerCase())) {
            assert.equal(part, part.toLowerCase(),
              `${group}.${key}: "${part}" is a function word and stays lower case`);
            continue;
          }
          assert.ok(/^[A-Z]/.test(part),
            `${group}.${key}: "${part}" should start with a capital`);
        }
      });
    }
  }
});

test('the six missingness words are distinct and never substituted for each other', () => {
  const values = Object.values(MISSING);
  assert.equal(new Set(values).size, values.length);
  // "Not Yet Collected" is the database's own word (actor_fact.collection_state
  // allows found / not_found / not_yet_collected), so the screen uses it rather
  // than a synonym.
  assert.deepEqual(values, [
    'Not Found', 'Not Yet Collected', 'Not Provided', 'Pending Classification',
    'Not Available', 'Not Applicable',
  ]);
});

test('field labels come from the dictionary', () => {
  assert.equal(reviewFieldLabel('actor_category'), 'Actor Category');
  assert.equal(reviewFieldLabel('category_type'), 'Category Type');
  assert.equal(reviewFieldLabel('category_note'), 'Classification Note');
  assert.equal(reviewFieldLabel('actor_type'), 'Legacy Actor Type');
  assert.equal(reviewFieldLabel('location_city'), 'City');
});

test('a fact column never claims a search that did not happen', () => {
  // Decision: "Not Found" means the layer looked. "Not Yet Collected" means it
  // did not run. The source, date, confidence and origin columns carry the same
  // kind of missing as the row they belong to.
  const unchecked = lightFactRows({reviewed_payload: {actor_category: 'company'}});
  for (const row of unchecked) {
    assert.equal(row.state, MISSING.notYetChecked);
    assert.equal(row.metaState, MISSING.notYetChecked,
      `${row.key}: an unrun layer must not report a missing source as Not Found`);
  }

  const searched = lightFactRows({
    reviewed_payload: {actor_category: 'company'},
    agent_metadata: {facts: [
      {fact_type: 'light_pull', layer: 1, fact_key: 'funding_signal', collection_state: 'not_found', value: null},
    ]},
  });
  for (const row of searched) {
    assert.equal(row.metaState, MISSING.notFound,
      `${row.key}: once the layer has run, an absent column is Not Found`);
  }
});

test('every review reason has its own label, and none reads as a decision', () => {
  const labels = Object.keys(REVIEW_REASON_LABELS).map(reviewReasonLabel);
  assert.equal(new Set(labels).size, labels.length, 'two review reasons share a label');
  // "Verified" is a decision GHUS makes, not a reason a record is in the queue.
  assert.ok(!labels.includes('Verified'));
  assert.equal(reviewReasonLabel('verify_actor'), 'Awaiting Verification');
  assert.equal(reviewReasonLabel('verify_person'), 'Awaiting Person Verification');
  assert.equal(reviewReasonLabel('verify_event'), 'Awaiting Event Verification');
  assert.equal(reviewReasonLabel('hub_assignment'), 'Hub Assignment');
  assert.equal(reviewReasonLabel('same_topic_overlap'), 'Same Topic Overlap');
});

// ------------------------------- agreement with the database's own vocabulary
// These pin the UI to the CHECK constraints in the Architecture V2 target
// schema (docs/evidence/v2_target_schema_manifest_2026-10-06.json in the
// backend repo). A value the database can store must render as a real label,
// never as a raw code.

test('the ledger state not_yet_collected reads Not Yet Collected', () => {
  // actor_fact_collection_state_check allows exactly found / not_found /
  // not_yet_collected, and anything other than found carries a NULL value.
  const rows = lightFactRows({
    reviewed_payload: {actor_category: 'company'},
    agent_metadata: {facts: [
      {fact_type: 'light_pull', layer: 1, fact_key: 'funding_signal',
       collection_state: 'not_yet_collected', value: null},
      {fact_type: 'light_pull', layer: 1, fact_key: 'recent_activity',
       collection_state: 'not_found', value: null},
      {fact_type: 'light_pull', layer: 1, fact_key: 'description',
       collection_state: 'found', value: 'A company.'},
    ]},
  });
  const byKey = Object.fromEntries(rows.map(row => [row.key, row]));
  assert.equal(byKey.funding_signal.state, MISSING.notYetChecked);
  assert.equal(byKey.recent_activity.state, MISSING.notFound);
  assert.equal(byKey.description.state, null);
  assert.equal(byKey.description.value, 'A company.');
});

test('the stored UM6P/OCP link code resolves to its Guide label', () => {
  // entity_edge_relationship_type_check allows connected_to_um6p_ocp, without
  // the trailing _entity that Appendix B writes. Both must display properly.
  assert.equal(linkTypeLabel('connected_to_um6p_ocp'), 'Connected to UM6P/OCP Entity');
  assert.equal(linkTypeLabel('connected_to_um6p_ocp_entity'), 'Connected to UM6P/OCP Entity');
  assert.equal(isParentLink('connected_to_um6p_ocp'), false);
});

test('every review_kind the database allows has a label', () => {
  // The full ck_review_item_kind list.
  const stored = [
    'verify_actor', 'category_doubt', 'geocode_failed', 'hub_needs_review',
    'hub_radius_overlap', 'hub_member_outside_radius', 'hub_center_drift',
    'hub_proposal', 'possible_duplicate', 'fact_conflict', 'pending_update',
    'verify_person', 'verify_event', 'identity', 'affiliation_change',
    'classification', 'geocode', 'hub_assignment', 'same_topic_overlap',
    'new_hub', 'pending_human_update',
  ];
  for (const kind of stored) {
    const label = reviewReasonLabel(kind);
    assert.ok(REVIEW_REASON_LABELS[kind], `${kind} has no label`);
    assert.ok(!label.includes('_'), `${kind} renders as a raw code`);
    assert.ok(/^[A-Z]/.test(label), `${kind} label is not Title Case`);
  }
  assert.equal(new Set(stored.map(reviewReasonLabel)).size, stored.length,
    'two review kinds share a label');
});

test('controlled strength and confidence values display as labels', () => {
  // actor_topic_match_strength_check: strong | moderate.
  // actor_fact_confidence_check: high | medium | low. All stored lower case.
  assert.equal(matchStrengthLabel('strong'), 'Strong');
  assert.equal(matchStrengthLabel('moderate'), 'Moderate');
  assert.equal(confidenceLabel('high'), 'High');
  assert.equal(confidenceLabel('medium'), 'Medium');
  assert.equal(confidenceLabel('low'), 'Low');
  // An unknown value is shown as stored, never guessed at.
  assert.equal(confidenceLabel('unverifiable'), 'unverifiable');
  assert.equal(confidenceLabel(null), null);
  assert.equal(matchStrengthLabel(null), MISSING.notFound);
});

test('the screen says which dimension decides hub membership', () => {
  // GHUS decision, 2026-10-08. Sector decides; topic is recorded but no longer
  // gates. A reviewer should be able to read that off the screen.
  // Carried by the badges on the fields themselves rather than by a paragraph
  // of explanation: the screen is for reviewing a record, not for teaching the
  // rule. The sector field is marked "Decides Hub". The topic "Secondary"
  // row was removed at GHUS request (2026-10-15).
  assert.match(component, /BADGES\.hubDimension/);
  assert.doesNotMatch(component, /BADGES\.secondary/);
  assert.equal(BADGES.hubDimension, 'Decides Hub');
  // And the explanatory prose is gone from the page.
  assert.doesNotMatch(component, /SENTENCES\.sectorDecidesHub/);
  assert.doesNotMatch(component, /SENTENCES\.topicIsSecondary/);
});

// ------------------------------------------- layout correction and dropdowns

test('the filters sit above the workspace, not inside the queue rail', () => {
  // The original layout put them across the top, and that is where they work:
  // in the rail they made it tall and heavy and pushed the editing area aside.
  const filtersAt = component.indexOf('class="review-filters"');
  const workspaceAt = component.indexOf('class="review-workspace"');
  assert.ok(filtersAt > 0 && workspaceAt > 0);
  assert.ok(filtersAt < workspaceAt, 'the filters must come before the workspace');
  // Only one filter block, so they were moved rather than duplicated.
  assert.equal(component.split('class="review-filters"').length - 1, 1);
});

test('the editing area is the dominant pane', () => {
  const css = fs.readFileSync(new URL('../frontend/review.css', import.meta.url), 'utf8');
  const grid = css.match(/\.review-workspace\{[^}]*grid-template-columns:([^;]+);/);
  assert.ok(grid, 'the workspace grid must be declared');
  // The rail is a fixed, narrow column; the detail takes the rest.
  assert.match(grid[1], /minmax\(230px,\s*270px\)\s+minmax\(0,\s*1fr\)/);
});

test('hub assignment is one dropdown of existing hubs, with an explicit no-hub option', () => {
  assert.match(component, /BUTTONS\.chooseHub/);
  assert.match(component, /SENTENCES\.noHubOption/);
  assert.doesNotMatch(component, /select multiple value=\$\{hubIds\}/);
  // It never creates a hub.
  assert.match(SENTENCES.hubDropdownRule, /never created here/);

  const options = hubDropdownOptions({agent_metadata: {
    hub_memberships: [{hub_id: 'h1', name: 'Corn Belt', distance_miles: 18.4}],
    hub_suggestions: [{hub_id: 'h2', name: 'Delta Valley', distance_miles: 44.1}],
    hubs: [{hub_id: 'h1', name: 'Corn Belt'}, {hub_id: 'h2', name: 'Delta Valley'},
           {hub_id: 'h3', name: 'Gulf Coast'}],
  }});
  // Assigned first, then suggested, then the rest — each labelled as what it is,
  // and never listed twice.
  assert.deepEqual(options.map(o => o.hub_id), ['h1', 'h2', 'h3']);
  assert.match(options[0].label, /Currently Assigned/);
  assert.match(options[0].label, /18\.4 mi/);
  assert.match(options[1].label, /Suggested/);
  assert.doesNotMatch(options[2].label, /Assigned|Suggested/);
  assert.deepEqual(hubDropdownOptions({}), []);
});

test('sector is a controlled dropdown that grows with the reference data', () => {
  assert.match(component, /FIELDS\.primarySector/);
  assert.doesNotMatch(component, /review-checklist/);
  const base = sectorOptions();
  assert.equal(base.length, 8, 'the eight thematic sectors');
  assert.deepEqual(base.map(o => o.value),
    ['AGRI', 'WATER', 'AI', 'ENERGY', 'MINING', 'CHEM', 'HEALTH', 'SUSTAIN']);
  // A sector already on the record is offered even when it is not thematic, so
  // an existing value is never dropped from its own dropdown.
  const widened = sectorOptions(['CROSS']);
  assert.equal(widened.length, 9);
  assert.equal(widened.at(-1).label, 'Cross-Cutting');
  // Duplicates do not accumulate.
  assert.equal(sectorOptions(['AGRI', 'AGRI']).length, 8);
});

test('country is a controlled dropdown and the stored spellings resolve', () => {
  assert.match(component, /countryOptions\(\)/);
  assert.ok(COUNTRIES.length > 150);
  // The data holds both spellings for the same country; both resolve to one.
  assert.equal(normalizeCountry('USA'), 'United States');
  assert.equal(normalizeCountry('United States'), 'United States');
  assert.equal(normalizeCountry('Morocco'), 'Morocco');
  // An unrecognised value is kept exactly as stored rather than discarded.
  assert.equal(normalizeCountry('Atlantis'), 'Atlantis');
  assert.equal(normalizeCountry(''), '');
  // Changing the country re-derives the region.
  assert.match(component, /function editCountry\(value\)/);
  assert.match(component, /regionForState\(current\.state, value\)/);
});

test('Light Pull fills information boxes, and the category drives which ones', () => {
  // Not a separate table: boxes, in two groups.
  assert.match(component, /lightPullBoxes\(selected, draft\.actor_category\)/);
  assert.match(component, /FIELDS\.commonLightPull/);
  assert.match(component, /review-boxes/);

  const candidate = {reviewed_payload: {actor_category: 'university_academic'}};
  const university = lightPullBoxes(candidate, 'university_academic');
  const startup = lightPullBoxes(candidate, 'startup');

  // Common boxes do not change with the category.
  assert.deepEqual(university.common.map(r => r.key), startup.common.map(r => r.key));
  // Category-specific ones do, and follow Architecture V2 Sept 5.2.
  assert.ok(university.specific.some(r => r.key === 'rankings'));
  assert.ok(!startup.specific.some(r => r.key === 'rankings'));
  assert.ok(startup.specific.some(r => r.key === 'published_stage_or_trl'));
  assert.ok(!university.specific.some(r => r.key === 'published_stage_or_trl'));

  // A field already shown as an editable control is not repeated as a box.
  for (const key of ['description', 'website', 'location', 'actor_category_type']) {
    assert.ok(!university.common.some(r => r.key === key), `${key} is duplicated`);
  }
  // Every box stays visible even with nothing in it, saying which kind of
  // absence it is.
  assert.ok(university.specific.every(r => r.state === MISSING.notYetChecked));
  // An unknown category still yields the common boxes and no specific ones.
  assert.equal(lightPullBoxes(candidate, '').specific.length, 0);
  assert.ok(lightPullBoxes(candidate, '').common.length > 0);
});

test('changing the actor category never discards what the reviewer typed', () => {
  // lightPullBoxes reads the category it is given and leaves the payload alone.
  const candidate = {reviewed_payload: {
    actor_category: 'startup', description: 'Typed by the reviewer.',
  }};
  const before = JSON.stringify(candidate.reviewed_payload);
  lightPullBoxes(candidate, 'university_academic');
  assert.equal(JSON.stringify(candidate.reviewed_payload), before);
  // Only an incompatible category TYPE is cleared, and only after confirming.
  assert.match(component, /window\.confirm\(SENTENCES\.categoryChangeWarning\)/);
});

// ---------------------------------------------------- WS6 the Updates tab

test('Review has an Updates tab that does not disturb the queue', () => {
  assert.match(component, /class="review-tabs"/);
  assert.match(component, /SECTIONS\.updates/);
  assert.match(component, /request\("\/api\/review\/subscriptions"\)/);
  // The queue and the updates view are alternatives, not stacked panels.
  assert.match(component, /view === "queue" && html`<div class="review-workspace">/);
  assert.match(component, /view === "updates" && html`<section class="review-updates"/);
  // The list is loaded once, when the tab is first opened.
  assert.match(component, /if \(view !== "updates" \|\| updates\.loaded\) return;/);
});

test('a subscription scope reads as the intersection it is', () => {
  // Sector AGRI plus state CA means agriculture actors in California, not
  // everything in either, so the joining word is "and".
  assert.equal(
    subscriptionScopeLabel({sector_codes: ['AGRI'], state_code: 'CA'}),
    'Agriculture and CA',
  );
  assert.equal(
    subscriptionScopeLabel({actor_ids: ['a', 'b'], city: 'Davis', country: 'United States'}),
    '2 named actors and Davis, United States',
  );
  assert.equal(subscriptionScopeLabel({actor_ids: ['a']}), '1 named actor');
  assert.equal(subscriptionScopeLabel({topic_ids: ['t1', 't2']}), '2 topics');
  // An unscoped subscription would sweep everything, so it says so rather than
  // rendering as an innocuous blank.
  assert.equal(subscriptionScopeLabel({}), SENTENCES.subscriptionNoScope);
  assert.match(SENTENCES.subscriptionNoScope, /must not run/);
});

test('subscription statuses are labelled and only one of them runs', () => {
  for (const [status, label] of Object.entries(SUBSCRIPTION_STATUS_LABELS)) {
    assert.equal(subscriptionStatusLabel(status), label);
    assert.ok(/^[A-Z]/.test(label));
  }
  assert.deepEqual(Object.keys(SUBSCRIPTION_STATUS_LABELS),
    ['active', 'paused', 'expired', 'cancelled']);
  // An unrecognised status is shown as stored rather than hidden.
  assert.equal(subscriptionStatusLabel('draining'), 'draining');
});

test('the Updates tab shows words, not database codes', () => {
  // Found by looking at the rendered tab: requested_via was printing its raw
  // code. review.js's own rule is that debug strings never reach the main view.
  assert.equal(requestedViaLabel('map_verification'), 'Map Verification');
  assert.equal(requestedViaLabel('review_updates'), 'Review Updates');
  assert.deepEqual(Object.keys(REQUESTED_VIA), ['map_verification', 'review_updates']);
  // An unrecognised channel is still readable rather than blank, because the
  // value is real data even when this screen does not know the code yet.
  assert.equal(requestedViaLabel('monthly_report'), 'monthly report');
  assert.equal(requestedViaLabel(null), '');
  // And the tab renders through the label, never the bare field.
  assert.match(component, /requestedViaLabel\(item\.requested_via\)/);
  assert.doesNotMatch(component, /<dd>\$\{item\.requested_via\}/);
});

test('a subscription period reads in the same date form as its next due date', () => {
  // Found by looking at the rendered tab: the period printed ISO "2026-08-30"
  // beside a localised Next Due. start_date is a calendar date and last_run_at
  // is epoch seconds, so the two cannot share one formatter.
  const line = subscriptionPeriodLabel({
    cadence: 'monthly', start_date: '2026-08-30', end_date: '2027-04-07',
  });
  assert.match(line, /^Subscription · Monthly · /);
  // Assembled as one string, because htm drops the whitespace at a line break
  // and rendered this as "Monthly· 30/08/2026to 07/04/2027".
  assert.match(line, / to /);
  assert.doesNotMatch(line, /\S·|·\S|\d{4}to/);
  assert.doesNotMatch(line, /2026-08-30/);
  // A date-only value is built from its parts, so a reader west of Greenwich is
  // not shown the previous day.
  assert.match(component, /function formatDay[\s\S]*?split\("-"\)/);
  assert.doesNotMatch(component, /formatDate\(item\.(start|end)_date\)/);
  // A period with no recorded end says which kind of missing it is.
  assert.match(
    subscriptionPeriodLabel({cadence: 'weekly', start_date: '2026-03-23'}),
    /to Not Provided$/,
  );
});

test('the Updates tab never invents a requester and never creates a subscription', () => {
  // requested_by is null until authentication exists.
  assert.match(component, /item\.requested_by \|\| SENTENCES\.noRunRecorded/);
  // Read-only: no POST, PATCH or DELETE against the subscriptions endpoint.
  const calls = component.match(/\/api\/review\/subscriptions[^`]*/g) || [];
  assert.equal(calls.length, 1);
  assert.doesNotMatch(component, /subscriptions`?,\s*\{\s*method/);
  assert.match(SENTENCES.subscriptionsExplain, /event update schedule is separate/);
});

test('a hub proposal says it is only a proposal, with its margin', () => {
  // Detection proposes; GHUS decides. The page must never suggest a hub exists.
  assert.equal(
    hubProposalPlace({primary_city: 'Albany', state: 'OR', country: 'US',
                      dimension: 'sector', dimension_key: 'AGRI'}),
    'Albany, OR, US · sector AGRI',
  );
  assert.match(hubProposalPlace({}), /Not Provided/);

  // The count alone does not say whether it passed; the requirement alone does
  // not say by how much. Show both.
  assert.equal(thresholdLabel(12, 10), '12 of 10 required');
  assert.equal(thresholdLabel(0, 10), '0 of 10 required');
  assert.equal(thresholdLabel(null, 10), MISSING.notYetChecked);
  assert.equal(thresholdLabel(7, null), '7');

  // The tab is read-only: it fetches and never writes.
  const calls = component.match(/\/api\/review\/hub-proposals[^`]*/g) || [];
  assert.equal(calls.length, 1);
  assert.doesNotMatch(component, /hub-proposals`?,\s*\{\s*method/);
  assert.match(component, /SENTENCES\.noHubCreated/);
});

test('Why It Matched is one box, reading the explanation discovery recorded', () => {
  // The dedicated box read agent_metadata.why_matched only, which discovery
  // does not always set, so a populated Light Pull fact sat beside an empty box
  // saying Not Yet Collected. One box now, reading either.
  const candidate = {agent_metadata: {facts: [
    {fact_key: 'why_matched', collection_state: 'found', confidence: 'medium',
     source_url: 'https://example.org', date_read: '2026-10-09',
     value: {reason: "Found by open-web discovery for hub 'NYC AI Hub' (topic AI)"}},
  ]}};
  const why = whyMatchedFact(candidate);
  assert.match(why.reason, /NYC AI Hub/);
  assert.equal(why.source_url, 'https://example.org');
  assert.equal(why.date_read, '2026-10-09');

  // Nothing recorded means nothing invented.
  assert.equal(whyMatchedFact({agent_metadata: {facts: []}}), null);
  assert.equal(whyMatchedFact({agent_metadata: {facts: [
    {fact_key: 'why_matched', collection_state: 'not_found', value: null}]}}), null);

  // And it is listed once, not twice.
  assert.equal(COMMON_LIGHT_ROWS.filter(([key]) => key === 'why_matched').length, 0);
});

test('a fact value shows what it says, not when it was read', () => {
  // Recent Activity is stored as {date, description} because Light Pull's
  // evidence rule requires both. The box should read as the statement, not as
  // "Date: October 2024 Description: ...". The date stays on the stored fact.
  assert.equal(
    formatFactValue({date: 'October 2024', description: 'Empire AI Phase One launched.'}),
    'Empire AI Phase One launched.',
  );
  // Date-like keys are dropped even when nothing else is a headline value.
  assert.equal(formatFactValue({date_read: '2026-10-09T16:39:44+00:00', funder: 'Seattle City Light'}),
    'Funder: Seattle City Light');
  // A fact that is only a date says nothing a reviewer can read.
  assert.equal(formatFactValue({retrieved_at: '2026-10-09'}), 'No value recorded');
});


test('sectors come from the database and a reviewer can add one', async () => {
  const {setSectors, sectorOptions, sectorLabel} = await import('../frontend/taxonomy.js');
  setSectors([{code: 'WATER', name: 'Water'}, {code: 'WATER_TECH', name: 'Water Technology'}]);
  assert.deepEqual(sectorOptions().map(o => o.value), ['WATER', 'WATER_TECH']);
  assert.equal(sectorLabel('WATER_TECH'), 'Water Technology');
  assert.match(component, /api\/review\/sectors/);
  assert.match(component, /BUTTONS\.addSector/);
  assert.match(component, /unmatched_sector_suggestion/);
  setSectors([]);
});

test('a box the Light Pull read for says which pages it checked', async () => {
  const {lightFactRows, missingWithPages} = await import('../frontend/review.js');
  const pages = ['https://thewatercouncil.com/', 'https://thewatercouncil.com/about-us/',
    'https://thewatercouncil.com/members/'];
  const candidate = {
    reviewed_payload: {actor_category: 'association_network'},
    agent_metadata: {facts: [
      {fact_key: 'funding_signal', fact_type: 'light_pull', layer: 1, collection_state: 'found', value: '$2 million grant.',
        source_url: pages[1], confidence: 'high', pages_read: pages},
      {fact_key: 'um6p_ocp_connection', fact_type: 'light_pull', layer: 1, collection_state: 'not_found', value: null,
        pages_read: pages},
    ]},
  };
  const rows = Object.fromEntries(lightFactRows(candidate).map((row) => [row.key, row]));
  assert.equal(rows.funding_signal.value, '$2 million grant.');
  assert.equal(missingWithPages(rows.um6p_ocp_connection), 'Not Stated on the 3 Pages Read');
  assert.deepEqual(rows.um6p_ocp_connection.pagesRead, pages);
  // A box with no fact at all, while others were read, is still plain "Not Found".
  assert.equal(missingWithPages(rows.recent_activity), rows.recent_activity.state);
});
