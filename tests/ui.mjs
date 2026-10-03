import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

// Small DOM harness: exercise the real browser script without adding runtime dependencies.
const storage = {};
Object.defineProperties(storage, {
  getItem: {value(key) { return this[key] ?? null; }},
  setItem: {value(key, value) { this[key] = value; }}
});
const fields = ['trans', 'structure', 'other', 'meaning', 'rest'];
const question = (id, family) => ({id, family, target: family, q: 'Question about ' + id,
  o: ['choice one', 'choice two', 'choice three', 'choice four'], a: 0,
  exp: Object.fromEntries(fields.map(k => [k, id + ': ' + k]))});
const data = {date: '2026-09-29', repo: 'pkppkqbobs/kaoyan-english-trainer',
  questions: Array.from({length: 8}, (_, i) => question('main-' + i, 'family-' + i)), retry: {}};
data.questions.forEach(q => { data.retry[q.family] = [question('retry-' + q.family, q.family)]; });
const originalFirst = data.questions[0];
originalFirst.exp.rest = 'A alpha; B beta; C gamma; D delta';
const source = fs.readFileSync('web/review.js', 'utf8');
let nodes, opened;
class Element {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.listeners = {}; this._text = ''; this.disabled = false;
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
  const document = {hidden: false, getElementById: id => nodes[id], createElement: tag => new Element(tag), addEventListener() {}};
  let clock = 0;
  const context = {window: {REVIEW_DATA: data, open: url => { opened = url; }}, document, localStorage: storage,
    performance: {now: () => ++clock}, Math, Date, Intl, JSON, Blob, URL, setTimeout, console};
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
answer(false);
assert.ok(nodes.body.textContent.includes('1.【整句翻译】'));
const shuffledFirst = run().queue[0];
const remapped = originalFirst.o.map((_, oldIndex) => 'ABCD'[shuffledFirst.o.indexOf(originalFirst.o[oldIndex])]);
assert.equal(shuffledFirst.exp.rest, remapped.map((letter, i) => letter + ' ' + ['alpha', 'beta', 'gamma', 'delta'][i]).join('; '),
  'option-specific explanation labels must follow the shuffled options');
const firstWrong = run().answers[0];
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
clickText('提交结果到 GitHub');
const body = new URL(opened).searchParams.get('body');
const report = JSON.parse(body.match(/<!-- review-json:v3\s*\n(.*?)\n-->/s)[1]);
assert.equal(report.answers.length, 8);
assert.equal(report.answers[0].ok, false);
assert.equal(report.answers[0].pick, firstWrong.pick);
assert.equal(report.retrySummary[0].correct, 1);
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
clickText('提交结果到 GitHub');
const articleBody = new URL(opened).searchParams.get('body');
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
console.log('UI tests passed: shuffle, refresh, retry, first errors, reports, daily/passage/article isolation, Text 3 -> Text 4, revision history.');
