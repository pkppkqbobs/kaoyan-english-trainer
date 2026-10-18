import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

// Small DOM harness: exercise the real browser script without adding runtime dependencies.
const storage = {};
Object.defineProperties(storage, {
  getItem: {value(key) { return this[key] ?? null; }},
  setItem: {value(key, value) { this[key] = value; }},
  removeItem: {value(key) { delete this[key]; }}
});
const sessionStore = {
  items: {},
  getItem(key) { return this.items[key] ?? null; },
  setItem(key, value) { this.items[key] = value; },
  removeItem(key) { delete this.items[key]; }
};
const fields = ['trans', 'structure', 'other', 'meaning', 'rest'];
const question = (id, family) => ({id, family, context_id: id, target: family, q: 'Question about ' + id,
  o: ['choice one', 'choice two', 'choice three', 'choice four'], a: 0,
  exp: Object.fromEntries(fields.map(k => [k, id + ': ' + k]))});
const data = {date: '2026-09-29', repo: 'pkppkqbobs/kaoyan-english-trainer',
  questions: Array.from({length: 8}, (_, i) => question('main-' + i, 'family-' + i)), retry: {}};
data.questions.forEach(q => { data.retry[q.family] = [question('retry-' + q.family, q.family)]; });
const dailyQuestionsForAuto = structuredClone(data.questions);
const dailyRetryForAuto = structuredClone(data.retry);
const originalFirst = data.questions[0];
const paragraphReferences = '; 段B位于段C之前。attribute A to B';
originalFirst.exp.rest = 'A alpha; B beta; C gamma; D delta' + paragraphReferences;
originalFirst.diag = {1: 'diagnostic for choice two; 段B位于段C之前', 2: 'diagnostic for choice three', 3: 'diagnostic for choice four'};
const source = fs.readFileSync('web/review.js', 'utf8');
let nodes, opened, clock, pageEvents, documentEvents, simulatedDay, clipboardImpl = null, copiedBeforeOpen = false;
const mockPayloads = new Map(), fetchRequests = [];
const githubIssues = [];
let githubIssueCreates = 0, githubPostedBody = '';
class FixtureDate extends Date {
  constructor(...args) { super(...(args.length ? args : [FixtureDate.now()])); }
  static now() { return Date.parse((simulatedDay || data.date) + 'T12:00:00+08:00'); }
}
class Element {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.listeners = {}; this._text = ''; this.disabled = false; this.style = {};
    const classes = new Set();
    this.classList = {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x)};
  }
  set textContent(text) { this._text = String(text); this.children = []; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join('\n'); }
  set innerHTML(markup) {
    this.children = []; this._text = '';
    for (const match of markup.matchAll(/id="([^"]+)"/g)) {
      const child = new Element(); nodes[match[1]] = child; this.children.push(child);
    }
  }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  click() { if (!this.disabled) (this.onclick || this.listeners.click)?.(); }
}
function boot() {
  nodes = {}; nodes.app = new Element(); opened = '';
  clock = 0; pageEvents = {}; documentEvents = {};
  const document = {hidden: false, getElementById: id => nodes[id], createElement: tag => new Element(tag),
    createTextNode(value) { const node = new Element('text'); node.textContent = value; return node; },
    addEventListener(type, handler) { documentEvents[type] = handler; }};
  const context = {window: {REVIEW_DATA: data,
    navigator: clipboardImpl ? {clipboard: {writeText(value) {
      copiedBeforeOpen = opened === '';
      return clipboardImpl(value);
    }}} : undefined,
    open: url => { opened = url; },
    sessionStorage: sessionStore,
    addEventListener(type, handler) { pageEvents[type] = handler; }}, document, localStorage: storage,
    performance: {now: () => ++clock}, Math, Date: FixtureDate, Intl, JSON, Blob, URL, setTimeout, console,
    fetch: async (path, options={}) => {
      fetchRequests.push(path);
      const repoRoot = 'https://api.github.com/repos/pkppkqbobs/kaoyan-english-trainer/issues';
      if (path === 'https://api.github.com/user') {
        assert.ok(options.headers.Authorization.startsWith('Bearer github_pat_'));
        return {ok:true,status:200,json:async()=>({login:'pkppkqbobs'})};
      }
      if (path.startsWith(repoRoot + '?')) {
        return {ok:true,status:200,json:async()=>structuredClone(githubIssues)};
      }
      if (path.startsWith(repoRoot + '/') && options.method !== 'POST') {
        const id = Number(path.split('/').at(-1));
        const found = githubIssues.find(i=>i.number===id);
        return {ok:!!found,status:found?200:404,json:async()=>structuredClone(found)};
      }
      if (path === repoRoot && options.method === 'POST') {
        githubIssueCreates++;
        const payload=JSON.parse(options.body);
        githubPostedBody=payload.body;
        const issue={number:300+githubIssueCreates,title:payload.title,body:payload.body,
          html_url:'https://github.com/pkppkqbobs/kaoyan-english-trainer/issues/'+(300+githubIssueCreates)};
        githubIssues.push(issue);
        return {ok:true,status:201,json:async()=>structuredClone(issue)};
      }
      return {ok: mockPayloads.has(path), json: async () => structuredClone(mockPayloads.get(path))};
    }};
  vm.runInNewContext(source, context, {timeout: 2000});
}
function allButtons(element = nodes.body) {
  return [element, ...element.children.flatMap(child => allButtons(child))].filter(x => x.tag === 'button');
}
function clickText(text) {
  const b = allButtons().find(x => x.textContent === text);
  assert.ok(b, 'Missing button: ' + text); b.click();
}
function snapshot() { return JSON.parse(storage[(data.storagePrefix || 'kaoyan.daily.v3.') + (data.storageId || data.date)]); }
function run() { const s = snapshot(); return s.runs[s.current]; }
function answer(correct) {
  const r = run(), q = r.queue[r.index];
  const pick = correct ? q.a : (q.a + 1) % 4;
  const b = allButtons().find(x => x.className === 'choice' && x.textContent.startsWith('ABCD'[pick] + '.'));
  assert.ok(b); b.click();
}
boot();
assert.ok(!nodes.body.textContent.includes('1.【整句翻译】'), 'Answers must initially be hidden');
assert.equal(run().queue.length, 8);
assert.deepEqual([0,1,2,3].map(i => run().queue.filter(q => q.a === i).length), [2,2,2,2]);
clock += 20000; pageEvents.pagehide();
const checkpointTime = run().timing.ms;
assert.ok(checkpointTime >= 20000);
boot(); clock += 5000;
simulatedDay = '2026-10-01';
answer(false);
assert.ok(run().answers[0].ms >= 25000, 'refresh must retain active reading time');
assert.equal(run().answers[0].answeredOn, '2026-10-01', 'old paper must record the actual answer day');
simulatedDay = undefined;
assert.ok(nodes.body.textContent.includes('1.【整句翻译】'));
const shuffledFirst = run().queue[0];
const remapped = originalFirst.o.map((_, oldIndex) => 'ABCD'[shuffledFirst.o.indexOf(originalFirst.o[oldIndex])]);
assert.equal(shuffledFirst.exp.rest, remapped.map((letter, i) => letter + ' ' + ['alpha', 'beta', 'gamma', 'delta'][i]).join('; ') + paragraphReferences,
  'option-specific explanation labels must follow the shuffled options');
for (const [oldIndex, diagnostic] of Object.entries(originalFirst.diag)) {
  const currentIndex = shuffledFirst.o.indexOf(originalFirst.o[Number(oldIndex)]);
  assert.equal(shuffledFirst.diag[currentIndex], diagnostic, 'diagnostic must follow the option, not its old index');
}
const firstWrong = run().answers[0];
assert.ok(nodes.body.textContent.includes(shuffledFirst.diag[firstWrong.pick]), 'wrong choice must display its own diagnostic');
boot();
assert.equal(run().answers[0].ok, false, 'Refresh must retain the answer');
clickText('下一题');
for (let i = 1; i < 8; i++) { answer(true); clickText(i === 7 ? '完成本轮' : '下一题'); }
assert.equal(run().answers.filter(x => x.ok).length, 7);
clickText('① 只重做错题');
assert.equal(run().kind, 'retry');
assert.equal(run().queue.length, 1);
assert.ok(run().queue[0].id.startsWith('retry-'));
assert.ok(run().queue[0].exp.trans.startsWith('retry-'), 'Retry must use its own translation');
answer(true); clickText('完成本轮');
assert.equal(snapshot().runs[0].answers[0].ok, false, 'Retry must not erase initial errors');
clickText('② 查看本轮错题与解析');
assert.ok(nodes.body.textContent.includes('Question about main-0'));
clickText('返回本轮结果');
clickText('备用提交：复制报告并打开空白 Issue');
assert.equal(new URL(opened).searchParams.has('body'), false, 'submission URL must not include a long report body');
const body = nodes.body.children.find(x => x.tag === 'textarea' && x.value.includes('<!-- review-json:v3'))?.value;
assert.ok(body, 'full structured report must remain available on page');
const report = JSON.parse(body.match(/<!-- review-json:v3\s*\n(.*?)\n-->/s)[1]);
assert.equal(report.answers.length, 8);
assert.equal(report.answers[0].ok, false);
assert.equal(report.answers[0].pick, firstWrong.pick);
assert.deepEqual(report.answers[0].optionOrder, shuffledFirst.o.map(x=>originalFirst.o.indexOf(x)));
assert.equal(report.answers[0].optionOrder[report.answers[0].expected], originalFirst.a);
assert.equal(report.retrySummary[0].correct, 1);
// A real clipboard request must occur before the new GitHub tab takes focus.
clipboardImpl = value => {
  assert.ok(value.includes('<!-- review-json:v3'));
  return Promise.resolve();
};
boot();
clickText('备用提交：复制报告并打开空白 Issue');
assert.ok(copiedBeforeOpen, 'request clipboard before window.open steals focus');
assert.equal(new URL(opened).searchParams.has('body'), false);
await new Promise(setImmediate);
clipboardImpl = null;
boot();
clickText('备用提交：复制报告并打开空白 Issue');
assert.equal(new URL(opened).searchParams.has('body'), false, 'fallback issue URL must not carry a long body query');
assert.ok(nodes.body.children.some(x => x.tag === 'textarea' && x.value.includes('<!-- review-json:v3')),
  'fallback must expose the full structured report when clipboard is unavailable');
clickText('③ 全部重做');
assert.equal(snapshot().runs.length, 3, 'All-redo must archive previous runs');
assert.equal(run().answers.length, 0);
boot();
assert.equal(snapshot().runs.length, 3);
nodes.historyBtn.click();
assert.ok(nodes.body.textContent.includes('本地历史'));
const dailyKey = 'kaoyan.daily.v3.' + data.date;
const dailySnapshot = storage[dailyKey];
data.storagePrefix = 'kaoyan.passage.v1.';
data.storageId = '2026-09-30-executive-moves';
boot();
assert.ok(storage['kaoyan.passage.v1.2026-09-30-executive-moves'], 'Passage drill must use its own storage namespace');
assert.equal(storage[dailyKey], dailySnapshot, 'Passage drill must not overwrite daily progress');
const passageKey = data.storagePrefix + data.storageId;
const passageSnapshot = storage[passageKey];
const text3 = JSON.parse(fs.readFileSync('data/article-reviews/2026-10-03-2011-text3.json', 'utf8'));
const text4 = JSON.parse(fs.readFileSync('data/article-review.json', 'utf8'));
Object.assign(data, text3);
boot();
answer(true);
const text3Key = data.storagePrefix + data.storageId;
const text3Snapshot = storage[text3Key];
Object.assign(data, text4);
boot();
assert.equal(run().answers.length, 0, 'Text 4 must not restore Text 3 answers');
answer(false);
const articleFirst = run().answers[0];
boot();
assert.deepEqual(run().answers[0], articleFirst, 'Article refresh must retain first choice and shuffled key');
clickText('下一题');
answer(true);
clickText('标记：仍没看懂 / 猜对');
clickText('下一题');
for (let i = 2; i < 8; i++) { answer(true); clickText(i === 7 ? '完成本轮' : '下一题'); }
clickText('① 只重做错题');
assert.equal(run().kind, 'retry');
answer(true); clickText('完成本轮');
assert.equal(snapshot().runs[0].answers[0].ok, false, 'Article retry must preserve the initial error');
clickText('备用提交：复制报告并打开空白 Issue');
assert.equal(new URL(opened).searchParams.has('body'), false, 'article submission must use the short URL');
const articleBody = nodes.body.children.find(x => x.tag === 'textarea' && x.value.includes('<!-- review-json:v3'))?.value;
assert.ok(articleBody, 'full article report must be available for manual paste');
const articleReport = JSON.parse(articleBody.match(/<!-- review-json:v3\s*\n(.*?)\n-->/s)[1]);
assert.equal(articleReport.answers[0].pick, articleFirst.pick);
assert.equal(articleReport.answers[0].expected, articleFirst.expected);
assert.equal(articleReport.answers[0].ok, false);
assert.equal(articleReport.answers[1].uncertain, true);
assert.equal(articleReport.retrySummary[0].correct, 1);
assert.equal(articleReport.answers.length, 8, 'Retry answers are not additional main-test attempts');
assert.equal(storage[text3Key], text3Snapshot);
assert.equal(storage[dailyKey], dailySnapshot);
assert.equal(storage[passageKey], passageSnapshot);
const text4Key = data.storagePrefix + data.storageId;
const text4Snapshot = storage[text4Key];
Object.assign(data, text3); boot();
assert.equal(run().answers.length, 1, 'Archived Text 3 must resume its own progress');
assert.equal(storage[text4Key], text4Snapshot);
Object.assign(data, text4, {storageId: text4.storageId + '-test-next-round'}); boot();
assert.equal(run().answers.length, 0, 'A revised round must use a new isolated key');
assert.equal(storage[text4Key], text4Snapshot, 'New rounds must not overwrite older article rounds');
if (process.env.ARTICLE_TEST_REPORT_PATH) fs.writeFileSync(process.env.ARTICLE_TEST_REPORT_PATH, articleBody);
const damagedKey = data.storagePrefix + data.storageId + '-damaged';
data.storageId += '-damaged'; storage[damagedKey] = 'not valid JSON';
boot();
assert.equal(storage[damagedKey], 'not valid JSON', 'corrupt local records must not be replaced');
allButtons().find(b=>b.className==='choice').click();
assert.equal(storage[damagedKey], 'not valid JSON', 'temporary answers must preserve the unreadable original');
assert.ok(nodes.notice.textContent.includes('原数据已保留'));
for (const corruption of [s=>{s.current=999;}, s=>{s.runs[0].answers[0].ms='invalid';}, s=>{s.runs[0].answers[0]=null;},
  s=>{s.runs[0].answers[0].ok=false;}, s=>{s.runs[0].answers[0].qid='unrelated-question';}]) {
  const saved = JSON.parse(text3Snapshot); corruption(saved);
  const raw = JSON.stringify(saved); storage[damagedKey] = raw;
  boot();
  allButtons().find(b=>b.className==='choice').click();
  assert.equal(storage[damagedKey], raw, 'invalid stored shape must be preserved without crashing');
  nodes.historyBtn.click();
  assert.ok(nodes.body.textContent.includes('本地历史'));
  assert.equal(storage[damagedKey], raw);
}

// Old v3 records did not cache their original retry pool. Restoring one on the
// latest article page must recover its immutable source, not the new article.
const contexts = JSON.parse(fs.readFileSync('data/question-contexts.json', 'utf8')).contexts;
const oldState = JSON.parse(text3Snapshot), oldMain = oldState.runs[0];
delete oldState.retry; delete oldState.meta;
const wrongIndex = oldMain.queue.findIndex(q => !text4.retry[q.family] &&
  text3.retry[q.family]?.some(v => v.id !== q.id && contexts[v.id] !== contexts[q.id]));
assert.ok(wrongIndex >= 0, 'fixture needs an old family absent from the latest sheet');
oldMain.answers = oldMain.queue.map((q, i) => ({qid: q.id, family: q.family,
  pick: i === wrongIndex ? (q.a + 1) % 4 : q.a, expected: q.a, ok: i !== wrongIndex,
  ms: 1000, uncertain: false, answeredOn: text3.date}));
oldMain.index = oldMain.queue.length;
delete oldMain.timing;
const originalAnswers = JSON.stringify(oldMain.answers), oldQuestion = oldMain.queue[wrongIndex];
const oldSourcePath = './data/article-reviews/' + text3.storageId + '.json';
Object.assign(data, text4);
function restoreOld(state) {
  storage[text3Key] = JSON.stringify(state); boot(); nodes.historyBtn.click();
  clickText(text3.date + ' · 主测 · 7/8 · 已完成');
}
mockPayloads.set(oldSourcePath, text3);
mockPayloads.set('./data/question-contexts.json', {contexts});
restoreOld(oldState);
assert.ok(nodes.meta.textContent.includes('历史题单'));
assert.ok(!nodes.meta.textContent.includes('2012'));
const beforeRequests = fetchRequests.length;
clickText('① 只重做错题'); clickText('① 只重做错题');
await new Promise(setImmediate);
let restored = JSON.parse(storage[text3Key]);
assert.equal(restored.runs.length, 2, 'double click while fetching must create only one retry');
assert.equal(fetchRequests.slice(beforeRequests).filter(p=>p===oldSourcePath).length, 1);
const migrated = restored.runs[1].queue[0];
assert.equal(migrated.family, oldQuestion.family);
assert.notEqual(migrated.id, oldQuestion.id);
assert.notEqual(contexts[migrated.id], contexts[oldQuestion.id]);
assert.equal(JSON.stringify(restored.runs[0].answers), originalAnswers);
assert.ok(restored.retry[oldQuestion.family]);
assert.equal(restored.meta, text3.meta);
assert.ok(nodes.meta.textContent.includes('2011'));
assert.ok(!nodes.meta.textContent.includes('2012'));

// A failed fetch must preserve the first result and accurately label the fallback.
mockPayloads.delete(oldSourcePath); restoreOld(oldState);
clickText('① 只重做错题'); await new Promise(setImmediate);
restored = JSON.parse(storage[text3Key]);
assert.equal(restored.runs[1].queue[0].id, oldQuestion.id);
assert.ok(nodes.body.textContent.includes('无法取得这轮的迁移题'));
assert.equal(JSON.stringify(restored.runs[0].answers), originalAnswers);

// A response from another published sheet must not be used for this old round.
mockPayloads.set(oldSourcePath, text4); restoreOld(oldState);
clickText('① 只重做错题'); await new Promise(setImmediate);
restored = JSON.parse(storage[text3Key]);
assert.equal(restored.runs[1].queue[0].id, oldQuestion.id);
assert.equal(JSON.stringify(restored.runs[0].answers), originalAnswers);

// Different IDs in the same curated context are not fresh transfer practice.
const contextState = structuredClone(oldState);
contextState.runs[0].queue[wrongIndex].context_id = 'same-old-context';
const near = {...question('near-copy', oldQuestion.family), context_id: 'same-old-context'};
const fresh = {...question('independent-transfer', oldQuestion.family), context_id: 'different-context'};
contextState.retry = {[oldQuestion.family]: [near, fresh]};
restoreOld(contextState); clickText('① 只重做错题'); await new Promise(setImmediate);
restored = JSON.parse(storage[text3Key]);
assert.equal(restored.runs[1].queue[0].id, fresh.id);
assert.equal(JSON.stringify(restored.runs[0].answers), originalAnswers);
contextState.retry[oldQuestion.family] = [near];
restoreOld(contextState); clickText('① 只重做错题'); await new Promise(setImmediate);
restored = JSON.parse(storage[text3Key]);
assert.equal(restored.runs[1].queue[0].id, oldQuestion.id);
assert.equal(restored.runs[1].queue[0].retryOriginal, true);
assert.equal(JSON.stringify(restored.runs[0].answers), originalAnswers);
assert.equal(storage[dailyKey], dailySnapshot);
assert.equal(storage[passageKey], passageSnapshot);
assert.equal(storage[text4Key], text4Snapshot, 'historical retry must preserve the latest article');

// One-time credential setup: never include PAT in reports or answer storage.
Object.assign(data, {date:'2026-09-29',storagePrefix:'kaoyan.daily.v3.',
  storageId:'2026-09-29',questions:dailyQuestionsForAuto, retry:dailyRetryForAuto,
  repo:'pkppkqbobs/kaoyan-english-trainer'});
boot();
nodes.githubAuthBtn.click();
const authInput=nodes.body.children.find(x=>x.tag==='input' && x.type==='password');
assert.ok(authInput, 'settings must render a masked credential field');
authInput.value='github_pat_minimum_issues_test';
clickText('③ 保存授权并自动同步');
await new Promise(setImmediate);
assert.equal(storage['kaoyan.github.issue-credential.v1.pkppkqbobs/kaoyan-english-trainer'],
  'github_pat_minimum_issues_test', 'opt-in persistence is separate from the training record');
assert.equal(githubIssueCreates,0,'configuring an unfinished quiz must not invent a score');
for(let i=0;i<8;i++) { answer(true); clickText(i===7?'完成本轮':'下一题'); }
await new Promise(setImmediate);
assert.equal(githubIssueCreates,1,'completion must directly create one authenticated Issue');
assert.equal(githubIssues[0].title.startsWith('[TRAINING_RESULT]'),true);
assert.ok(githubPostedBody.includes('<!-- review-json:v3'));
assert.ok(!githubPostedBody.includes('github_pat_'),'secret must never appear in the report');
assert.ok(!JSON.stringify(snapshot()).includes('github_pat_'),'secret must not leak into learning state');
clickText('提交结果到 GitHub');
await new Promise(setImmediate);
assert.equal(githubIssueCreates,1,'repeated clicks must not create duplicate Issues');
boot();
clickText('提交结果到 GitHub');
await new Promise(setImmediate);
assert.equal(githubIssueCreates,1,'reload + retry must verify prior Issue without reposting');
nodes.githubAuthBtn.click();
clickText('移除此浏览器中的 GitHub 授权');
assert.equal(storage['kaoyan.github.issue-credential.v1.pkppkqbobs/kaoyan-english-trainer'],undefined,
  'revocation must remove the local credential');

console.log('UI tests passed: shuffle, paragraph references, refresh/timing, actual answer dates, retry, first errors, verified reports, daily/passage/article isolation, Text 3 -> Text 4, history, damaged-record protection, immutable historical retry recovery, fetch failure, wrong-source rejection, duplicate-click prevention, same-context exclusion.');
