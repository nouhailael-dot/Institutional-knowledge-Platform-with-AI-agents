import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';

const page=fs.readFileSync(new URL('../frontend/index.html',import.meta.url),'utf8');
const context=vm.createContext({});
vm.runInContext(page.slice(page.indexOf('function hubLocationKey('),page.indexOf('let existingHubCatalog=')),context);
const match=context.suggestExistingHub;
const actor={city:'Boston',state:'MA',country:'USA'};
const hub={hub_id:'boston',name:'Boston ecosystem',primary_city:'Boston',state:'Massachusetts',country:'United States'};

test('normalizes US country and state aliases',()=>{
  assert.equal(match(actor,[hub]).matches[0].hub_id,'boston');
});
test('does not infer membership from state alone or a nearby city',()=>{
  assert.equal(match({...actor,city:'Cambridge'},[hub]).matches.length,0);
});
test('requires complete US location and rejects conflicting geography',()=>{
  for(const change of [{country:''},{state:''},{city:''},{state:'TX'},{country:'Canada'}])
    assert.equal(match({...actor,...change},[hub]).matches.length,0);
});
test('preserves ambiguity instead of selecting an arbitrary hub',()=>{
  const result=match(actor,[hub,{...hub,hub_id:'second',name:'Second ecosystem'}]);
  assert.equal(result.matches.length,2);
  assert.match(result.reason,/Several/);
});
test('does not mutate the actor or create new hubs',()=>{
  const input=Object.freeze({...actor});
  assert.equal(match(input,[]).matches.length,0);
  assert.deepEqual(input,actor);
});
test('international matching rejects conflicting state and country',()=>{
  const foreign={...hub,primary_city:'Paris',state:'Île-de-France',country:'France'};
  assert.equal(match({city:'Paris',state:'Ile de France',country:'France'},[foreign]).matches.length,1);
  assert.equal(match({city:'Paris',state:'Texas',country:'France'},[foreign]).matches.length,0);
});
