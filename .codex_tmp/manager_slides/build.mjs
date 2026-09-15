import fs from 'node:fs/promises';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
import {resolvePresentationFont,makeNativeBulletParagraphs,finalizePresentation} from '/Users/ghus/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations/container_tools/artifact_tool_utils.mjs';
const root='/Users/ghus/Desktop/um6p-rag', tmp=root+'/.codex_tmp/manager_slides';
const skill='/Users/ghus/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations';
const font=resolvePresentationFont();
const p=Presentation.create({slideSize:{width:1280,height:720}});
const orange='#D7410B',ink='#302D2B',muted='#686461';
function text(s,str,x,y,w,h,size=26,color=ink,bold=false){const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});t.text=str;t.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};return t;}
function bullets(s,items,x,y,w,h,size=25){const t=text(s,'',x,y,w,h,size);t.text=makeNativeBulletParagraphs(items,{marginLeftPoints:16,hangingPoints:9,spaceAfterPoints:10});return t;}
function slide(title,n){const s=p.slides.add();s.background.fill='#FAF9F6';text(s,'UM6P GLOBAL HUBS US',64,27,1000,25,16,orange,true);text(s,title,64,81,1152,86,42,ink,true);text(s,String(n).padStart(2,'0'),1160,672,60,24,16,muted);s.speakerNotes.textFrame.setText('Source: project discussion with Nouhaila and docs/PROJECT_CHANGE_HISTORY.md. Status as discussed in September 2026.');return s;}
function decision(s,str){text(s,str,64,606,1120,55,23,orange,true);}
let s=slide('Platform development',1);
s.background.fill='#2F2D2C';
// Cover uses editable typography on a solid background.
s.shapes.items?.length;
text(s,'Progress and decisions',64,205,1130,100,60,'#FFFFFF',true);
text(s,'Management working session',68,334,1080,45,29,'#D9D4CF');
text(s,'Review progress since our last meeting\nAgree on the outstanding architecture and review decisions\nConfirm next-phase priorities and responsibilities',68,420,1100,155,27,'#FFFFFF');
text(s,'Nouhaila and Ismail',68,628,800,35,22,'#D9D4CF');
// Recolor the cover title for contrast.
s.shapes.items[1].text.style={typeface:font,fontSize:42,color:'#FFFFFF',bold:true,autoFit:'none'};
s=slide('Progress ready to demonstrate',2);
bullets(s,[
'Connected results: organizations display their people, including multiple affiliations.',
'Saved maps: reopen results and partial work, and switch pages without losing the map view.',
'Cost controls: track estimated spending by stage, with a $2 default budget and explicit approval for $3 total.',
'Updated interface: clearer navigation and result cards using UM6P orange.',
'Initial hub suggestions: match existing hub locations or flag assignments for review.'
],64,192,1130,375,28);
text(s,'Spending remains an estimate. Hub suggestions do not create approved database links.',64,607,1100,50,21,muted);
s=slide('Actor architecture: current structure',3);
text(s,'Currently in the Actor table',64,181,600,39,27,orange,true);
text(s,'Supported in related tables',730,181,485,39,27,orange,true);
bullets(s,['Actor name and category','Description and official website','City, state, and country','Primary technical focus and technical approach','Current activities','Technology and IP notes','Key constraints and funding summary','Estimated TRL and primary lifecycle role','Verification status and confidence'],64,232,605,362,23);
bullets(s,['Ecosystem hub and sector/topic relationships','Project/challenge relevance and relevance score','Maturity risk and collaboration orientation','Value for UM6P and partnership entry points','Supporting evidence and sources'],730,232,485,362,23);
decision(s,'Decision: agree on required common fields and category-specific additions.');
s.speakerNotes.textFrame.setText('Source: Database schema.md, documented survey dated 2026-08-05. This slide distinguishes main actor columns from related tables. Existing relationships and fields are not necessarily populated for every actor. Refresh the live schema before treating this as a current database audit. The manager proposed category-specific fields. The user requested removal of the missing/development section.');
s=slide('Build the Map: information for review',4);
text(s,'Suggested information on each result',64,181,650,39,27,orange,true);
bullets(s,['Actor name, category, and location','Short description and relevance to the topic','Potential value for UM6P GHUS','Suggested ecosystem hub','Relevant people and their roles','Official website and supporting sources','Verification status, gaps, and uncertainties'],64,232,635,338,24);
text(s,'Decisions to agree on',764,181,450,39,27,orange,true);
bullets(s,['Is this enough to decide whether to add an actor?','Which details should appear immediately, and which should be expandable?','What must be verified before adding an actor?'],764,232,450,348,26);
decision(s,'Objective: agree on the information users need before accepting an actor.');
s.speakerNotes.textFrame.setText('Source: user-approved proposed slide content. The information list is a proposed review design, not a claim that every listed field is currently available. Database insertion remains unfinished.');
s=slide('Ecosystem hubs and admission criteria',5);
text(s,'Hub mapping',64,181,620,39,27,orange,true);
bullets(s,['Use six dimensions: academic excellence, applied research, industry presence, expert talent, innovation platforms, and global engagement.','Link actors to existing hubs where appropriate.','Propose new hubs when evidence supports a distinct regional ecosystem.'],64,232,620,342,26);
text(s,'Decisions to confirm',754,181,460,39,27,orange,true);
bullets(s,['How do we define hub boundaries?','What evidence supports a new hub?','Who approves hubs and actor membership?','What makes an actor worth adding, including discoveries from Ismail’s agent?'],754,232,460,342,26);
decision(s,'Outcome: agreed admission criteria and approval responsibilities.');
s=slide('Remaining work and next priorities',6);
bullets(s,['Full hub discovery, assessment, and approved database linking.','Verification acceptance testing, batch exclusions, and the database-add workflow.','Explicit geography override and map-completion notifications.','Criteria-based event discovery beyond the original sources.','Existing-person updates and admission criteria for Ismail’s agent.','Later phase: per-user accounts and personal search history.'],64,187,1130,336,27);
text(s,'Proposed sequence',64,531,1100,34,25,orange,true);
text(s,'Agree on schema and admission rules, complete review and database integration,\nthen expand hub mapping and address the remaining features.',64,570,1120,65,24);
text(s,'Meeting outcome: confirmed priorities, owners, and review dates.',64,654,1060,30,21,orange,true);
await (await PresentationFile.exportPptx(p)).save(tmp+'/candidate.pptx');
for(let i=0;i<p.slides.items.length;i++){const img=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(tmp+`/slide-${i+1}.png`,new Uint8Array(await img.arrayBuffer()));}
const result=await finalizePresentation({workspaceDir:root,candidatePath:tmp+'/candidate.pptx',finalPath:root+'/outputs/manager_meeting/Platform_Progress_and_Decisions.pptx',pythonExecutable:'/Users/ghus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],explicitTotalSlideCount:6,fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,receiptPath:tmp+'/validation.json'});
console.log(result);
