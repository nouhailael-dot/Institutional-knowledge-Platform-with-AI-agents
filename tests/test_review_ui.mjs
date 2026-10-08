import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {
  actorReviewSummary,
  canSubmitReview,
  decisionOptions,
  diffFields,
  editableReviewPayload,
  existingHubMemberships,
  filterReviewCandidates,
  formatFactValue,
  formatReviewRefresh,
  formatReviewTime,
  deepPullFacts,
  hubAssignments,
  hubAssignmentState,
  hubProposalStatuses,
  lightPullFacts,
  latestRunOutcome,
  manualHubOptions,
  reviewRunLabel,
  reviewQueryParams,
  reviewStatusLabel,
  reviewFieldLabel,
  validateReviewDraft,
} from '../frontend/review.js';

test('audit and status All selections reach the backend instead of falling back to Current',()=>{
  const params=reviewQueryParams({inbox:'all',status:'all',entity_type:'all',source_run_id:'',search:'Lab'},true);
  assert.equal(params.get('inbox'),'all');
  assert.equal(params.get('status'),'all');
  assert.equal(params.get('search'),'Lab');
  assert.equal(params.get('refresh'),'true');
});

test('Review uses authoritative human labels and exposes history and diagnostic inboxes',()=>{
  assert.equal(reviewRunLabel({run_label:'Actor Discovery — Oct 6, 2026',source_run_id:'discovery:577bd0bd-263a-43a7-90f8-373f7cab65ae'}),'Actor Discovery — Oct 6, 2026');
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  for(const label of ['Current / latest review','Previous runs / history','All actionable runs','Incomplete discovery records','Development / dry-run diagnostics','Full audit history'])assert.ok(component.includes(label));
});

test('latest run cards present truthful status, results, and an unambiguous refresh time',()=>{
  assert.equal(latestRunOutcome({records_staged:1,queued_for_review:12,records_promoted:13,pending_review:9}),'1 staged · 12 queued for review · 13 promoted · 9 pending now');
  assert.match(formatReviewTime(1791378000),/Oct 7, 2026.*UTC/);
  assert.equal(formatReviewRefresh([]),'Not yet refreshed');
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  for(const text of ['Latest discovery','Real run status','Review data refreshed:','Review decisions are read-only.'])assert.ok(component.includes(text));
  assert.doesNotMatch(component,/Last PostgreSQL sync/);
});

test('review exposes only Layer 1 Light Pull facts with readable states and values',()=>{
  const candidate={agent_metadata:{facts:[
    {fact_type:'light_pull',layer:1,fact_key:'funding_signal',collection_state:'not_found',value:null},
    {fact_type:'classification',layer:1,fact_key:'actor_category_type',value:{actor_category:'company'}},
    {fact_type:'light_pull',layer:2,fact_key:'deep_only',value:'excluded'},
  ]}};
  assert.deepEqual(lightPullFacts(candidate).map(fact=>fact.fact_key),['funding_signal']);
  assert.equal(formatFactValue(null),'No value recorded');
  assert.match(formatFactValue({actor_category:'company'}),/"actor_category": "company"/);
});

test('review separates verified Layer 2 evidence from Light Pull facts',()=>{
  const candidate={agent_metadata:{facts:[
    {fact_type:'light_pull',layer:1,fact_key:'description'},
    {fact_type:'deep_pull',layer:2,fact_key:'relevant_products'},
  ]}};
  assert.deepEqual(deepPullFacts(candidate).map(fact=>fact.fact_key),['relevant_products']);
});

test('actor review separates classification and exposes location without guessing',()=>{
  assert.deepEqual(actorReviewSummary({
    actor_category:'research_center',category_type:'university_center',
    location_city:'Boston',state:'Massachusetts',region:'Northeast',country:'United States',
  }),{
    actor_category:'research_center',category_type:'university_center',city:'Boston',
    state:'Massachusetts',region:'Northeast',country:'United States',legacy_category_fallback:false,
  });
  assert.deepEqual(actorReviewSummary({actor_type:'research institute',state:'MA'}),{
    actor_category:'research institute',category_type:null,city:null,state:'MA',region:null,
    country:null,legacy_category_fallback:true,
  });
  assert.equal(reviewFieldLabel('actor_category'),'Actor Category');
  assert.equal(reviewFieldLabel('category_type'),'Category Type');
  assert.equal(reviewFieldLabel('actor_type'),'Legacy Actor Type (compatibility)');
});

const candidates=[
  {candidate_id:'a',display_name:'Example Lab',entity_type:'actor',status:'pending_review',source_run_id:'run-1',reviewed_payload:{description:'Battery research'}},
  {candidate_id:'p',display_name:'Sam Example',entity_type:'person',status:'approved',source_run_id:'run-1',reviewed_payload:{title:'Director'}},
  {candidate_id:'e',display_name:'Water Summit',entity_type:'event',status:'rejected_by_reviewer',source_run_id:'run-2',reviewed_payload:{location:'Boston'}},
];

test('review filters combine status, entity, source map, and text search',()=>{
  assert.deepEqual(filterReviewCandidates(candidates,{status:'pending_review'}).map(x=>x.candidate_id),['a']);
  assert.deepEqual(filterReviewCandidates(candidates,{entity_type:'person'}).map(x=>x.candidate_id),['p']);
  assert.deepEqual(filterReviewCandidates(candidates,{source_run_id:'run-2'}).map(x=>x.candidate_id),['e']);
  assert.deepEqual(filterReviewCandidates(candidates,{search:'battery'}).map(x=>x.candidate_id),['a']);
  assert.deepEqual(filterReviewCandidates(candidates,{status:'all',entity_type:'event',search:'summit'}).map(x=>x.candidate_id),['e']);
});

test('only API-provided editable fields enter an approval payload',()=>{
  const candidate={editable_fields:['name','description']};
  const payload=editableReviewPayload(candidate,{name:'Reviewed Lab',description:'Reviewed',source_id:'forbidden',_judge:{score:1}});
  assert.deepEqual(payload,{name:'Reviewed Lab',description:'Reviewed'});
});

test('all entity decisions are available and enforce target and fixed rejection reasons',()=>{
  const candidate={status:'pending_review'};
  for(const entity of ['actor','event','person'])assert.deepEqual(decisionOptions(entity).map(x=>x.value),['same_existing','new','reject','defer']);
  assert.equal(canSubmitReview({candidate,reviewer:'R',decisionKind:'new',admissionConfigured:true}),true);
  assert.equal(canSubmitReview({candidate,reviewer:'R',decisionKind:'new',admissionConfigured:false}),false);
  assert.equal(canSubmitReview({candidate,reviewer:'R',decisionKind:'same_existing',targetId:'',admissionConfigured:true}),false);
  assert.equal(canSubmitReview({candidate,reviewer:'R',decisionKind:'same_existing',targetId:'id',admissionConfigured:true}),true);
  assert.equal(canSubmitReview({candidate,reviewer:'R',decisionKind:'reject',rejectionReason:'Outside target geography',admissionConfigured:true}),true);
  assert.equal(canSubmitReview({candidate,reviewer:'R',decisionKind:'reject',rejectionReason:'Other',rejectionOther:'',admissionConfigured:true}),false);
  assert.equal(canSubmitReview({candidate:{status:'approved'},reviewer:'R',decisionKind:'defer',admissionConfigured:true}),false);
});

test('model length validation is inline and match differences are explicit',()=>{
  const candidate={entity_type:'actor',editable_fields:['name'],field_constraints:{name:{max_length:5}}};
  assert.deepEqual(validateReviewDraft(candidate,{name:'123456'}),{name:'Maximum 5 characters.'});
  assert.deepEqual(diffFields({name:'New'},{payload:{name:'Held'}}),[
    {field:'name',candidate:'New',existing:'Held'},
  ]);
});

test('review run labels hide raw discovery UUIDs without changing canonical IDs',()=>{
  const source={
    source_run_id:'discovery:577bd0bd-263a-43a7-90f8-373f7cab65ae',
    source_description:'Open-web actor discovery · dry_run · 577bd0bd-263a-43a7-90f8-373f7cab65ae',
    entity_type:'actor',
  };
  assert.equal(reviewRunLabel(source),'Open-web actor discovery · dry_run');
  assert.equal(source.source_run_id,'discovery:577bd0bd-263a-43a7-90f8-373f7cab65ae');
  assert.equal(reviewRunLabel({description:'discovery:577bd0bd-263a-43a7-90f8-373f7cab65ae'}),'Discovery run');
});

test('normal Review detail hides audit cards while retaining badges, loading, and actions',()=>{
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  assert.doesNotMatch(component,/<dt>Candidate ID<\/dt>/);
  assert.doesNotMatch(component,/<dt>Source run<\/dt>/);
  assert.doesNotMatch(component,/<dt>Created<\/dt>/);
  assert.doesNotMatch(component,/class="review-provenance"/);
  assert.match(component,/reviewStatusLabel\(selected\.status\)/);
  assert.match(component,/DUPLICATE_LABELS\[selected\.duplicate_state\]/);
  assert.match(component,/request\(`\/api\/review\/candidates\/\$\{selectedId\}`\)/);
  assert.match(component,/request\(`\/api\/review\/candidates\/\$\{selected\.candidate_id\}\/decision`/);
  assert.match(component,/Commit decision/);
});

test('hub assignment safely falls back without exposing legacy controls by default',()=>{
  assert.deepEqual(hubAssignments(null),[]);
  assert.deepEqual(existingHubMemberships(null),[]);
  assert.deepEqual(hubProposalStatuses(null),[]);
  assert.deepEqual(hubAssignments({agent_metadata:{hubs:[{hub_id:'legacy-1',name:'Legacy Hub'}]}}),[]);
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  assert.match(component,/No deterministic hub recommendation is available/);
  assert.match(component,/Choose hub manually/);
  assert.doesNotMatch(component,/>Existing hubs</i);
  assert.doesNotMatch(component,/Propose a new hub/i);
  assert.match(component,/proposed_hub:null/);
});

test('backend outcomes drive 199 and 200 mile assignment plus outside and missing-location states',()=>{
  for(const distance of [199,200])assert.equal(hubAssignmentState({
    outcome:'assigned',recommended_hub_id:'hub-ai',distance_miles:distance,radius_miles:200,
    topic_match:true,location_evaluated:true,
  }),'recommended');
  assert.equal(hubAssignmentState({
    outcome:'needs_review_location',recommended_hub_id:'hub-ai',distance_miles:201,
    radius_miles:200,topic_match:true,location_evaluated:true,within_radius:false,
  }),'outside_radius');
  assert.equal(hubAssignmentState({
    outcome:'needs_review_location',topic_match:true,location_evaluated:false,
  }),'missing_location');
  assert.equal(hubAssignmentState({
    outcome:'needs_review_topic',topic_match:false,location_evaluated:true,
  }),'topic_mismatch');
});

test('same-topic overlap preserves the backend nearest recommendation and competing evidence',()=>{
  const [assignment]=hubAssignments({agent_metadata:{hub_assignments:[{
    topic_id:'ai',topic_name:'Artificial Intelligence',outcome:'same_topic_overlap',
    review_kind:'hub_radius_overlap',topic_match:true,location_evaluated:true,
    recommended_hub_id:'bay-ai',recommended_hub_name:'Bay Area AI Hub',
    distance_miles:86,radius_miles:200,
    competing_hubs:[{hub_id:'sac-ai',name:'Sacramento AI Hub',distance_miles:143}],
  }]}});
  assert.equal(assignment.state,'overlap');
  assert.equal(assignment.recommended_hub_id,'bay-ai');
  assert.deepEqual(assignment.competing_hubs.map(hub=>[hub.hub_id,hub.distance_miles]),[['sac-ai',143]]);
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  assert.match(component,/Issue: hub_radius_overlap/);
  assert.match(component,/Multiple qualifying same-topic hubs/);
  assert.ok(component.indexOf('Topic match')<component.indexOf('Location match'));
});

test('multiple topics remain independent and historical memberships stay preserved',()=>{
  const candidate={agent_metadata:{
    hub_assignments:[
      {topic_id:'ai',topic_name:'Artificial Intelligence',outcome:'assigned',recommended_hub_id:'hub-ai'},
      {topic_id:'manufacturing',topic_name:'Advanced Manufacturing',outcome:'assigned',recommended_hub_id:'hub-mfg'},
    ],
    existing_memberships:[{hub_id:'historic',name:'Arizona Water Innovation Hub',topic_name:'Water'}],
  }};
  assert.deepEqual(hubAssignments(candidate).map(row=>[row.topic_id,row.recommended_hub_id]),[
    ['ai','hub-ai'],['manufacturing','hub-mfg'],
  ]);
  assert.equal(existingHubMemberships(candidate)[0].name,'Arizona Water Innovation Hub');
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  assert.match(component,/Existing GHUS membership/);
  assert.match(component,/Preserved historical assignment/);
});

test('manual hub exploration prioritizes topic metadata, preserves IDs, and requires notes',()=>{
  const options=manualHubOptions([
    {hub_id:'other',name:'Alpha Other Hub',topic_id:'water'},
    {hub_id:'match',name:'Zulu AI Hub',topic_id:'ai'},
  ],{topic_id:'ai'},'');
  assert.deepEqual(options.map(hub=>hub.hub_id),['match','other']);
  const candidate={status:'pending_review'};
  assert.equal(canSubmitReview({candidate,reviewer:'R',decisionKind:'new',admissionConfigured:true,manualHubOverride:true,notes:''}),false);
  assert.equal(canSubmitReview({candidate,reviewer:'R',decisionKind:'new',admissionConfigured:true,manualHubOverride:true,notes:'Approved exception.'}),true);
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  assert.match(component,/value=\$\{hub\.hub_id\}/);
  assert.match(component,/Search hubs/);
  assert.match(component,/requires reviewer notes/);
});

test('Phase 7 proposal participation is read-only on actor Review',()=>{
  const candidate={agent_metadata:{hub_proposal_memberships:[{
    proposal_id:'proposal-1',name:'Phoenix Advanced Materials Hub',
    independent_family_count:14,independent_category_count:6,radius_miles:200,
  }]}};
  assert.equal(hubProposalStatuses(candidate)[0].independent_family_count,14);
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  assert.match(component,/Potential new hub detected/i);
  assert.match(component,/No active hub proposal for this actor/);
  assert.match(component,/View hub proposal/);
  assert.doesNotMatch(component,/Approve hub proposal|Create hub/);
});

test('actor decision, reviewer notes, badges, and existing evidence sections remain intact',()=>{
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  for(const text of ['Actor decision','Reviewer and notes','Commit decision','Light Pull evidence','Verified Deep Pull evidence','Sourced relationships','Actor classification and location'])assert.match(component,new RegExp(text));
  assert.match(component,/decisionOptions\(selected\.entity_type\)/);
  assert.match(component,/reviewStatusLabel\(selected\.status\)/);
  assert.match(component,/DUPLICATE_LABELS\[selected\.duplicate_state\]/);
});

test('exact rejected label and mounted Review navigation are present',()=>{
  assert.equal(reviewStatusLabel('rejected_by_reviewer'),'Rejected by reviewer');
  const page=fs.readFileSync(new URL('../frontend/index.html',import.meta.url),'utf8');
  assert.match(page,/\["review","Review","✓"\]/);
  assert.match(page,/display:tab==="review"/);
  const component=fs.readFileSync(new URL('../frontend/review.js',import.meta.url),'utf8');
  assert.match(component,/Top existing matches and differences/);
  assert.match(component,/Refresh now/);
  assert.match(component,/window\.confirm/);
  assert.match(component,/target="_blank" rel="noreferrer"/);
  assert.match(component,/Actor classification and location/);
  assert.match(component,/Category Type is not inferred/);
  assert.match(component,/Sourced relationships/);
  assert.match(component,/Light Pull evidence/);
  assert.match(component,/Verified Deep Pull evidence/);
  assert.match(component,/Not found.*pages read/i);
  assert.match(component,/edge\.relationship_type/);
  assert.match(component,/edge\.source_url/);
  for(const label of ['City','State','Region','Country'])assert.match(component,new RegExp(`<dt>${label}<\\/dt>`));
});
