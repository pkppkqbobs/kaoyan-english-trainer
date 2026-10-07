/* Standalone ordering UI. Only kaoyan.partb.v1.* is read or written. */
(() => {
  'use strict';
  const DATA = window.PARTB_DATA, CORE = window.PARTB_CORE;
  // The mobile QA fixture runs the real UI in memory, never in the learner's storage.
  const PREVIEW = new URLSearchParams(window.location.search).get('preview') === '1';
  const storage = PREVIEW ? Object.defineProperties({}, {
    getItem:{value(key){return this[key]??null;}},
    setItem:{value(key,value){this[key]=value;}}
  }) : localStorage;
  const PREFIX = DATA.storagePrefix, ACTIVE = PREFIX + 'active';
  const app = document.getElementById('partb-app');
  const clone = x => JSON.parse(JSON.stringify(x));
  const byId = id => document.getElementById(id);
  let state, storageKey, storageError='', memoryOnly=false, started = performance.now(), active = !document.hidden;
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const uid = () => 'pb-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2,12);
  const current = () => state.runs[state.current];
  const question = () => DATA.questions.find(q=>q.id===state.question.id) || state.question;
  function el(tag, text, className, parent) {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (className) e.className = className;
    if (parent) parent.appendChild(e);
    return e;
  }
  function button(parent, label, handler, options={}) {
    const b = el('button',label,options.primary?'primary':'',parent);
    if (options.id) b.id = options.id;
    if (options.aria) b.setAttribute('aria-label',options.aria);
    b.disabled = Boolean(options.disabled); b.type='button';
    b.addEventListener('click',handler); return b;
  }
  function link(parent,label,href) { const a=el('a',label,'',parent); a.href=href; return a; }
  function warn(text) { const n=byId('storageNotice'); if(n) {n.textContent=text; n.hidden=false;} }
  function validLocalState(value) {
    try {
      const q=DATA.questions.find(q=>q.id===value?.question?.id);
      if(!q || value.version!==1 || !Array.isArray(value.runs) || !value.runs.length ||
          !Number.isInteger(value.current) || !value.runs[value.current])return false;
      const saved=value.question;
      const signature=q=>JSON.stringify({paragraphs:q.paragraphs.map(p=>[p.id,p.text]),
        expected:q.expectedOrder,links:q.links.map(l=>[l.from,l.to,l.signals,l.anchor])});
      if(signature(saved)!==signature(q) || new Set(value.runs.map(r=>r?.id)).size!==value.runs.length)return false;
      return value.runs.every(r=>{
        if(!r || typeof r.id!=='string' || !r.id || !['main','retry'].includes(r.mode) ||
            !/^\d{4}-\d{2}-\d{2}$/.test(r.date) || new Date(r.date+'T00:00:00Z').toISOString().slice(0,10)!==r.date ||
            !Number.isFinite(r.elapsedMs) || r.elapsedMs<0 ||
            typeof r.uncertain!=='boolean')return false;
        if(r.mode==='retry' ? !value.runs.some(p=>p.id===r.parentId && p.mode==='main' && p.result) : !!r.parentId)return false;
        CORE.validateOrder(q,r.displayOrder);
        if(!Array.isArray(r.pickOrder) || new Set(r.pickOrder).size!==r.pickOrder.length ||
            r.pickOrder.some(id=>typeof id!=='string' || !q.expectedOrder.includes(id)))return false;
        if(r.result!==null && (!r.result || typeof r.result!=='object' || Array.isArray(r.result)))return false;
        if(r.result) {
          CORE.validateOrder(q,r.pickOrder);
          if(!Number.isFinite(r.result.ms) || r.result.ms<0 || r.result.ms>3600000)return false;
        }
        return true;
      });
    }catch(_){return false;}
  }
  function localStates() {
    const found=[];let unreadable=0;
    try {
      for(const key of Object.keys(storage).filter(k=>k.startsWith(PREFIX) && k!==ACTIVE)) {
        try { const value=JSON.parse(storage.getItem(key));
          if(validLocalState(value) && key===PREFIX+value.question.id) found.push({key,value});
          else unreadable++;
        } catch(_) { unreadable++; }
      }
    } catch(_) { warn('浏览器无法读取本地历史，已有记录没有被清除。'); }
    if(unreadable)warn('有 '+unreadable+' 套本地记录无法完整读取，原数据已保留。其他历史仍可查看。');
    return found;
  }
  function save() {
    if(memoryOnly){warn(storageError);return;}
    try {storage.setItem(storageKey,JSON.stringify(state));storage.setItem(ACTIVE,JSON.stringify(question().id));}
    catch(_) {storageError='浏览器未能保存进度。请保持页面打开，完成后导出报告；已有记录不会被主动清除。';warn(storageError);}
  }
  function checkpoint() {
    if(!state || current().result) return;
    if(active) current().elapsedMs += Math.max(0,performance.now()-started);
    started=performance.now(); save();
  }
  document.addEventListener('visibilitychange',()=>{checkpoint();active=!document.hidden;started=performance.now();});
  window.addEventListener('pagehide',checkpoint);
  function newRun(mode='main',parentId=null) {
    const r={id:uid(),date:today(),createdAt:new Date().toISOString(),mode,parentId,
      displayOrder:CORE.shuffle(question().paragraphs.map(p=>p.id)),pickOrder:[],elapsedMs:0,uncertain:false,result:null};
    state.runs.push(r);state.current=state.runs.length-1;started=performance.now();save();
  }
  function load(qid, roundId=null) {
    checkpoint();
    const q=DATA.questions.find(q=>q.id===qid);
    if(!q) throw new Error('没有找到这套排序题。');
    const nextKey=PREFIX+qid;
    let raw,candidate,nextMemoryOnly=false,nextError='';
    try{raw=storage.getItem(nextKey);}catch(_){nextMemoryOnly=true;nextError='浏览器无法读取存储，原记录未被覆盖。当前仅临时作答，完成后请导出报告。';}
    if(raw) {
      try {candidate=JSON.parse(raw);} catch(_) {throw new Error('这套本地记录无法读取，已保留原数据。请换另一套练习。');}
      if(candidate?.question?.id!==qid || !validLocalState(candidate)) {
        throw new Error('这套本地记录格式不完整，已保留原数据。请换另一套练习。');
      }
      if(roundId) {
        const index=candidate.runs.findIndex(r=>r.id===roundId);
        if(index>=0) candidate.current=index;
      }
    } else {
      candidate={version:1,question:clone(q),runs:[],current:0};
      const remote=DATA.results.find(r=>r.qid===qid);
      if(remote) {
        candidate.runs.push({id:remote.roundId,date:remote.date,mode:'main',parentId:null,
          displayOrder:CORE.shuffle(q.paragraphs.map(p=>p.id)),pickOrder:remote.pickOrder.slice(),
          elapsedMs:remote.ms,uncertain:remote.uncertain,result:{...CORE.score(q,remote.pickOrder),ms:remote.ms},restoredFrom:'github'});
        if(!validLocalState(candidate))throw new Error('GitHub首次成绩无法完整恢复，已有记录未被修改。');
      }
    }
    state=candidate;storageKey=nextKey;memoryOnly=nextMemoryOnly;storageError=nextError;
    if(!state.runs.length)newRun();
    started=performance.now();active=!document.hidden;save();
  }
  function header(history=false) {
    app.innerHTML='';
    el('h1',history?'Part B 训练历史':'Part B 段落排序训练','',app);
    el('p','每次一篇 · 5–7段 · 约5–8分钟 · 点击段落编号排序','muted',app);
    const nav=el('nav',undefined,'',app);nav.setAttribute('aria-label','训练导航');
    link(nav,'总训练站','./');link(nav,'每日8题','./today.html');
    link(nav,'排序训练','./partb-review.html');link(nav,'Part B 历史与统计','./partb-history.html');
    const warning=el('p','','notice',app);warning.id='storageNotice';warning.hidden=true;warning.setAttribute('role','status');
    if(storageError)warn(storageError);
    if(PREVIEW)el('p','交互预览：记录仅在内存，不保存或提交训练成绩。','notice',app);
  }
  function selector(parent) {
    const label=el('label','选择文章（全部为新语境）','',parent);label.htmlFor='partbKit';
    const select=el('select',undefined,'',parent);select.id='partbKit';
    DATA.questions.forEach(q=>{const o=el('option',q.topic+' · '+q.title,'',select);o.value=q.id;o.selected=q.id===question().id;});
    select.addEventListener('change',()=>{try{load(select.value);render();}catch(error){select.value=question().id;warn(error.message);}});
  }
  function render() {
    header();const q=question(),r=current();const controls=el('section',undefined,'card',app);selector(controls);
    el('h2',q.title,'',controls);el('p',q.overview,'muted',controls);
    if(r.restoredFrom==='github')el('p','本地没有本套记录，已从GitHub恢复真实首次成绩。原题回顾不计新的掌握证据。','notice',controls);
    if(r.mode==='retry') el('p','原题回顾，不计新的跨日掌握证据。首次提交的顺序与错误仍保留。','notice',controls);
    if(r.result) {resultView(app,q,r);return;}
    const area=el('section',undefined,'card',app);
    el('h2','按你判断的顺序选段','',area);
    el('p','主题相似只是线索；还要核对回指、段尾钩子与全篇走向。先完成排序，提交后再看接缝解析。','muted',area);
    const sequence=el('p',r.pickOrder.length?r.pickOrder.join(' → '):'尚未选段','sequence',area);sequence.id='pickSequence';sequence.setAttribute('aria-live','polite');
    const actions=el('div',undefined,'actions',area);
    button(actions,'撤销最后一步',()=>{checkpoint();r.pickOrder.pop();save();render();focusNext();},{id:'undoOrder',disabled:!r.pickOrder.length});
    button(actions,'清空重排',()=>{checkpoint();r.pickOrder=[];save();render();focusNext();},{id:'clearOrder',disabled:!r.pickOrder.length});
    const label=el('label',undefined,'',area), check=el('input',undefined,'',label);check.type='checkbox';check.id='orderUncertain';check.checked=r.uncertain;
    label.appendChild(document.createTextNode('本轮仍有犹豫 / 猜答'));
    check.addEventListener('change',()=>{checkpoint();r.uncertain=check.checked;save();});
    const list=el('ol',undefined,'paragraphs',area);list.setAttribute('aria-label','打乱的段落');
    r.displayOrder.forEach(id=>{
      const p=q.paragraphs.find(p=>p.id===id),position=r.pickOrder.indexOf(id);
      const item=el('li',undefined,'paragraph-card'+(position>=0?' selected':''),list);
      button(item,position>=0?'段 '+id+' · 已选第'+(position+1)+'位':'选段 '+id,()=>{
        if(r.pickOrder.includes(id)||r.result)return;
        checkpoint();r.pickOrder.push(id);save();render();focusNext();
      },{id:'choose-'+id,aria:'将段'+id+'加入顺序',disabled:position>=0});
      el('p',p.text,'',item);
    });
    const submit=el('div',undefined,'actions',area);
    button(submit,'提交完整顺序',()=>{
      if(r.result)return;
      checkpoint();const computed=CORE.score(q,r.pickOrder);
      r.date=today();r.completedAt=new Date().toISOString();
      r.result={...computed,ms:Math.min(3600000,Math.round(r.elapsedMs))};save();render();byId('resultHeading')?.focus();
    },{id:'submitOrder',primary:true,disabled:r.pickOrder.length!==q.paragraphs.length});
  }
  function focusNext() {
    const next=current().displayOrder.find(id=>!current().pickOrder.includes(id));
    byId(next?'choose-'+next:'submitOrder')?.focus();
  }
  function sequence(parent,label,order) {el('p',label+'：'+order.join(' → '),'sequence',parent);}
  function explain(parent,q,result) {
    const list=el('ol',undefined,'result-pairs',parent);
    q.links.forEach((l,i)=>{
      const hit=result.pairResults[i].ok,item=el('li',undefined,'pair'+(hit?' hit':''),list);
      el('h3',l.from+' → '+l.to+' · '+(hit?'命中':'漏掉')+' · 证据：'+DATA.strengths[l.strength],'',item);
      el('p',l.signals.map(s=>DATA.signals[s]).join(' / ')+(l.anchor?' · 本题锚点':''),'muted',item);
      el('p',l.explanation,'',item);
      const evidence=el('ul',undefined,'',item);
      l.evidence.forEach(e=>el('li',DATA.strengths[e.level]+'证据：'+e.text,'',evidence));
    });
    el('h3','全篇核对','',parent);el('p',q.globalLogic,'screen-note',parent);
    el('h3','为什么主题相似可能误导','',parent);el('p',q.themeTrap,'screen-note',parent);
  }
  function rootRun(r=current()) {return r.parentId?state.runs.find(x=>x.id===r.parentId):r;}
  function reportText() {
    const main=rootRun();
    const obj=CORE.report(main,question(),state.runs.filter(r=>r.parentId===main.id));
    const s=CORE.score(question(),main.pickOrder);
    return ['<!-- kaoyan-english-training-result -->','考研英语 Part B '+main.date,
      '题目 '+question().id,'首次顺序：'+main.pickOrder.join(' → '),
      '标准顺序：'+question().expectedOrder.join(' → '),
      '完整排序：'+(s.fullOrderOk?'正确':'未完全正确')+'｜相邻连接 '+s.pairScore.correct+'/'+s.pairScore.total,
      '用时 '+(main.result.ms/1000).toFixed(1)+'s｜犹豫 '+(main.uncertain?'是':'否'),
      '即时回顾不参与掌握度。','', '<!-- review-json:v4',JSON.stringify(obj),'-->'].join('\n');
  }
  function submitIssue() {
    const main=rootRun(),title='[TRAINING_RESULT] Part B '+main.date+' '+main.id;
    window.open('https://github.com/'+DATA.repo+'/issues/new?title='+encodeURIComponent(title)+'&body='+encodeURIComponent(reportText()),
      '_blank','noopener,noreferrer');
    warn('已打开预填 Issue。你还需在 GitHub 点击 Submit new issue 才会回流；同轮重复提交只计一次。报告只含训练表现。');
  }
  function exportReport() {
    const url=URL.createObjectURL(new Blob([reportText()],{type:'text/plain;charset=utf-8'}));
    const a=el('a');a.href=url;a.download='partb-'+rootRun().date+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function completedQuestions() {
    return new Set([...DATA.results.map(r=>r.qid),
      ...localStates().filter(x=>x.value.runs.some(r=>r.mode==='main'&&r.result)).map(x=>x.value.question.id)]);
  }
  function nextContext() {
    const attempted=completedQuestions();
    const next=DATA.questions.find(q=>q.id!==question().id&&!attempted.has(q.id));
    if(!next) {warn('目前6套新语境都已练过，可选择原题回顾；回顾不计新的掌握证据。');return;}
    load(next.id);render();
  }
  function resultView(parent,q,r,readOnly=false) {
    const s=CORE.score(q,r.pickOrder),box=el('section',undefined,'card',parent);
    const h=el('h2',s.fullOrderOk?'完整排序正确':'先看你命中了哪些接缝','',box);
    if(!readOnly){h.id='resultHeading';h.tabIndex=-1;}
    sequence(box,'你的顺序',r.pickOrder);sequence(box,'标准顺序',q.expectedOrder);
    const stats=el('div',undefined,'stats',box);
    el('p','相邻连接 '+s.pairScore.correct+' / '+s.pairScore.total,'',stats);
    el('p','锚点 '+s.anchorScore.correct+' / '+s.anchorScore.total,'',stats);
    el('p','首段 '+(s.startOk?'正确':'错误')+' · 尾段 '+(s.endOk?'正确':'错误'),'',stats);
    el('p','段落位置 '+s.positionScore.correct+' / '+s.positionScore.total,'',stats);
    el('p','用时 '+((r.result?.ms??r.ms)/1000).toFixed(1)+' 秒 · '+(r.uncertain?'仍有犹豫':'未标犹豫'),'muted',box);
    el('p','漏掉的连接：'+(s.missedPairs.map(p=>p.from+' → '+p.to).join('；')||'无'),'bad',box);
    el('p','错误建立的连接：'+(s.wrongPairs.map(p=>p.from+' → '+p.to).join('；')||'无'),'bad',box);
    if(!readOnly) {
      const actions=el('div',undefined,'actions',box);
      button(actions,'下一篇新语境',nextContext,{primary:true});
      button(actions,'原题回顾（不计掌握）',()=>{const main=rootRun();newRun('retry',main.id);render();});
      button(actions,r.uncertain?'已标记：犹豫 / 猜答':'标记：犹豫 / 猜答',()=>{r.uncertain=!r.uncertain;save();render();});
      if(!PREVIEW) {
        button(actions,'提交首次结果到 GitHub',submitIssue,{id:'submitPartBIssue'});
        button(actions,'导出首次报告',exportReport);
      }
      if(r.mode==='retry') button(actions,'返回首次结果',()=>{state.current=state.runs.indexOf(rootRun());save();render();});
      el('p','即时重做不会覆盖首次结果。优先换一篇语境；原题回顾只用于理解，不计新的跨日掌握。','notice',box);
    }
    explain(box,q,s);
  }
  function historyView() {
    header(true);const all=new Map();
    DATA.results.forEach(r=>all.set(r.roundId,{...r,submitted:true}));
    const locals=localStates(),hist=el('section',undefined,'card',app);el('h2','本地轮次','',hist);
    locals.forEach(({value})=>value.runs.forEach(r=>{
      const p=el('p',undefined,'',hist),s=r.result?CORE.score(value.question,r.pickOrder):null;
      link(p,r.date+' · '+value.question.title+' · '+(r.mode==='main'?'主测':'原题回顾')+' · '+
        (s?'连接 '+s.pairScore.correct+'/'+s.pairScore.total:'未完成，继续排序'),
        './partb-review.html?qid='+encodeURIComponent(value.question.id)+'&round='+encodeURIComponent(r.id));
      if(s&&r.mode==='main') all.set(r.id,{...r,...s,qid:value.question.id,roundId:r.id,ms:r.result.ms,
        submitted:all.get(r.id)?.submitted||false});
    }));
    if(!locals.length)el('p','此浏览器还没有排序记录。旧 daily 和 article 记录不会被迁入这里。','muted',hist);
    const completed=[...all.values()].sort((a,b)=>b.date.localeCompare(a.date)||b.roundId.localeCompare(a.roundId));
    const recent=completed.slice(0,5),summary=el('section',undefined,'card',app);el('h2','最近表现（最多5次主测）','',summary);
    if(!recent.length)el('p','尚无完整排序主测。2011真题的未知选项没有补成成绩。','muted',summary);
    else {
      const hits=recent.reduce((n,r)=>n+r.pairScore.correct,0),total=recent.reduce((n,r)=>n+r.pairScore.total,0);
      el('p','完整排序正确 '+recent.filter(r=>r.fullOrderOk).length+'/'+recent.length+' · 相邻连接正确率 '+Math.round(hits/total*100)+'%','sequence',summary);
      el('p','统计合并本地未提交与GitHub已提交记录，同一roundId只计一次。回顾不参与统计。一个连接可有多个机制标签，机制计数不代表独立作答次数。','muted',summary);
      const table=el('table',undefined,'',summary);table.setAttribute('aria-label','连接机制表现');
      const head=el('tr',undefined,'',table);el('th','机制','',head);el('th','命中 / 连接数','',head);
      Object.keys(DATA.signals).forEach(signal=>{
        const pairs=recent.flatMap(r=>r.pairResults).filter(p=>p.signals.includes(signal));
        if(pairs.length){const tr=el('tr',undefined,'',table);el('td',DATA.signals[signal],'',tr);el('td',pairs.filter(p=>p.ok).length+' / '+pairs.length,'',tr);}
      });
    }
    const remote=el('section',undefined,'card',app);el('h2','GitHub已提交的首次结果','',remote);
    if(!DATA.results.length)el('p','还没有已提交的完整排序成绩。网页本地记录不会自动上传。','muted',remote);
    DATA.results.slice().reverse().forEach(r=>{
      const details=el('details',undefined,'',remote);
      el('summary',r.date+' · '+r.title+' · 连接 '+r.pairScore.correct+'/'+r.pairScore.total+' · Issue #'+r.origin,'',details);
      const q=DATA.questions.find(q=>q.id===r.qid);if(q)resultView(details,q,r,true);
    });
  }
  if(app.dataset.mode==='history') {historyView();return;}
  try {
    const params=new URLSearchParams(window.location.search);
    let preferred;try{preferred=JSON.parse(storage.getItem(ACTIVE));}catch(_){}
    const attempted=completedQuestions();
    const fresh=DATA.questions.find(q=>!attempted.has(q.id));
    const qid=params.get('qid') || (DATA.questions.some(q=>q.id===preferred)?preferred:(fresh||DATA.questions[0]).id);
    load(qid,params.get('round'));render();
  } catch(error) {
    header();el('p',error.message,'notice error',app);
    DATA.questions.forEach(q=>{const p=el('p',undefined,'',app);link(p,'选择 '+q.title,'./partb-review.html?qid='+encodeURIComponent(q.id));});
  }
})();
