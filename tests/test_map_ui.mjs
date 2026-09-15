// Offline state-transition tests using a tiny hook harness, no browser or API.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const page = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
const script = page.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
// Parse the entire delivered module, including all templates/imports.
new vm.SourceTextModule(script);
const component = script.slice(script.indexOf('function BuildMap(){'), script.indexOf('/* ------------------------------------------------------------------ App */'))
  .replace('const total=all().length;', `const total=all().length;
    globalThis.view={send,stop,restore,reset,poll,refreshRecent,setDesc,extendBudget,continueResearch,
      state:{jobId,cost,res,busy,runStatus,err,msgs}};`);
const cost = {estimated_usd:.05,budget_usd:2,reserved_usd:0,usage_complete:true,can_extend:true,by_stage:{Planning:.05},calls:[]};
const record = (id,status='done') => ({id,status,description:'Saved map '+id,stage:'Complete',
  result:{entities:{actor:[{name:'Sample Lab'}]}},messages:[],cost,error:null});
const reply = value => ({ok:true,json:async()=>value});

function harness(fetcher){
  const hooks=[], storage=new Map(), timers=new Map();
  let cursor=0, nextTimer=1;
  const context = vm.createContext({
    fetch:fetcher,
    useState(initial){const i=cursor++; if(!(i in hooks)) hooks[i]=initial;
      return [hooks[i],value=>{hooks[i]=typeof value==='function'?value(hooks[i]):value;}];},
    useRef(initial){const i=cursor++; if(!(i in hooks)) hooks[i]={current:initial};return hooks[i];},
    useEffect(){cursor++;},
    setTimeout(fn){const id=nextTimer++;timers.set(id,fn);return id;},
    clearTimeout(id){timers.delete(id);},
    localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    html:(strings,...values)=>({strings,values}),
    MGROUPS:[['actor','Organizations','slate'],['person','People','slate'],['event','Events','slate']],
    MDISPLAY_GROUPS:[['actor','Organizations','slate'],['event','Events','slate']],
    AVATAR:'', ICON_SEARCH:'', MapCard(){}, md:()=>({}), ename:e=>e.name||e.full_name,
  });
  vm.runInContext(component,context);
  const render=()=>{cursor=0;context.BuildMap();return context.view;};
  render();
  return {render,context,storage,timers};
}

test('reopening an interrupted map restores results and cost without paid requests',async()=>{
  const requested=[];
  const h=harness(async(url,options)=>{requested.push([url,options]);return reply(record('saved','interrupted'));});
  await h.render().restore('saved');
  const state=h.render().state;
  assert.equal(state.res.entities.actor[0].name,'Sample Lab');
  assert.equal(state.cost.estimated_usd,.05);
  assert.equal(state.runStatus,'interrupted');
  assert.equal(state.busy,false);
  assert.equal(h.storage.get('um6p.mapJobId'),'saved');
  assert.equal(requested.length,1);
  assert.equal(requested[0][1],undefined);
});

test('late response from a previously opened map cannot replace the current map',async()=>{
  let resolveOld;
  const h=harness(url=>url.endsWith('/old')?new Promise(r=>{resolveOld=r;}):Promise.resolve(reply(record('new'))));
  const old=h.render().restore('old');
  await h.render().restore('new');
  resolveOld(reply(record('old')));await old;
  assert.equal(h.render().state.jobId,'new');
});

test('Stop during planning prevents the returned plan from starting research',async()=>{
  let resolvePlan;
  const requests=[];
  const h=harness(async(url,options)=>{
    requests.push(url);
    if(url==='/api/maps') return reply({maps:[],research_available:true});
    if(url==='/api/map/session') return reply({job_id:'test'});
    if(url==='/api/map/chat') return new Promise(resolve=>{resolvePlan=resolve;});
    if(url.endsWith('/stop')) return reply(record('test','cancelled'));
    throw new Error('Unexpected network operation: '+url);
  });
  await h.render().refreshRecent();
  h.render().setDesc('Example');
  const sending=h.render().send();
  // Flush resolved fake session promises; no real timers or network calls.
  for(let i=0;i<10&&!resolvePlan;i++) await Promise.resolve();
  assert.ok(resolvePlan);
  await h.render().stop();
  resolvePlan(reply({status:'plan',job_id:'test',summary:'Example',tasks:[],cost}));
  await sending;
  assert.equal(requests.filter(url=>url==='/api/map').length,0);
  assert.equal(h.render().state.runStatus,'cancelled');
});

test('paused research cannot submit a paid planning call',async()=>{
  const requested=[];
  const h=harness(async(url)=>{requested.push(url);throw new Error('No network expected');});
  h.render().setDesc('Example');
  await h.render().send();
  assert.equal(requested.length,0);
});

test('reset starts a new local view without deleting saved backend data',async()=>{
  const requested=[];
  const h=harness(async(url,options)=>{requested.push([url,options]);return reply(record('saved'));});
  await h.render().restore('saved');
  h.render().reset();
  assert.equal(h.render().state.jobId,null);
  assert.equal(h.storage.has('um6p.mapJobId'),false);
  assert.equal(requested.length,1);
});

test('a failed stale poll cannot overwrite the new map view',async()=>{
  let rejectPoll;
  let gets=0;
  const h=harness(async()=>{
    gets++;
    if(gets===1) return reply(record('saved'));
    return new Promise((_,reject)=>{rejectPoll=reject;});
  });
  await h.render().restore('saved');
  h.render().poll('saved');
  const polling=[...h.timers.values()][0]();
  h.render().reset();
  rejectPoll(new Error('Old connection failed'));
  await polling;
  assert.equal(h.render().state.err,null);
  assert.equal(h.render().state.jobId,null);
});

test('extension needs an explicit action and does not resume research',async()=>{
  const requested=[];
  const h=harness(async(url,options)=>{
    requested.push([url,options]);
    const saved=record('saved','budget_stopped');
    if(url.endsWith('/budget-extension')){
      assert.equal(JSON.parse(options.body).approve,true);
      saved.cost={...cost,budget_usd:3,can_extend:false};
    }
    return reply(saved);
  });
  await h.render().restore('saved');
  assert.equal(requested.length,1);
  await h.render().extendBudget();
  assert.equal(h.render().state.cost.budget_usd,3);
  assert.equal(h.render().state.runStatus,'budget_stopped');
  await h.render().extendBudget();
  assert.equal(requested.length,2);
  assert.equal(requested[1][0],'/api/map/saved/budget-extension');
});

test('late budget approval cannot overwrite a different map view',async()=>{
  let completeApproval;
  const h=harness(async(url)=>{
    if(url.endsWith('/budget-extension')) return new Promise(resolve=>{completeApproval=resolve;});
    return reply(record(url.endsWith('/new')?'new':'old'));
  });
  await h.render().restore('old');
  const approval=h.render().extendBudget();
  await h.render().restore('new');
  completeApproval(reply({...record('old'),cost:{...cost,budget_usd:3,can_extend:false}}));
  await approval;
  assert.equal(h.render().state.jobId,'new');
  assert.equal(h.render().state.cost.budget_usd,2);
});

test('unfinished research continues only after the explicit button action',async()=>{
  const requested=[];
  const saved=record('saved','budget_stopped');
  saved.cost={...cost,can_extend:false,can_resume:true};
  const h=harness(async(url,options)=>{
    requested.push([url,options]);
    if(url==='/api/maps') return reply({maps:[],research_available:true});
    if(url.endsWith('/resume')) return reply({...saved,status:'running',stage:'Continuing saved research'});
    if(url.endsWith('/saved')) return reply(saved);
    return reply(saved);
  });
  await h.render().refreshRecent();
  await h.render().restore('saved');
  assert.equal(requested.filter(([url])=>url.endsWith('/resume')).length,0);
  await h.render().continueResearch();
  const resumes=requested.filter(([url])=>url.endsWith('/resume'));
  assert.equal(resumes.length,1);
  assert.equal(JSON.parse(resumes[0][1].body).approve,true);
});
