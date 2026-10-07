import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const core=require('../web/partb-core.js');
const questions=JSON.parse(fs.readFileSync('data/partb-questions/2026-10-04-transfer.json','utf8')).sort((a,b)=>a.id.localeCompare(b.id));
const data={schema:1,repo:'pkppkqbobs/kaoyan-english-trainer',storagePrefix:'kaoyan.partb.v1.',questions,results:[],
  signals:{anaphora:'回指','lexical-chain':'词汇复现','synonym-chain':'同义复现','problem-to-reason':'问题→原因',
    'cause-effect':'因果','general-to-specific':'概括→具体',example:'举例',parallel:'平行',contrast:'转折',
    conclusion:'收束','topic-introduction':'主题引入','paragraph-end-hook':'段尾钩子'},
  strengths:{strong:'强',medium:'中',support:'辅助'}};
const protectedKeys=['kaoyan.daily.v3.2026-10-04','kaoyan.article.v1.2026-10-03-2011-text4',
  'kaoyan.passage.v1.2026-09-30-executive-moves'];
const storage=Object.fromEntries(protectedKeys.map(k=>[k,JSON.stringify({original:'untouched'})]));
const reads=[];
Object.defineProperties(storage,{
  getItem:{value(k){reads.push(k);return this[k]??null;}},
  setItem:{value(k,v){this[k]=v;}}
});
let nodes,opened='',clock=0,focused,documentEvents,windowEvents;
let activeStorage=storage;
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.attrs={};this.dataset={};this.disabled=false;this._text='';}
  set id(value){this._id=value;nodes[value]=this;}get id(){return this._id;}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join('\n');}
  set innerHTML(value){assert.equal(value,'');this._text='';this.children=[];}
  appendChild(c){this.children.push(c);return c;}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,fn){this.listeners[k]=fn;}
  click(){if(!this.disabled)this.listeners.click?.();}
  focus(){focused=this;}
}
let wallDate='2026-10-04T13:10:00Z';
class TestDate extends Date {constructor(...args){super(...(args.length?args:[wallDate]));}static now(){return 1791119400000+clock;}}
let counter=0;
const random=()=>((++counter*37)%97)/97;
const source=fs.readFileSync('web/partb.js','utf8');
function boot(mode='review',search='',store=storage){
  activeStorage=store;
  nodes={};nodes['partb-app']=new Element();nodes['partb-app'].dataset.mode=mode;
  documentEvents={};windowEvents={};focused=null;opened='';
  const document={hidden:false,getElementById:id=>nodes[id],createElement:tag=>new Element(tag),
    createTextNode:text=>{const e=new Element('text');e.textContent=text;return e;},
    addEventListener:(event,fn)=>{documentEvents[event]=fn;}};
  const window={PARTB_DATA:data,PARTB_CORE:core,location:{search},open:u=>{opened=u;},
    addEventListener:(event,fn)=>{windowEvents[event]=fn;}};
  vm.runInNewContext(source,{window,document,localStorage:store,performance:{now:()=>clock+=100},
    Math:Object.create(Math,{random:{value:random}}),Date:TestDate,Intl,JSON,Blob,URL,URLSearchParams,setTimeout,console});
}
function all(element=nodes['partb-app']){return [element,...element.children.flatMap(c=>all(c))];}
function click(text){const b=all().find(e=>e.tag==='button'&&e.textContent===text);assert.ok(b,'Missing button: '+text);b.click();}
const currentState=(qid=questions[0].id)=>JSON.parse(activeStorage[data.storagePrefix+qid]);
const run=(qid=questions[0].id)=>{const s=currentState(qid);return s.runs[s.current];};
function choose(id){const b=nodes['choose-'+id];assert.ok(b);b.click();}
function finish(order){order.forEach(choose);nodes.submitOrder.click();}
boot();
assert.ok(nodes.submitOrder.disabled,'Cannot submit a missing paragraph');
assert.ok(!nodes['partb-app'].textContent.includes(questions[0].globalLogic),'Explanation must stay hidden initially');
const shuffled=run().displayOrder.slice();
choose(shuffled[0]);choose(shuffled[1]);
assert.ok(nodes['choose-'+shuffled[0]].disabled);
assert.equal(focused.id,'choose-'+shuffled[2],'Click advances keyboard focus');
windowEvents.pagehide();const elapsed=run().elapsedMs;
boot();
assert.deepEqual(run().pickOrder,shuffled.slice(0,2),'Refresh retains current ordering');
assert.deepEqual(run().displayOrder,shuffled,'Refresh must not reshuffle paragraphs');
assert.ok(run().elapsedMs>=elapsed);
nodes.undoOrder.click();assert.equal(run().pickOrder.length,1);
nodes.clearOrder.click();assert.equal(run().pickOrder.length,0);
nodes.orderUncertain.checked=true;nodes.orderUncertain.listeners.change();
assert.ok(run().uncertain);
const q=questions[0];
finish(q.expectedOrder.slice().reverse());
const first=structuredClone(run());assert.equal(first.result.fullOrderOk,false);
assert.equal(first.result.pairScore.correct,0);
assert.ok(nodes['partb-app'].textContent.includes('错误建立的连接'));
assert.ok(nodes['partb-app'].textContent.includes(q.globalLogic));
click('原题回顾（不计掌握）');
assert.equal(run().mode,'retry');
assert.ok(nodes['partb-app'].textContent.includes('不计新的跨日掌握'));
finish(q.expectedOrder);
assert.equal(run().result.fullOrderOk,true);
assert.deepEqual(currentState().runs[0].pickOrder,first.pickOrder,'Retry must not overwrite first result');
click('提交首次结果到 GitHub');
const body=new URL(opened).searchParams.get('body');
const obj=JSON.parse(body.match(/<!-- review-json:v4\s*\n(.*?)\n-->/s)[1]);
assert.deepEqual(obj.answers[0].pickOrder,first.pickOrder);
assert.equal(obj.answers[0].mode,'main');assert.equal(obj.answers[1].mode,'retry');
assert.equal(obj.answers[0].ok,false);assert.ok(obj.answers[0].uncertain);
assert.equal(obj.answers[0].ms,first.result.ms);
const old=storage[data.storagePrefix+q.id];
click('下一篇新语境');
const activeId=JSON.parse(storage[data.storagePrefix+'active']);
assert.notEqual(activeId,q.id,'Prefer a different passage');
assert.equal(storage[data.storagePrefix+q.id],old,'New context must preserve earlier rounds');
const second=questions.find(q=>q.id===activeId);
// Native button semantics make Enter/Space operable; no drag-only or pointer-only widget.
assert.equal(nodes['choose-'+second.expectedOrder[0]].tag,'button');
nodes['choose-'+second.expectedOrder[0]].focus();
focused.click(); // browser's default Enter/Space activation
assert.equal(run(activeId).pickOrder[0],second.expectedOrder[0]);
assert.equal(focused.id,'choose-'+run(activeId).displayOrder.find(x=>x!==second.expectedOrder[0]));
boot('history');
assert.ok(nodes['partb-app'].textContent.includes('相邻连接正确率 0%'));
const restoreLink=all().find(e=>e.tag==='a'&&e.href?.includes('round='+first.id));assert.ok(restoreLink);
const query=new URL(restoreLink.href,'https://example.test/').search;
boot('review',query);assert.equal(run().id,first.id,'Historical main round can be restored');
assert.equal(run().result.fullOrderOk,false);
assert.ok(nodes['partb-app'].textContent.includes('证据：'));
// Client and script scoring agree for every permutation of a six-paragraph fixture.
function permutations(xs){if(!xs.length)return [[]];return xs.flatMap((x,i)=>permutations(xs.filter((_,j)=>j!==i)).map(rest=>[x,...rest]));}
for(const order of permutations(q.expectedOrder)){
  const s=core.score(q,order),hit=q.links.filter(l=>order.some((x,i)=>x===l.from&&order[i+1]===l.to)).length;
  assert.equal(s.pairScore.correct,hit);
  assert.equal(s.missedPairs.length+s.hitPairs.length,q.links.length);
  assert.equal(s.wrongPairs.length,q.links.length-hit);
}
for(const pick of ['ABCDEF',null,[],q.expectedOrder.concat('Z'),q.expectedOrder.map(()=>q.expectedOrder[0])]){
  assert.throws(()=>core.score(q,pick));
}
for(const key of protectedKeys)assert.equal(storage[key],JSON.stringify({original:'untouched'}),'Unrelated progress must stay intact');
assert.ok(reads.every(k=>k.startsWith(data.storagePrefix)),'Part B must not read daily/article/passage data');
// Malformed storage must not be overwritten when a user tries another kit.
storage[data.storagePrefix+questions.at(-1).id]='{bad-json';
nodes.partbKit.value=questions.at(-1).id;nodes.partbKit.listeners.change();
assert.equal(storage[data.storagePrefix+questions.at(-1).id],'{bad-json');
click('已标记：犹豫 / 猜答');
assert.equal(storage[data.storagePrefix+questions.at(-1).id],'{bad-json','A later save must not destroy the unreadable kit');
const beforePreview=JSON.stringify(storage);
boot('review','?preview=1');
finish(q.expectedOrder);
assert.ok(nodes['partb-app'].textContent.includes('完整排序正确'));
assert.ok(nodes['partb-app'].textContent.includes('记录仅在内存'));
assert.ok(!all().some(e=>e.id==='submitPartBIssue'),'Preview cannot submit a fabricated performance');
assert.equal(JSON.stringify(storage),beforePreview,'Mobile preview must not write any learner record');
boot('review','?qid='+second.id);
assert.equal(run(second.id).date,'2026-10-04');
wallDate='2026-10-05T01:00:00Z';
finish(second.expectedOrder.slice(1));
assert.equal(run(second.id).date,'2026-10-05','An overnight unfinished passage belongs to its first submission day');
assert.equal(currentState(q.id).runs[0].date,'2026-10-04','Later context must not redate the first result');
wallDate='2026-10-04T13:10:00Z';
const homeSource=fs.readFileSync('web/partb-home.js','utf8');
async function homeCheck(recommend,as_of) {
  const node={hidden:true,textContent:''};
  const immutableDaily=JSON.stringify({date:'2026-10-04',ids:['locked-1','locked-2']});
  const forbidden=new Proxy({}, {get(){throw new Error('Home suggestion must not touch learner storage');}});
  vm.runInNewContext(homeSource,{document:{getElementById:id=>{assert.equal(id,'partbSuggestion');return node;}},
    fetch:(url)=>{assert.equal(url,'./data/partb-recommendation.json');return Promise.resolve({ok:true,json:()=>({recommend,as_of})});},
    Date:TestDate,Intl,localStorage:forbidden});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(immutableDaily,JSON.stringify({date:'2026-10-04',ids:['locked-1','locked-2']}));
  return node;
}
assert.equal((await homeCheck(true,'2026-10-04')).textContent,'今日建议加练：Part B 排序 1 篇');
assert.equal((await homeCheck(false,'2026-10-04')).hidden,true);
assert.ok((await homeCheck(true,'2026-10-03')).textContent.includes('2026-10-03'));
// One damaged kit must not crash history, mutate raw bytes, or hide healthy kits.
const damagedKey=data.storagePrefix+q.id, healthy=storage[damagedKey];
for(const corrupt of [
  s=>{s.runs[0].pickOrder=[];}, s=>{s.runs[0].displayOrder[1]=s.runs[0].displayOrder[0];},
  s=>{s.runs[0].elapsedMs='1200';}, s=>{s.runs[1].parentId='missing-parent';},
  s=>{s.question.expectedOrder.reverse();}, s=>{s.runs[0].result=0;}, s=>{s.runs[0].date='2026-99-99';}
]) {
  const invalid=JSON.parse(healthy);corrupt(invalid);
  const raw=JSON.stringify(invalid);storage[damagedKey]=raw;
  boot('history');
  assert.ok(nodes['partb-app'].textContent.includes('原数据已保留'));
  assert.ok(nodes['partb-app'].textContent.includes(second.title),'Healthy history remains available');
  assert.equal(storage[damagedKey],raw);
  boot('review','?qid='+q.id);
  assert.ok(nodes['partb-app'].textContent.includes('本地记录格式不完整'));
  windowEvents.pagehide();assert.equal(storage[damagedKey],raw,'Unreadable kit cannot be overwritten after pagehide');
}
storage[damagedKey]=healthy;
function isolatedStore(items={},getError=null) {
  const store={...items};
  Object.defineProperties(store,{getItem:{value(k){if(getError?.(k))throw Error('read blocked');return this[k]??null;}},
    setItem:{value(k,v){this[k]=v;}}});
  return store;
}
const blockedStore=isolatedStore({[damagedKey]:healthy,[data.storagePrefix+'active']:JSON.stringify(q.id)},()=>true);
const blockedBefore=JSON.stringify(blockedStore);
boot('review','?qid='+q.id,blockedStore);choose(q.expectedOrder[0]);windowEvents.pagehide();
assert.equal(JSON.stringify(blockedStore),blockedBefore,'Blocked reads must never replace potentially existing records');
assert.ok(nodes['partb-app'].textContent.includes('当前仅临时作答'));
// Restoring remote first results must not create a new main attempt on a new browser.
const remote=r=>({...core.score(r,r.expectedOrder),qid:r.id,title:r.title,date:'2026-10-04',
  roundId:'pb-remote-'+r.id,pickOrder:r.expectedOrder.slice(),expectedOrder:r.expectedOrder.slice(),ms:120000,uncertain:false,origin:900});
data.results=[remote(q),remote(questions[1])];
const freshBrowser=isolatedStore();
boot('review','?qid='+q.id,freshBrowser);
assert.equal(run(q.id).id,data.results[0].roundId);
assert.equal(run(q.id).result.fullOrderOk,true);
assert.equal(currentState(q.id).runs.length,1);
assert.ok(nodes['partb-app'].textContent.includes('恢复真实首次成绩'));
click('原题回顾（不计掌握）');finish(q.expectedOrder);
click('提交首次结果到 GitHub');
const restoredReport=JSON.parse(new URL(opened).searchParams.get('body').match(/<!-- review-json:v4\s*\n(.*?)\n-->/s)[1]);
assert.equal(restoredReport.roundId,data.results[0].roundId);
assert.equal(restoredReport.date,'2026-10-04');
assert.equal(restoredReport.answers[0].ms,120000);
click('下一篇新语境');
assert.equal(JSON.parse(freshBrowser[data.storagePrefix+'active']),questions[2].id,'Remote completed kits are excluded from fresh context selection');
boot('review','',isolatedStore());
assert.equal(nodes.partbKit.children.find(o=>o.selected).value,questions[2].id,'New browser starts with a truly unseen kit');
data.results=[];
boot('history');
assert.equal(storage[damagedKey],healthy,'Remote restoration cannot modify existing local first results');
if(process.argv.includes('--report'))process.stdout.write(JSON.stringify(obj));
else console.log('Part B UI passed: shuffle, partial refresh, first result/retry, verified remote recovery, local/remote fresh context spacing, damaged-history isolation, blocked-read protection, keyboard focus, isolated storage, 720 permutations.');
