import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';
const page=fs.readFileSync(new URL('../frontend/index.html',import.meta.url),'utf8');
const context=vm.createContext({});
vm.runInContext(page.slice(page.indexOf('function hubLocationKey('),page.indexOf('function PeopleSearch(')),context);
const match=context.regionalHub;
const actor={location_city:'Boston',state:'Massachusetts',country:'United States'};
test('all 50 states and DC have exactly one agreed region',()=>{
 const expected={Northeast:'CT ME MA NH NY RI VT','Mid-Atlantic':'DE MD NJ PA VA WV DC',Southeast:'AL FL GA KY MS NC SC TN','Midwest / Great Lakes':'IL IN IA KS MI MN MO NE ND OH SD WI','South Central / Texas Gulf':'AR LA OK TX','Mountain West / Rocky Mountain':'AZ CO ID MT NV NM UT WY','West Coast / Pacific':'AK CA HI OR WA'};
 const seen=new Set();
 for(const [region,codes] of Object.entries(expected))for(const state of codes.split(' ')){
  assert.equal(seen.has(state),false);seen.add(state);
  assert.equal(match({state,country:'US'}).region,region);
 }
 assert.equal(seen.size,51);
});
test('normalizes full state names and US aliases',()=>{
 for(const country of ['USA','U.S.','U.S.A.','United States of America',' united states '])
  assert.equal(match({...actor,country}).region,'Northeast');
 for(const state of ['Texas',' texas ','TX'])assert.equal(match({...actor,state}).region,'South Central / Texas Gulf');
});
test('city is optional and both city field formats are supported',()=>{
 assert.equal(match({...actor,location_city:'Cambridge'}).region,'Northeast');
 assert.equal(match(actor).city,'Boston');
 assert.equal(match({state:'MA',country:'US',city:'Cambridge'}).city,'Cambridge');
 assert.equal(match({state:'MA',country:'US'}).region,'Northeast');
});
test('DC is Mid-Atlantic while Washington state is Pacific',()=>{
 for(const state of ['District of Columbia','DC','D.C.','Washington, D.C.'])
  assert.equal(match({...actor,state}).region,'Mid-Atlantic');
 assert.equal(match({...actor,state:'Washington'}).region,'West Coast / Pacific');
});
test('missing, non-US, territory and ambiguous locations are not guessed',()=>{
 for(const state of ['',null,'MA / NY','Boston','PR','Ontario'])
  assert.equal(match({...actor,state}).status,'Needs review');
 assert.equal(match({...actor,country:''}).region,null);
 assert.equal(match({...actor,country:'Canada'}).status,'Outside US regions');
});
test('does not mutate records or fetch a hub catalog',()=>{
 const input=Object.freeze({...actor});match(input);assert.deepEqual(input,actor);
 assert.equal(page.includes('loadExistingHubCatalog'),false);
});
