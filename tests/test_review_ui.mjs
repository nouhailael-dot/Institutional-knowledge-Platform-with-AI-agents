import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {
  canSubmitReview,
  decisionOptions,
  diffFields,
  editableReviewPayload,
  filterReviewCandidates,
  reviewStatusLabel,
  validateReviewDraft,
} from '../frontend/review.js';

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
});
