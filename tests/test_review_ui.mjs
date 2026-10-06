import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {
  actorReviewSummary,
  canSubmitReview,
  decisionOptions,
  diffFields,
  editableReviewPayload,
  filterReviewCandidates,
  formatFactValue,
  deepPullFacts,
  lightPullFacts,
  reviewRunLabel,
  reviewStatusLabel,
  reviewFieldLabel,
  validateReviewDraft,
} from '../frontend/review.js';

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
