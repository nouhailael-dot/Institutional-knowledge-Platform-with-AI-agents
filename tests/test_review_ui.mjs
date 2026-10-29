import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {
  AUDIT_ONLY_FIELDS,
  DERIVED_FIELDS,
  actorReviewSummary,
  createReviewPage,
  twoWayKind,
  canConfirmCategories,
  canSubmitReviewItem,
  canSubmitReview,
  decisionOptions,
  deepPullFacts,
  diffFields,
  editableReviewPayload,
  factHistoryRows,
  filterReviewCandidates,
  formatFactValue,
  groupQueue,
  RUN_TYPE_OPTIONS,
  recordRowNote,
  recordsOfRun,
  runMeta,
  runsForType,
  runTypeName,
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
  pendingCategoryReviews,
  reviewItemKind,
  reviewFieldLabel,
  reviewReasonLabel,
  reviewRunLabel,
  reviewStatusLabel,
  runChip,
  hubProposalPlace,
  whyMatchedFact,
  thresholdLabel,
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
    {category_type: 'This type belongs to a different Category.'},
  );
  assert.deepEqual(
    validateReviewDraft(candidate, {name: 'X', category_type: 'medical_school'}),
    {actor_category: 'Choose the Category first.'},
  );
});

// ----------------------------------------------------------------- parent

test('no parent reads Not Available with an explanation, not a warning', () => {
  const display = parentDisplay({agent_metadata: {relationships: []}});
  assert.equal(display.hasParent, false);
  assert.equal(display.missing, MISSING.notAvailable);
  assert.match(display.tooltip, /A standalone organization is a complete record/);
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
  assert.equal(formatFactValue({actor_category: 'company'}), 'Category: company');
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

test('Run Type offers exactly six choices, and the reason filter is gone', () => {
  assert.deepEqual(RUN_TYPE_OPTIONS.map(o => o.label),
    ['All Runs', 'Discovery Actors', 'Discovery Events', 'Discovery People', 'Actor Updates',
     'Data Feed Imports']);
  assert.equal(runTypeName('map_checks'), 'Map Checks');
  assert.equal(runTypeName('data_feed'), 'Data Feed Imports');
  assert.doesNotMatch(component, /review_reason:\s*"all"/);
  assert.doesNotMatch(component, /FIELDS\.reviewReason/);
  assert.doesNotMatch(component, /FIELDS\.sourceRun/);
  assert.match(component, /Back to Records/);
  // Two panels: the runs, and the centre; no right-hand panel.
  assert.match(component, /class="review-runs"/);
  assert.match(component, /class="review-main"/);
});

test('the runs panel lists only runs of the type with records in the queue, each once', () => {
  const groups = [
    {key: 'r1', run_type: 'discovery_actors', run_name: 'Battery storage in Texas', run_date: 'Oct 19, 2026', pending_count: 9},
    {key: 'r2', run_type: 'actor_updates', run_name: 'CPower Energy', run_date: 'Oct 19, 2026', pending_count: 1},
    {key: 'r3', run_type: 'discovery_events', run_name: 'Water events', run_date: 'Oct 18, 2026', pending_count: 0},
  ];
  const candidates = [
    {candidate_id: 'a', run_group_key: 'r1'}, {candidate_id: 'b', run_group_key: 'r1'},
    {candidate_id: 'u', run_group_key: 'r2'},
  ];
  // A run with nothing left in the queue disappears.
  assert.deepEqual(runsForType(groups, candidates, 'all').map(g => g.key), ['r1', 'r2']);
  assert.deepEqual(runsForType(groups, candidates, 'actor_updates').map(g => g.key), ['r2']);
  assert.deepEqual(runsForType(groups, candidates, 'discovery_events'), []);
  const [first] = runsForType(groups, candidates, 'discovery_actors');
  // The count is what the queue shows now, so a decision lowers it at once.
  assert.equal(runMeta(first), 'Oct 19, 2026 · 2 pending');
  assert.equal(runMeta(first, 'approved'), 'Oct 19, 2026 · 2 verified');
  assert.deepEqual(recordsOfRun(candidates, 'r1').map(c => c.candidate_id), ['a', 'b']);
  assert.deepEqual(recordsOfRun(candidates, null), []);
  // Every record belongs to exactly one run.
  const shown = runsForType(groups, candidates, 'all').flatMap(g => recordsOfRun(candidates, g.key));
  assert.equal(new Set(shown.map(c => c.candidate_id)).size, shown.length);
});

test('a record row says what it is: an update result, or the kind and reason', () => {
  assert.equal(recordRowNote({agent_metadata: {source_table: 'actor_update'}, entity_type: 'actor'}),
    'Update result · check what it wrote');
  assert.match(recordRowNote({entity_type: 'actor', review_reason: 'below_threshold', agent_metadata: {}}),
    /^Actor · /);
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
  // Stored "parked" by the agent is not a decision: it reads Pending.
  assert.deepEqual(badges.map(badge => badge.label),
    ['Actor', 'Pending', 'Geocode Failed', 'Possible Duplicate']);
  // Parked only when a person parked it - in Review, or on its Build the Map card.
  assert.equal(headerBadges({entity_type: 'actor', status: 'pending_review', record_status: 'parked',
    decision_kind: 'defer'})[1].label, 'Parked');
  assert.equal(headerBadges({entity_type: 'event', status: 'pending_review',
    agent_metadata: {_review: 'parked'}})[1].label, 'Parked');
  assert.equal(reviewStatusLabel('pending_review'), 'Pending');
  // One decision bar, at the bottom: none beside the name, and no hub checkbox,
  // reviewer or notes in each record; the reviewer is named once at the top.
  assert.doesNotMatch(component, /review-card-actions|checked=\$\{proposeHub\}/);
  assert.match(component, /class=\$\{"review-whoami"/);
  assert.match(component, /localStorage\.getItem\("ghus\.review\.reviewer"\)/);
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

test('a record reads like a Build the Map result card, and the IDs live only in Audit', () => {
  // One card per record (organization, event or person): number, name, status
  // and Verify / Park / Reject on top; description; a profile that folds open;
  // the inline facts; its web sources; analyst notes at the bottom.
  for (const marker of ['class=${"mcard review-card"', '<span class="rank">',
    'class=${"review-desc"', 'class="mpeople review-profile"', '>Actor profile<', '"Event profile" : "Person profile"',
    'class="review-facts-row"', 'web source${sources.length > 1', 'class="review-analyst-notes"',
    'class="why"']) {
    assert.ok(component.includes(marker), `missing on the card: ${marker}`);
  }
  // Everything collected stays one click away, then duplicates and the audit.
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
  // The COMPASS navigation (2026-10-29): [id, label], an icon per id.
  assert.match(page, /\["review","Review Results"\]/);
  assert.match(page, /review:svg\(/);
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
  assert.equal(reviewFieldLabel('actor_category'), 'Category');
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
  // Plain words for what the reviewer is asked to do, not the source's code.
  assert.equal(reviewReasonLabel('hub_assignment'), 'Hub to Confirm');
  assert.equal(reviewReasonLabel('same_topic_overlap'), 'Overlaps Another Hub');
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
  // As lines, not boxes: found facts each on a line, the rest named together.
  assert.match(component, /lightLines\(html, lightBoxes\.common\)/);
  assert.match(component, /lightLines\(html, lightBoxes\.specific\)/);
  assert.doesNotMatch(component, /review-boxes|light-box/);

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

// --------------------------------------- requests and runs live in Discovery

test('Review has no Updates tab: Discovery shows the requests and their runs', () => {
  assert.doesNotMatch(component, /view === "updates"/);
  assert.doesNotMatch(component, /setView\("updates"\)/);
  assert.doesNotMatch(component, /\/api\/review\/subscriptions/);
  assert.equal(SECTIONS.updates, undefined);
});

test('every review reason a source sends has a plain label and a reason why', async () => {
  const {reviewReasonLabel, reviewReasonHint} = await import('../frontend/review.js');
  for (const code of ['borderline_score', 'third_party_page', 'website_unverified',
    'page_not_organisation', 'focus_unconfirmed', 'thin_evidence', 'weak_description',
    'low_priority', 'new_person', 'new_record', 'possible_duplicate', 'location_unplaced',
    'relationship_check', 'map_agent']) {
    const label = reviewReasonLabel(code);
    assert.ok(label && !label.includes('_') && label !== code.replaceAll('_', ' '), code);
    assert.ok(reviewReasonHint(code).length > 20, `${code} has no explanation`);
  }
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
  assert.equal(missingWithPages(rows.um6p_ocp_connection), 'Not Found');
  assert.deepEqual(rows.um6p_ocp_connection.pagesRead, pages);
  // A box with no fact at all, while others were read, is still plain "Not Found".
  assert.equal(missingWithPages(rows.recent_activity), rows.recent_activity.state);
});

test('the reason filter offers only reasons that are waiting, most first', async () => {
  const {reasonOptions} = await import('../frontend/review.js');
  assert.deepEqual(reasonOptions({location_unplaced: 154, borderline_score: 97, map_agent: 0}),
    [['location_unplaced', 154], ['borderline_score', 97]]);
  // A chosen reason stays in the list even when nothing matches it any more.
  assert.deepEqual(reasonOptions({borderline_score: 3}, 'possible_duplicate'),
    [['borderline_score', 3], ['possible_duplicate', 0]]);
  assert.deepEqual(reasonOptions(undefined), []);
});

test('a run reads as what it was and how many items wait, not "Manual"', async () => {
  const {runOptionLabel} = await import('../frontend/review.js');
  assert.equal(runOptionLabel({label: 'Actor discovery · test run · Oct 7, 2026',
    trigger: 'manual', trigger_label: 'Manual', pending_count: 15}),
    'Actor discovery · test run · Oct 7, 2026 (15)');
  assert.equal(runOptionLabel({label: 'Discovery request · Water · Oct 15, 2026',
    trigger: 'subscription', trigger_label: 'Subscription', pending_count: 0}),
    'Discovery request · Water · Oct 15, 2026 · Subscription');
});

test('a fact conflict is a choice between the value on the map and the one found', async () => {
  const {factChangeRows, isFactReview, decisionOptions: options, canSubmitReview: canSubmit,
    REVIEW_REASON_LABELS: labels} = await import('../frontend/review.js');
  const candidate = {status: 'pending_review', agent_metadata: {
    source_table: 'review_item', review_kind: 'pending_update', fact_change: {
      field_key: 'funding_signal',
      current: {value: '$1M grant.', source_url: 'https://a.example/', date_read: '2026-01-02T00:00:00',
        confidence: 'high', set_by: 'ghus_human'},
      proposed: {value: '$2M grant.', source_url: 'https://b.example/about',
        date_read: '2026-10-18T09:00:00', confidence: 'high', set_by: 'agent'}}}};
  assert.equal(isFactReview(candidate), true);
  assert.equal(isFactReview({agent_metadata: {source_table: 'review_item', review_kind: 'verify_actor'}}), false);
  assert.deepEqual(options('actor', candidate).map(x => x.value), ['new', 'reject', 'defer']);
  assert.deepEqual(options('actor', candidate).slice(0, 2).map(x => x.label),
    ['Use the new value', 'Keep the current value']);
  // Keeping the current value needs no rejection reason.
  assert.equal(canSubmit({candidate, reviewer: 'R', decisionKind: 'reject', admissionConfigured: true}), true);
  assert.equal(canSubmit({candidate, reviewer: 'R', decisionKind: 'same_existing', targetId: 'x', admissionConfigured: true}), false);
  const {field, rows} = factChangeRows(candidate);
  assert.equal(field, 'funding_signal');
  assert.deepEqual(rows.map(r => [r.label, r.value, r.date_read, r.set_by]), [
    ['In the directory now', '$1M grant.', '01/02/2026', 'GHUS'],
    ['Found by the update', '$2M grant.', '10/18/2026', 'Agent']]);
  assert.ok(labels.fact_conflict && labels.pending_update);
});

test('a proposed link and a hub proposal are each a choice between two answers', async () => {
  const {twoWayKind, twoWaySummary, decisionOptions: options, canSubmitReview: canSubmit} =
    await import('../frontend/review.js');
  const link = {status: 'pending_review', display_name: 'CPower', agent_metadata: {
    source_table: 'review_item', review_kind: 'relationship_review', entity_id: 'a1',
    candidate_name: 'NRG Energy', pipeline: {subject_actor_id: 'a1', object_actor_id: 'a2',
      proposed_relationship_type: 'unit_of', source_url: 'https://cpower.example/about'}}};
  const hub = {status: 'pending_review', display_name: 'CPower', agent_metadata: {
    source_table: 'review_item', review_kind: 'hub_assignment', proposed_hub_name: 'Northeast Energy Hub',
    pipeline: {proposal: 'membership', deterministic_evidence: {sector_code: 'ENERGY',
      distance_miles: 12.5, radius_miles: 200}}}};
  const legacyHub = {agent_metadata: {source_table: 'review_item', review_kind: 'hub_assignment',
    pipeline: {issue: 'needs_review_sector'}}};
  assert.deepEqual([twoWayKind(link), twoWayKind(hub), twoWayKind(legacyHub)],
    ['relationship', 'hub', null]);
  assert.deepEqual(options('actor', link).slice(0, 2).map(o => o.label), ['Confirm the link', 'Not a link']);
  assert.deepEqual(options('actor', hub).slice(0, 2).map(o => o.label), ['Add to the hub', 'Keep it out']);
  assert.equal(twoWaySummary(link).question, 'CPower is a unit of NRG Energy?');
  assert.equal(twoWaySummary(link).source_url, 'https://cpower.example/about');
  // The other side is the subject when the proposal says so.
  const reversed = {...link, agent_metadata: {...link.agent_metadata,
    pipeline: {...link.agent_metadata.pipeline, subject_actor_id: 'a2'}}};
  assert.equal(twoWaySummary(reversed).question, 'NRG Energy is a unit of CPower?');
  assert.equal(twoWaySummary(hub).question, 'Add CPower to Northeast Energy Hub?');
  assert.match(twoWaySummary(hub).detail, /12.5 miles from the centre/);
  // Refusing needs no rejection reason.
  assert.equal(canSubmit({candidate: link, reviewer: 'R', decisionKind: 'reject', admissionConfigured: true}), true);
});

test('an actor update card shows what it wrote in its boxes and is a two-answer check', async () => {
  const {twoWayKind, lightFactRows, decisionOptions: options} = await import('../frontend/review.js');
  const card = {status: 'pending_review', agent_metadata: {source_table: 'actor_update',
    review_kind: 'actor_update', written: [
      {fact_key: 'location', collection_state: 'found', value: {city: 'Montpelier', state: 'VT'},
        previous_value: {region: 'Not Provided', country: 'US'}, lifecycle_state: 'accepted',
        source_url: 'https://www.cleanegroup.org/', confidence: 'high'},
      {fact_key: 'international_connection', collection_state: 'not_found', value: null,
        previous_value: null, lifecycle_state: 'accepted', source_url: 'https://www.cleanegroup.org/'},
      {fact_key: 'funding_signal', collection_state: 'found', value: '$3M',
        previous_value: '$1M', lifecycle_state: 'conflict_flagged', source_url: null}]}};
  assert.equal(twoWayKind(card), 'update');
  assert.deepEqual(options('actor', card).slice(0, 2).map(o => o.label),
    ['Looks right', 'Flag it (the map is not changed)']);
  // No table: each box holds what the update wrote, marked with what it did.
  const rows = Object.fromEntries(lightFactRows({...card, reviewed_payload: {}})
    .map(row => [row.key, row]));
  assert.deepEqual(['location', 'international_connection', 'funding_signal']
    .map(key => rows[key].update.outcome), ['changed', 'not_found', 'conflict']);
  assert.deepEqual(rows.location.value, {city: 'Montpelier', state: 'VT'});
  assert.equal(rows.international_connection.state, 'Not Found');
  // The conflict was not applied: proposed, never shown as the saved value.
  assert.equal(rows.funding_signal.value, null);
  assert.equal(rows.funding_signal.kept, true);
  assert.equal(rows.funding_signal.pending.proposed.value, '$3M');
});

// ------------------------------------------------------------------ actor update profiles

test('an update profile fills its boxes, marks what the update found, and shows proposals as unsaved', async () => {
  const {lightFactRows, lightPullBoxes, updateNote, changeRows, recordRowNote, canSubmitReview,
    isUpdateProfile} = await import('../frontend/review.js');
  const profile = {
    candidate_id: 'p', status: 'pending_review', display_name: 'CPower Energy', entity_type: 'actor',
    reviewed_payload: {name: 'CPower Energy', actor_category: 'company'},
    agent_metadata: {
      source_table: 'actor_update', review_kind: 'actor_profile', entity_id: 'a1',
      facts: [
        {fact_key: 'ownership_and_size', fact_type: 'light_pull', layer: 1, collection_state: 'found',
          value: 'An NRG company', source_url: 'https://cpowerenergy.com/who-we-are/',
          update: {outcome: 'changed', date: 1792368000, previous_value: 'Private company'}},
        {fact_key: 'international_connection', fact_type: 'light_pull', layer: 1,
          collection_state: 'not_found', value: null, update: {outcome: 'not_found'}},
        {fact_key: 'funding_signal', fact_type: 'light_pull', layer: 1, collection_state: 'found',
          value: '$1M.'},
      ],
      update_runs: [{run_id: 'r1', title: 'CPower Energy', counts: {changed: 1}}],
      changes: [{review_item_id: 'c1', kind: 'fact', field_key: 'funding_signal',
        current: {value: '$1M.', source_url: 'https://x.example/a', set_by: 'agent'},
        proposed: {value: '$3M.', source_url: 'https://x.example/b', date_read: '2026-10-19'},
        reason: 'Older reading', can_keep_both: false}],
    },
  };
  assert.equal(isUpdateProfile(profile), true);
  const rows = Object.fromEntries(lightFactRows(profile).map(row => [row.key, row]));
  // Saved values sit in their own boxes, each with what the update did.
  assert.equal(rows.ownership_and_size.value, 'An NRG company');
  assert.match(updateNote(rows.ownership_and_size.update), /^Updated · .* · was: Private company$/);
  assert.equal(rows.international_connection.state, 'Not Found');
  // A box no update read is Not Yet Collected, not Not Found.
  assert.equal(rows.topic_business_segment_product.state, 'Not Yet Collected');
  // The saved value stays; the proposal is attached as pending, never merged in.
  assert.equal(rows.funding_signal.value, '$1M.');
  assert.equal(rows.funding_signal.pending.proposed.value, '$3M.');
  assert.ok(lightPullBoxes(profile).specific.some(row => row.key === 'ownership_and_size'));
  const [change] = changeRows(profile);
  assert.deepEqual(change.choices.map(choice => choice.label), ['Keep Current Value', 'Use New Value']);
  assert.equal(change.previous.value, '$1M.');
  assert.equal(change.proposed.source, 'https://x.example/b');
  assert.equal(recordRowNote(profile), '1 update · 1 change to review');
  // Marked reviewed only once its changes are decided; flagging is always possible.
  const base = {candidate: profile, reviewer: 'R', busy: false, admissionConfigured: true};
  assert.equal(canSubmitReview({...base, decisionKind: 'new'}), false);
  assert.equal(canSubmitReview({...base, decisionKind: 'reject'}), true);
  const decided = {...profile, agent_metadata: {...profile.agent_metadata, changes: []}};
  assert.equal(canSubmitReview({...base, candidate: decided, decisionKind: 'new'}), true);
  assert.equal(recordRowNote(decided), '1 update · nothing to decide');
});

test('keep both is offered only for a location, and links and hubs keep their own answers', async () => {
  const {changeRows} = await import('../frontend/review.js');
  const profile = {display_name: 'Stanford Woods', reviewed_payload: {}, agent_metadata: {
    review_kind: 'actor_profile', entity_id: 'a1', changes: [
      {review_item_id: 'l', kind: 'fact', field_key: 'location', can_keep_both: true,
        current: {value: {city: 'Stanford', state: 'CA'}}, proposed: {value: {city: 'Palo Alto', state: 'CA'}}},
      {review_item_id: 'r', kind: 'relationship', candidate_name: 'Stanford University',
        relationship_type: 'unit_of', source_url: 'https://woods.stanford.edu/about'},
      {review_item_id: 'h', kind: 'hub', hub_name: 'Bay Area Water Hub',
        evidence: {sector_code: 'WATER', distance_miles: 12}},
    ]}};
  const [location, link, hub] = changeRows(profile);
  assert.deepEqual(location.choices.map(c => c.value), ['keep_current', 'use_new', 'keep_both']);
  assert.equal(link.question, 'Stanford Woods is a unit of Stanford University?');
  assert.deepEqual(link.choices.map(c => c.value), ['refuse', 'confirm']);
  assert.equal(hub.question, 'Add Stanford Woods to Bay Area Water Hub?');
  assert.equal(hub.reason, 'Same sector (WATER); 12 miles from the centre');
});

test('older update results render in the boxes, from what they wrote, with their run', async () => {
  const {lightFactRows, updateRunRows} = await import('../frontend/review.js');
  const legacy = {
    created_at: 1792368000, source_description: 'Actor update: Clean Energy Group',
    reviewed_payload: {actor_category: 'foundation_nonprofit'},
    agent_metadata: {source_table: 'actor_update', run_id: 'r9', run_status: 'succeeded',
      pages_read: ['https://www.cleanegroup.org/'], corroborated: 3,
      written: [
        {fact_key: 'funding_signal', collection_state: 'found', value: 'DOE EERE award',
          previous_value: 'Older grant', lifecycle_state: 'accepted',
          source_url: 'https://www.cleanegroup.org/initiatives/'},
        {fact_key: 'um6p_ocp_connection', collection_state: 'not_found', value: null},
      ]},
  };
  const rows = Object.fromEntries(lightFactRows(legacy).map(row => [row.key, row]));
  assert.equal(rows.funding_signal.value, 'DOE EERE award');
  assert.equal(rows.funding_signal.update.outcome, 'changed');
  assert.equal(rows.um6p_ocp_connection.state, 'Not Found');
  assert.equal(rows.mission_sector_focus.state, 'Not Yet Collected');
  const [run] = updateRunRows(legacy);
  assert.equal(run.title, 'Clean Energy Group');
  assert.equal(run.summary, '1 updated · 3 confirmed · 1 not found');
  assert.deepEqual(run.pages, ['https://www.cleanegroup.org/']);
});

test('the update table is gone: values live in the boxes', () => {
  assert.doesNotMatch(component, /What this update wrote/);
  assert.match(component, /Changes to Review/);
  assert.match(component, /Proposed — Not Yet Approved/);
});

test('other items for the same actor are listed on its card, never merged', async () => {
  const {relatedItems} = await import('../frontend/review.js');
  const profile = {candidate_id: 'p', agent_metadata: {entity_id: 'a1', review_kind: 'actor_profile',
    source_table: 'actor_update', update_runs: [], changes: []}};
  const geocode = {candidate_id: 'g', review_reason: 'geocode_failed', run_label: 'Map checks',
    agent_metadata: {entity_id: 'a1', source_table: 'review_item'}};
  const other = {candidate_id: 'o', agent_metadata: {entity_id: 'a2'}};
  assert.deepEqual(relatedItems([profile, geocode, other], profile).map(item => item.id), ['g']);
  assert.deepEqual(relatedItems([profile, geocode], geocode),
    [{id: 'p', label: 'Organization updates', run: ''}]);
  assert.deepEqual(relatedItems([profile], {candidate_id: 'x', agent_metadata: {}}), []);
});

test('a box shows its change fact by fact, and what an earlier reading supplied', async () => {
  const {partChanges, updateNote, lightFactRows, changeRows, formatFactValue} =
    await import('../frontend/review.js');
  const before = {employees: 500, places: ['Texas']};
  const after = {employees: 600, places: ['Texas'], customers: 2000};
  assert.deepEqual(partChanges(before, after).map(change => change.text),
    ['Employees: 500 → 600', 'Customers: added (2000)']);
  assert.deepEqual(partChanges('A paragraph', after), []);
  assert.match(updateNote({outcome: 'changed', date: 1792368000, previous_value: before}, after),
    /^Updated · .* · Employees: 500 → 600 · Customers: added \(2000\)$/);
  // Only additions: more detail, not a change.
  assert.match(updateNote({outcome: 'changed', previous_value: {employees: 500}},
    {employees: 500, customers: 2000}), /^More detail/);
  // The bookkeeping is never shown as a line of the value.
  assert.equal(formatFactValue({employees: 600, carried_over: ['customers']}), 'Employees: 600');
  const profile = {reviewed_payload: {actor_category: 'company'}, agent_metadata: {
    source_table: 'actor_update', review_kind: 'actor_profile', entity_id: 'a1',
    facts: [{fact_key: 'ownership_and_size', fact_type: 'light_pull', layer: 1,
      collection_state: 'found', value: {employees: 600, ownership: 'private', carried_over: ['ownership']}},
    {fact_key: 'funding_signal', fact_type: 'light_pull', layer: 1, collection_state: 'found',
      value: {amount: '$2M'}, from_sector: 'Water'}],
    changes: [{review_item_id: 'c', kind: 'fact', field_key: 'ownership_and_size',
      current: {value: {employees: 500}}, proposed: {value: {employees: 600}}}]}};
  const rows = Object.fromEntries(lightFactRows(profile).map(row => [row.key, row]));
  assert.deepEqual(rows.ownership_and_size.carriedOver, ['ownership']);
  assert.equal(rows.funding_signal.fromSector, 'Water');
  assert.equal(changeRows(profile)[0].difference, 'Employees: 500 → 600');
});

test('the earlier GHUS profile fills an empty box, and sits beside a box read and not found', async () => {
  const {lightFactRows} = await import('../frontend/review.js');
  const rows = Object.fromEntries(lightFactRows({reviewed_payload: {actor_category: 'company'},
    agent_metadata: {source_table: 'actor_update', review_kind: 'actor_profile', facts: [
      {fact_key: 'funding_signal', fact_type: 'light_pull', layer: 1, collection_state: 'found',
        value: 'Corporate R&D and venture investments', from_record: 'earlier GHUS profile'},
      {fact_key: 'recent_activity', fact_type: 'light_pull', layer: 1, collection_state: 'not_found',
        value: null, record_value: 'Large-scale CCUS projects', update: {outcome: 'not_found'}},
    ]}}).map(row => [row.key, row]));
  assert.equal(rows.funding_signal.fromRecord, 'earlier GHUS profile');
  assert.equal(rows.funding_signal.value, 'Corporate R&D and venture investments');
  // Read and not found stays Not Found; the earlier record is shown beside it.
  assert.equal(rows.recent_activity.state, 'Not Found');
  assert.equal(rows.recent_activity.recordValue, 'Large-scale CCUS projects');
});

test('a box read from another site names that site', async () => {
  const {lightFactRows} = await import('../frontend/review.js');
  const rows = Object.fromEntries(lightFactRows({
    reviewed_payload: {actor_category: 'university_academic', website: 'https://mge.engineering.arizona.edu'},
    agent_metadata: {source_table: 'actor_update', review_kind: 'actor_profile', facts: [
      {fact_key: 'relevant_centers_programs', fact_type: 'light_pull', layer: 1, collection_state: 'found',
        value: {names: ['San Xavier Underground Mining Lab']},
        source_url: 'https://engineering.arizona.edu/majors/mining', confidence: 'medium'},
      {fact_key: 'location', fact_type: 'light_pull', layer: 1, collection_state: 'found',
        value: {city: 'Tucson'}, source_url: 'https://mge.engineering.arizona.edu/contact'},
    ]}}).map(row => [row.key, row]));
  assert.equal(rows.relevant_centers_programs.sourceHost, 'engineering.arizona.edu');
  assert.equal(rows.location.sourceHost, null);       // its own site: just "Source"
});

test('a discovered person or event keeps its checks and page facts as data, not as a box', async () => {
  const {qualityOf, pageFactBoxes, recordRowNote} = await import('../frontend/review.js');
  const person = {entity_type: 'person', agent_metadata: {
    quality: {decision: 'review', completeness: 'incomplete',
      reasons: ['Identified and relevant, but missing: department or unit.'],
      checks: [{name: 'identity', passed: true, detail: 'An official profile names this person.'},
        {name: 'affiliation', passed: false, detail: 'The current affiliation could not be established.'}],
      missing_mandatory: [], missing_priority: ['department or unit'], conflicts: []},
    page_facts: {expertise: ['desalination', 'water reuse'],
      linkedin_url: 'https://www.linkedin.com/in/maria-lopez',
      evidence: {expertise: {quote: 'Research: desalination and water reuse',
        source_url: 'https://cee.example.edu/p', date_read: '2026-10-22T10:00:00+00:00'}}}}};
  const quality = qualityOf(person);
  assert.equal(quality.label, 'Incomplete');
  assert.deepEqual(quality.checks.map(c => [c.name, c.state]),
    [['Identity', 'ok'], ['Current affiliation', 'missing']]);
  const boxes = Object.fromEntries(pageFactBoxes(person).map(b => [b.key, b]));
  assert.equal(boxes.expertise.value, 'desalination, water reuse');
  assert.equal(boxes.expertise.quote, 'Research: desalination and water reuse');
  assert.equal(boxes.expertise.dateRead, '10/22/2026');
  assert.equal(boxes.linkedin_url.link, 'https://www.linkedin.com/in/maria-lopez');
  assert.equal(boxes.department.state, 'Not Found');          // read, not stated
  // The list says what the record is, not how complete the agent judged it.
  assert.equal(recordRowNote(person), 'Person');
  const event = {entity_type: 'event', agent_metadata: {page_facts: {format: 'online', organizer: 'Health AI Alliance'}}};
  const eventBoxes = Object.fromEntries(pageFactBoxes(event).map(b => [b.key, b]));
  assert.equal(eventBoxes.format.value, 'Online');
  assert.equal(eventBoxes.organizer.value, 'Health AI Alliance');
  assert.equal(qualityOf({agent_metadata: {}}), null);
});

test('a person reads what they do; an event its fuller description; no qualification box', async () => {
  const {personDescription} = await import('../frontend/review.js');
  const page = 'https://cee.example.edu/p';
  const bio = {agent_metadata: {page_facts: {bio: 'Maria Lopez joined Rice in 2019.',
    description: 'Maria Lopez is a professor.',
    evidence: {bio: {source_url: page}}}}};
  assert.deepEqual(personDescription(bio),
    {text: 'Maria Lopez joined Rice in 2019.', kind: 'Biography from its page', source: page});
  const summary = {agent_metadata: {page_facts: {description: 'Maria Lopez is a professor.'}}};
  assert.equal(personDescription(summary).kind, 'Summary of its page');
  assert.equal(personDescription({agent_metadata: {}}), null);
  // A person found by Build the Map reads its bio.
  assert.equal(personDescription({agent_metadata: {}, original_payload: {bio: 'Leads grid research.'}}).kind,
    'Biography from Explore and Map');
  // No qualification box, no "read from its page" list, anywhere.
  assert.doesNotMatch(component, /Collected information|collectedBlock|readoutBlock|Read from its page|Not found on its page:/);
  assert.doesNotMatch(component, /review-checks|review-quality/);
  assert.match(component, /personDescription\(selected\)/);
  // An event's description - and any long text - is shown whole.
  assert.match(component, /rows=\$\{Math\.max\(3, textRows\(draft\.description\)\)\}/);
  const {textRows} = await import('../frontend/review.js');
  assert.equal(textRows(''), 2);
  assert.equal(textRows('x'.repeat(400)), 5);
  assert.equal(textRows('a\nb\nc'), 3);
  assert.equal(textRows('x'.repeat(5000)), 24);
});

test('an event and a person read with the names Build the Map uses, filled from its page', async () => {
  const {profileValue} = await import('../frontend/review.js');
  const event = {entity_type: 'event', editable_fields: ['next_date'],
    original_payload: {um6p_ocp_status: 'found', um6p_ocp_detail: 'OCP sponsors it', previous_edition: '2026-03-01'},
    agent_metadata: {sector_codes: [], quality: {why_matched: 'A water reuse summit.'},
      page_facts: {format: 'in_person', organizer: 'National Association of Water Companies (NAWC)',
        event_status: 'scheduled'}}};
  assert.equal(profileValue(event, {}, 'organizer', ['organizer']), 'National Association of Water Companies (NAWC)');
  assert.equal(profileValue(event, {}, 'event_format', ['format']), 'In person');
  assert.equal(profileValue(event, {}, 'date_status', ['event_status']), 'Scheduled');
  assert.equal(profileValue(event, {}, 'match_explanation'), 'A water reuse summit.');
  assert.equal(profileValue(event, {}, '_um6p_ocp', ['um6p_ocp_involvement']), 'Found — OCP sponsors it');
  assert.equal(profileValue(event, {}, 'previous_edition'), '03/01/2026');
  assert.equal(profileValue(event, {event_type: 'conference'}, 'event_type'), 'Conference');
  assert.equal(profileValue(event, {}, 'audience'), null);          // nothing: the row is left out
  // Sponsors is its own row; it is not shown as the organizer.
  assert.match(component, /\["sponsoring_orgs", "Sponsors"\]/);
  assert.match(component, /\["organizer", "Organizer", \["organizer"\]\]/);
  const person = {entity_type: 'person', agent_metadata: {page_facts: {expertise: ['groundwater'],
    work_location: 'Tucson, AZ', relevant_work: ['Indige-FEWSS']}}};
  assert.equal(profileValue(person, {}, 'research_area', ['expertise']), 'groundwater');
  assert.equal(profileValue(person, {}, 'organization_location', ['work_location']), 'Tucson, AZ');
  assert.equal(profileValue(person, {}, 'work_evidence', ['relevant_work']), 'Indige-FEWSS');
});

test('a discovered event shows its outcome, timing and why it matched', async () => {
  const {qualityOf} = await import('../frontend/review.js');
  const q = qualityOf({agent_metadata: {quality: {completeness: 'complete', outcome: 'qualified',
    freshness: 'upcoming', why_matched: 'A water reuse workshop.', checks: []}}});
  assert.equal(q.outcome, 'Qualified for Review');
  assert.equal(q.timing, 'Upcoming');
  assert.equal(q.whyMatched, 'A water reuse workshop.');
});

test('a record stored with its lists as Python text opens instead of crashing the page', async () => {
  const {asList, qualityOf} = await import('../frontend/review.js');
  assert.deepEqual(asList("('Identified and relevant, but missing: department or unit.',)"),
    ['Identified and relevant, but missing: department or unit.']);
  assert.deepEqual(asList("('official source', \"GHUS relevance\")"), ['official source', 'GHUS relevance']);
  // Python writes a value holding an apostrophe in double quotes.
  assert.deepEqual(asList(`("It's cancelled.",)`), ["It's cancelled."]);
  assert.deepEqual(asList('()'), []);
  assert.deepEqual(asList(['a']), ['a']);
  assert.deepEqual(asList(null), []);
  const q = qualityOf({agent_metadata: {quality: {completeness: 'incomplete',
    reasons: "('Missing a date.',)", missing_mandatory: "('confirmed date',)",
    missing_priority: '()', conflicts: '()', checks: [{name: 'identity', passed: true}]}}});
  assert.equal(q.reasons.join(' '), 'Missing a date.');
  assert.deepEqual(q.missing, ['confirmed date']);
  assert.equal(q.checks.length, 1);
});

test('a verified actor is offered a Deep Pull for exactly the sector it was verified for', async () => {
  const {deepPullTarget, deepCostLine, deepResultLine} = await import('../frontend/review.js');
  const verified = {status: 'approved', display_name: 'Acme Water',
    agent_metadata: {source_table: 'review_item', review_kind: 'verify_actor',
      entity_id: 'a1', topic_code: 'WATER'}};
  assert.deepEqual(deepPullTarget(verified),
    {key: 'a1:WATER', actor_id: 'a1', topic: 'WATER', name: 'Acme Water'});
  // Not before the decision, not after a rejection, and never for other kinds.
  assert.equal(deepPullTarget({...verified, status: 'pending_review'}), null);
  assert.equal(deepPullTarget({...verified, status: 'rejected_by_reviewer'}), null);
  assert.equal(deepPullTarget({...verified, agent_metadata: {...verified.agent_metadata,
    review_kind: 'category_doubt'}}), null);
  assert.equal(deepPullTarget({...verified, agent_metadata: {...verified.agent_metadata,
    topic_code: null}}), null);
  // The cost comes from real past reads, or says there are none.
  assert.equal(deepCostLine({cap_usd: 0.15, typical_usd: 0.04}), 'About $0.04; never more than $0.15.');
  assert.equal(deepCostLine({cap_usd: 0.15, typical_usd: null}),
    'No past reads to estimate from; never more than $0.15.');
  assert.equal(deepResultLine({cost_usd: 0.031}, {review_items: 1, results: [
    {written: true, actual: 'new'}, {written: true, actual: 'not_found'},
    {written: true, actual: 'conflict'}, {written: false}]}),
  'Deep Pull done: 2 items found on its pages, 1 not stated (recorded as Not Found), '
    + '1 waiting in Review Results, 1 could not be written. Cost $0.03.');
});

test('bulk category confirmation lists only pending, categorized, non-aggregate category reviews',()=>{
  const row=(id,extra={})=>({candidate_id:id,status:"pending_review",reviewed_payload:{actor_category:"company"},agent_metadata:{review_kind:"category_doubt",pipeline:{}},...extra});
  const rows=[row("a"),row("b",{status:"approved"}),row("c",{agent_metadata:{review_kind:"category_doubt",pipeline:{is_true_aggregate:true}}}),row("d",{reviewed_payload:{actor_category:""}}),row("e",{agent_metadata:{review_kind:"verify_actor",pipeline:{}}})];
  assert.deepEqual(pendingCategoryReviews(rows).map(item=>item.candidate_id),["a"]);
  assert.equal(canConfirmCategories({selectedIds:["a"],reviewer:"GHUS",busy:false,admissionConfigured:true}),true);
  assert.equal(canConfirmCategories({selectedIds:[],reviewer:"GHUS",busy:false,admissionConfigured:true}),false);
  assert.equal(canConfirmCategories({selectedIds:["a"],reviewer:" ",busy:false,admissionConfigured:true}),false);
  assert.equal(canConfirmCategories({selectedIds:["a"],reviewer:"GHUS",busy:false,admissionConfigured:false}),false);
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  assert.match(component,/\/api\/review\/category-decisions/);
});

test('location and relationship reviews have their own validated decisions',()=>{
  const item=(kind)=>({status:"pending_review",agent_metadata:{source_table:"review_item",review_kind:kind}});
  assert.equal(reviewItemKind(item("geocode_failed")),"location");
  assert.equal(reviewItemKind(item("geocode")),"location");
  assert.equal(reviewItemKind(item("relationship_review")),"relationship");
  assert.equal(reviewItemKind(item("verify_actor")),null);
  const base={reviewer:"GHUS",busy:false,admissionConfigured:true};
  assert.equal(canSubmitReviewItem({...base,candidate:item("geocode_failed"),kind:"location",city:"Austin",state:"TX"}),true);
  assert.equal(canSubmitReviewItem({...base,candidate:item("geocode_failed"),kind:"location",city:"Austin",state:""}),false);
  assert.equal(canSubmitReviewItem({...base,candidate:item("geocode_failed"),kind:"location",keepUnlocated:true,notes:""}),false);
  assert.equal(canSubmitReviewItem({...base,candidate:item("geocode_failed"),kind:"location",keepUnlocated:true,notes:"Based in Canada"}),true);
  assert.equal(canSubmitReviewItem({...base,candidate:item("relationship_review"),kind:"relationship",approve:true,sourceUrl:""}),false);
  assert.equal(canSubmitReviewItem({...base,candidate:item("relationship_review"),kind:"relationship",approve:true,sourceUrl:"https://un.org"}),true);
  assert.equal(canSubmitReviewItem({...base,candidate:item("relationship_review"),kind:"relationship",approve:false}),true);
});


test('modern relationship proposals retain their two-way decision workflow',()=>{
  const candidate={status:"pending_review",agent_metadata:{source_table:"review_item",
    review_kind:"relationship_review",pipeline:{proposed_relationship_type:"funded_by",
    source_url:"https://example.org/evidence"}}};
  assert.equal(reviewItemKind(candidate),null);
  assert.equal(twoWayKind(candidate),"relationship");
  assert.equal(canSubmitReview({candidate,reviewer:"Reviewer",decisionKind:"new",
    busy:false,admissionConfigured:true}),true);
});

test('a Build the Map result opens with its labels as the codes the dropdowns hold', async () => {
  const {normalizeMapDraft} = await import('../frontend/review.js');
  assert.deepEqual(normalizeMapDraft(
    {actor_category: 'National Laboratory', category_type: 'Government-Direct', state: 'Colorado'},
    {sector: 'Energy; Government research'}),
  {actor_category: 'national_laboratory', category_type: 'government_direct', state: 'CO',
    primary_sector: 'ENERGY'});
  // Only exact catalog labels change; a reviewer's own sector is never replaced.
  assert.deepEqual(normalizeMapDraft({actor_category: 'company', category_type: 'Weird', state: 'KS',
    primary_sector: 'WATER'}, {sector: 'Energy'}),
  {actor_category: 'company', category_type: 'Weird', state: 'KS', primary_sector: 'WATER'});
});

test('a card line is editable in place only where Review may change it', async () => {
  const {cardField, cardLine} = await import('../frontend/review.js');
  const html = (strings, ...values) => strings.reduce((out, s, i) => out + s + (values[i] ?? ''), '');
  const candidate = {editable_fields: ['next_date', 'location']};
  const date = cardField(html, candidate, 'next_date', '2027-04-02', () => {}, false, null, 'Date');
  assert.match(date, /<b>Date<\/b>/);
  assert.match(date, /value=04\/02\/2027/);
  assert.match(date, /placeholder=MM\/DD\/YYYY/);
  // Not editable here: shown as text, never as an input.
  const audience = cardField(html, candidate, 'audience', 'Utilities', () => {}, false, null, 'Audience');
  assert.doesNotMatch(audience, /<input/);
  assert.match(audience, /Utilities/);
  assert.match(cardLine(html, 'Other names', ''), /Not Found/);
});
