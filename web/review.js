/* No tokens, paid APIs, analytics, or automatic uploads are used in this page. */
/* Custom drill pages use isolated storage keys and the same audited interaction engine. */
(() => {
  'use strict';
  const DATA = window.REVIEW_DATA;
  const LETTERS = ['A', 'B', 'C', 'D'];
  const PREFIX = DATA.storagePrefix || 'kaoyan.daily.v3.';
  const copy = x => JSON.parse(JSON.stringify(x));
  const app = document.getElementById('app');
  let storageKey = PREFIX + (DATA.storageId || DATA.date);
  let state;
  let started = performance.now();
  let elapsed = 0;
  let active = !document.hidden;
  let storageError = '', memoryOnly = false;
  let questionVisible = false;
  const sources = new Map([...DATA.questions, ...Object.values(DATA.retry || {}).flat()].map(q => [q.id, q]));
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  const byId = id => document.getElementById(id);
  const shuffle = list => {
    const out = list.slice();
    for (let i = out.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [out[i], out[j]] = [out[j], out[i]];
    }
    return out;
  };
  function permuteQuestion(question, answerSlot) {
    const q = copy(question);
    let permutation = shuffle([0, 1, 2, 3]);
    if (answerSlot !== undefined) {
      const old = permutation.indexOf(q.a);
      [permutation[answerSlot], permutation[old]] = [permutation[old], permutation[answerSlot]];
    }
    const remapLetters = text => remapOptionLabels(text, permutation.map(i => LETTERS[i]));
    q.o = permutation.map(i => question.o[i]);
    q.a = permutation.indexOf(question.a);
    q.exp.rest = remapLetters(q.exp.rest);
    q.diag = {};
    permutation.forEach((old, now) => {
      if (question.diag && question.diag[old]) q.diag[now] = remapLetters(question.diag[old]);
    });
    return displayQuestion(q);
  }
  function remapOptionLabels(text, originalAtSlot) {
    // Option labels begin an explanation clause. Paragraph IDs and variables
    // such as 段B/段C or attribute A to B must remain literal.
    return String(text).replace(/(^|[;；。\n])(\s*)([ABCD])(?=[\s.、：:\u4e00-\u9fff])/g,
      (_, boundary, space, letter) => boundary + space + LETTERS[originalAtSlot.indexOf(letter)]);
  }
  function sourceFor(q) {
    const source = sources.get(q.id);
    return source && source.q === q.q && q.o.length === 4 && q.o.every(x => source.o.includes(x)) ? source : null;
  }
  function displayQuestion(question) {
    const source = sourceFor(question);
    if (!source) return question;
    const q = copy(question), originalAtSlot = q.o.map(x => LETTERS[source.o.indexOf(x)]);
    q.exp.rest = remapOptionLabels(source.exp.rest, originalAtSlot);
    q.diag = {};
    Object.entries(source.diag || {}).forEach(([old, text]) => {
      q.diag[q.o.indexOf(source.o[Number(old)])] = remapOptionLabels(text, originalAtSlot);
    });
    return q;
  }
  function notice(text) {
    const node = byId('notice');
    if (node) { node.textContent = text; node.classList.remove('hidden'); }
  }
  function save() {
    if (memoryOnly) { notice(storageError); return; }
    try { localStorage.setItem(storageKey, JSON.stringify(state)); }
    catch (_) { storageError = '浏览器未能保存记录。请保持此页面打开；做完可导出报告，已有记录不会被主动清除。'; notice(storageError); }
  }
  function validState(value) {
    return value?.version === 3 && Array.isArray(value.runs) && value.runs.length &&
      Number.isInteger(value.current) && value.runs[value.current] && value.runs.every(r => r &&
        Array.isArray(r.queue) && r.queue.length && Array.isArray(r.answers) && Number.isInteger(r.index) &&
        typeof r.id === 'string' && ['main','retry'].includes(r.kind) &&
        (!r.parentId || value.runs.some(parent=>parent?.id===r.parentId && parent.kind==='main')) &&
        r.index >= 0 && r.index <= r.queue.length && r.answers.length <= r.queue.length &&
        r.index <= r.answers.length && r.answers.every(a=>a && Number.isInteger(a.pick) &&
          a.pick >= 0 && a.pick < 4 && Number.isInteger(a.expected) && a.expected >= 0 && a.expected < 4 &&
          typeof a.ok === 'boolean' && Number.isFinite(a.ms) && a.ms >= 0) &&
        r.queue.every(q => q && typeof q.id === 'string' && typeof q.family === 'string' && typeof q.q === 'string' &&
          Array.isArray(q.o) && q.o.length === 4 && q.o.every(x=>typeof x==='string') &&
          Number.isInteger(q.a) && q.a >= 0 && q.a < 4 &&
          q.exp && ['trans','structure','other','meaning','rest'].every(k=>typeof q.exp[k]==='string')));
  }
  function restore(key) {
    storageKey = key;
    memoryOnly = false; storageError = '';
    let raw;
    try { raw = localStorage.getItem(key); state = raw ? JSON.parse(raw) : null; }
    catch (_) { state = null; memoryOnly = true; }
    if (!validState(state)) {
      if (raw || memoryOnly) {
        memoryOnly = true;
        storageError = '本地记录无法完整读取，原数据已保留。当前仅临时作答；完成后请导出报告。';
      }
      state = {version: 3, date: DATA.date, runs: [], current: 0};
      createRun('main', DATA.questions, null);
    }
  }
  function current() { return state.runs[state.current]; }
  function rootRun() {
    const run = current();
    return run.parentId ? state.runs.find(x => x.id === run.parentId) : run;
  }
  function createRun(kind, questions, parentId) {
    const slots = shuffle(questions.map((_, i) => i % 4));
    const queue = questions.map((q, i) => permuteQuestion(q, slots[i]));
    const run = {id: Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10), date: state.date,
      kind, parentId, queue, answers: [], index: 0, createdAt: new Date().toISOString()};
    state.runs.push(run);
    state.current = state.runs.length - 1;
    save();
  }
  function button(label, handler, className = '') {
    const b = document.createElement('button');
    b.textContent = label;
    b.className = className;
    b.addEventListener('click', handler);
    return b;
  }
  function paragraph(parent, text, className = '') {
    const p = document.createElement('p');
    p.textContent = text; p.className = className; parent.appendChild(p);
    return p;
  }
  function explanation(parent, q) {
    const box = document.createElement('section'); box.className = 'explanation';
    const fields = [['trans', '1.【整句翻译】'], ['structure', '2.【句子主干】'], ['other', '3.【其他词汇】'], ['meaning', '4.【本题词义】'], ['rest', '5.【其余选项】']];
    fields.forEach(([key, title]) => {
      const h = document.createElement('h3'); h.textContent = title; box.appendChild(h);
      paragraph(box, q.exp[key]);
    });
    parent.appendChild(box);
  }
  function resetClock() {
    const timing = current().timing;
    elapsed = timing?.index === current().index && Number.isFinite(timing.ms) ? Math.max(0, timing.ms) : 0;
    started = performance.now(); questionVisible = true; active = !document.hidden;
  }
  function milliseconds() { return Math.min(3600000, Math.max(0, Math.round(elapsed + (active ? performance.now() - started : 0)))); }
  function checkpoint() {
    const run = state && current();
    if (!questionVisible || !run || run.index >= run.queue.length || run.answers[run.index]) return;
    elapsed = milliseconds(); started = performance.now();
    run.timing = {index: run.index, ms: elapsed}; save();
  }
  document.addEventListener('visibilitychange', () => {
    checkpoint();
    started = performance.now(); active = questionVisible && !document.hidden;
  });
  window.addEventListener('pagehide', checkpoint);
  function shell() {
    app.innerHTML = '<header><h1>' + (DATA.title || '今日定制 · 8题') + '</h1><div id="meta" class="muted"></div><div class="actions"><a class="button" href="./">返回总训练站</a><button id="historyBtn">本地历史记录</button><button id="todayBtn">' + (DATA.progressLabel || '返回本轮进度') + '</button></div></header><p id="notice" class="notice hidden" role="status"></p><section id="body" class="card" aria-live="polite"></section>';
    byId('meta').textContent = DATA.meta || (state.date + ' · 约5–10分钟 · 答题后显示解析 · 刷新保留进度');
    byId('historyBtn').onclick = () => { checkpoint(); historyView(); };
    byId('todayBtn').onclick = () => { checkpoint(); restore(PREFIX + (DATA.storageId || DATA.date)); render(); };
    if (!DATA.ignoreStale && DATA.date < today()) notice('服务器当前题单日期为 ' + DATA.date + '。若今日任务尚未发布，可先保留进度，稍后刷新；不要清空本地记录。');
    if (storageError) notice(storageError);
  }
  function render() {
    shell();
    const run = current();
    if (run.index >= run.queue.length) { finish(); return; }
    const q = displayQuestion(run.queue[run.index]);
    const record = run.answers[run.index];
    if (record) { questionVisible = false; active = false; }
    const body = byId('body');
    paragraph(body, '【本题目标：' + q.target + '】', 'target');
    paragraph(body, (run.kind === 'retry' ? '错题重做' : '主测') + ' · ' + (run.index + 1) + ' / ' + run.queue.length, 'muted');
    if (q.retryOriginal) paragraph(body, '此目标暂时没有另一道经过审核的题，当前重做原题；首次错误仍保留。', 'notice');
    paragraph(body, q.q, 'sentence');
    const choices = document.createElement('div'); choices.className = 'choices';
    q.o.forEach((text, i) => {
      const b = button(LETTERS[i] + '. ' + text, () => answer(i), 'choice');
      if (record) {
        b.disabled = true;
        if (i === q.a) b.classList.add('good');
        if (i === record.pick && !record.ok) b.classList.add('bad');
      }
      choices.appendChild(b);
    });
    body.appendChild(choices);
    if (!record) { resetClock(); return; }
    paragraph(body, record.ok ? '回答正确。' : '本题选了 ' + LETTERS[record.pick] + '，正确答案为 ' + LETTERS[q.a] + '。' + (q.diag?.[record.pick] || ''), record.ok ? 'good' : 'bad');
    paragraph(body, '有效答题时间 ' + (record.ms / 1000).toFixed(1) + ' 秒。用时只是辅助信号，不直接等于不会。', 'muted');
    const actions = document.createElement('div'); actions.className = 'actions';
    actions.appendChild(button(record.uncertain ? '已标记：仍没看懂 / 猜对' : '标记：仍没看懂 / 猜对', () => { record.uncertain = !record.uncertain; save(); render(); }));
    actions.appendChild(button(run.index === run.queue.length - 1 ? '完成本轮' : '下一题', () => { run.index++; save(); render(); }, 'primary'));
    body.appendChild(actions);
    explanation(body, q);
  }
  function answer(pick) {
    const run = current();
    if (run.answers[run.index]) return;
    const q = run.queue[run.index];
    run.answers[run.index] = {qid: q.id, family: q.family, pick, expected: q.a, ok: pick === q.a, ms: milliseconds(), uncertain: false,
      answeredOn: today()};
    delete run.timing;
    questionVisible = false; active = false;
    save(); render();
  }
  function wrongOf(run) { return run.answers.map((r, i) => ({record: r, q: run.queue[i]})).filter(x => !x.record.ok); }
  function retryWrong() {
    const root = rootRun();
    const wrong = wrongOf(root);
    if (!wrong.length) { notice('这次主测没有错题；可以查看解析或全部重做。'); return; }
    const used = new Set(state.runs.filter(r => r.parentId === root.id).flatMap(r => r.queue.map(q => q.id)));
    const questions = wrong.map(({q}) => {
      const candidates = (DATA.retry[q.family] || []).filter(x => x.q !== q.q);
      const fresh = candidates.filter(x => !used.has(x.id));
      if (fresh.length || candidates.length) return copy(shuffle(fresh.length ? fresh : candidates)[0]);
      return {...copy(q), retryOriginal: true};
    });
    createRun('retry', shuffle(questions), root.id); render();
  }
  function wrongView() {
    const root = rootRun(); shell();
    const body = byId('body');
    paragraph(body, '主测错题与解析（重做不会删除这些错误）', 'target');
    const wrong = wrongOf(root);
    if (!wrong.length) paragraph(body, '这次主测没有错题。');
    wrong.forEach(({q, record}) => {
      q = displayQuestion(q);
      const item = document.createElement('article'); item.className = 'review';
      paragraph(item, '【本题目标：' + q.target + '】', 'target');
      paragraph(item, q.q, 'sentence');
      q.o.forEach((text, i) => paragraph(item, LETTERS[i] + '. ' + text));
      paragraph(item, '你选 ' + LETTERS[record.pick] + '；正确答案 ' + LETTERS[q.a] + '。');
      explanation(item, q); body.appendChild(item);
    });
    body.appendChild(button('返回本轮结果', render));
  }
  function report() {
    const root = rootRun();
    return {version: 3, roundId: root.id, date: root.date,
      module: PREFIX === 'kaoyan.article.v1.' ? 'article' : PREFIX === 'kaoyan.passage.v1.' ? 'passage' : 'daily',
      storageId: storageKey.slice(PREFIX.length),
      answers: root.answers.map((r, i) => {
        const q = root.queue[i], source = sourceFor(q);
        return {...r, kind: 'main', ...(source ? {optionOrder: q.o.map(x => source.o.indexOf(x))}
          : {pickText: q.o[r.pick], expectedText: q.o[r.expected]})};
      }),
      retrySummary: state.runs.filter(r => r.parentId === root.id).map(r => ({answered: r.answers.length, correct: r.answers.filter(a => a.ok).length}))};
  }
  function reportText() {
    const root = rootRun(), obj = report();
    const lines = ['<!-- kaoyan-english-training-result -->', (DATA.reportLabel || '考研英语每日复习') + ' ' + root.date,
      '题数 ' + root.answers.length + '｜正确 ' + root.answers.filter(r => r.ok).length,
      '题单日期保留；实际首次作答日期逐题记录，旧记录没有日期时不补造。', '', '【逐题：仅主测用于掌握度】'];
    root.answers.forEach((r, i) => lines.push('Q' + (i + 1) + ' ' + r.family + '：选' + LETTERS[r.pick] + '→正确' + LETTERS[r.expected] + '；' + (r.ok ? '正确' : '错误') + '；' + (r.ms / 1000).toFixed(1) + 's' + (r.uncertain ? '（仍不确定）' : '')));
    lines.push('', '<!-- review-json:v3', JSON.stringify(obj), '-->');
    return lines.join('\n');
  }
  function submit() {
    const root = rootRun();
    const title = '[TRAINING_RESULT] ' + (DATA.reportTitle || '每日复习') + ' ' + root.date + ' ' + root.id;
    const url = 'https://github.com/' + DATA.repo + '/issues/new?title=' + encodeURIComponent(title) + '&body=' + encodeURIComponent(reportText());
    window.open(url, '_blank', 'noopener,noreferrer');
    notice('已打开预填报告。还需在 GitHub 点击 Submit new issue 才算提交；重复提交同一轮不会重复计算。仓库是公开的，报告只含题目表现，不含聊天全文。');
  }
  function exportReport() {
    const blob = new Blob([reportText()], {type: 'text/plain;charset=utf-8'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = (DATA.exportStem || 'english-review') + '-' + state.date + '.txt'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  function finish() {
    const run = current(), root = rootRun(), body = byId('body');
    const correct = run.answers.filter(r => r.ok).length;
    paragraph(body, (run.kind === 'retry' ? '错题重做完成' : '主测完成') + '：' + correct + ' / ' + run.answers.length, 'target');
    paragraph(body, '主测原始错题：' + wrongOf(root).length + ' 道。即时重做不会抹掉首次错误，也不会算作跨日连续答对。');
    const actions = document.createElement('div'); actions.className = 'actions';
    actions.appendChild(button('① 只重做错题', retryWrong));
    actions.appendChild(button('② 查看本轮错题与解析', wrongView));
    actions.appendChild(button('③ 全部重做', () => { createRun('main', shuffle(root.queue), null); render(); }));
    actions.appendChild(button('提交结果到 GitHub', submit, 'primary'));
    actions.appendChild(button('导出本轮报告', exportReport));
    body.appendChild(actions);
    paragraph(body, '下一轮优先：' + (root.answers.filter(r => !r.ok || r.uncertain).map(r => root.queue.find(q => q.id === r.qid)?.target || r.family).join('；') || '继续间隔复习，不因一次答对就认定稳定。'), 'muted');
    paragraph(body, DATA.footer || '网页本地记录不会自动上传。提交到 GitHub 后，服务端会重新计算复习优先级；今天这套题不会中途被替换。', 'muted');
  }
  function historyView() {
    questionVisible = false; active = false;
    shell(); const body = byId('body');
    paragraph(body, '本地历史（包括以前的主测和错题重做）', 'target');
    let keys = [];
    try { keys = Object.keys(localStorage).filter(k => k.startsWith(PREFIX)).sort().reverse(); }
    catch (_) { notice('浏览器暂时无法读取本地历史。'); return; }
    keys.forEach(key => {
      let stored; try { stored = JSON.parse(localStorage.getItem(key)); } catch (_) { return; }
      if (!validState(stored)) return;
      stored.runs.forEach((run, i) => {
        const correct = run.answers.filter(a => a.ok).length;
        const label = stored.date + ' · ' + (run.kind === 'retry' ? '错题重做' : '主测') + ' · ' + correct + '/' + run.answers.length + ' · ' + (run.index >= run.queue.length ? '已完成' : '继续作答');
        const p = document.createElement('p');
        p.appendChild(button(label, () => { restore(key); if (!memoryOnly) state.current = i; save(); render(); })); body.appendChild(p);
      });
    });
  }
  restore(storageKey); render();
})();
