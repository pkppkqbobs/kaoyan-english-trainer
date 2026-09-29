/* No tokens, paid APIs, analytics, or automatic uploads are used in this page. */
(() => {
  'use strict';
  const DATA = window.REVIEW_DATA;
  const LETTERS = ['A', 'B', 'C', 'D'];
  const PREFIX = 'kaoyan.daily.v3.';
  const copy = x => JSON.parse(JSON.stringify(x));
  const app = document.getElementById('app');
  let storageKey = PREFIX + DATA.date;
  let state;
  let started = performance.now();
  let elapsed = 0;
  let active = !document.hidden;
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
    const remapLetters = text => String(text).replace(/\b[ABCD]\b/g, letter => LETTERS[permutation.indexOf(LETTERS.indexOf(letter))]);
    q.o = permutation.map(i => question.o[i]);
    q.a = permutation.indexOf(question.a);
    q.exp.rest = remapLetters(q.exp.rest);
    q.diag = {};
    permutation.forEach((old, now) => {
      if (question.diag && question.diag[old]) q.diag[now] = remapLetters(question.diag[old]);
    });
    return q;
  }
  function notice(text) {
    const node = byId('notice');
    if (node) { node.textContent = text; node.classList.remove('hidden'); }
  }
  function save() {
    try { localStorage.setItem(storageKey, JSON.stringify(state)); }
    catch (_) { notice('浏览器未能保存记录。请保持此页面打开；做完可导出报告，已有记录不会被主动清除。'); }
  }
  function restore(key) {
    storageKey = key;
    try { state = JSON.parse(localStorage.getItem(key)); } catch (_) { state = null; }
    if (!state || state.version !== 3 || !Array.isArray(state.runs) || !state.runs.length) {
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
  function resetClock() { elapsed = 0; started = performance.now(); active = !document.hidden; }
  function milliseconds() { return Math.round(elapsed + (active ? performance.now() - started : 0)); }
  document.addEventListener('visibilitychange', () => {
    if (active) elapsed += performance.now() - started;
    started = performance.now(); active = !document.hidden;
  });
  function shell() {
    app.innerHTML = '<header><h1>今日定制 · 8题</h1><div id="meta" class="muted"></div><div class="actions"><a class="button" href="./">返回总训练站</a><button id="historyBtn">本地历史记录</button><button id="todayBtn">返回今日进度</button></div></header><p id="notice" class="notice hidden" role="status"></p><section id="body" class="card" aria-live="polite"></section>';
    byId('meta').textContent = state.date + ' · 约5–10分钟 · 答题后显示解析 · 刷新保留进度';
    byId('historyBtn').onclick = historyView;
    byId('todayBtn').onclick = () => { restore(PREFIX + DATA.date); render(); };
    const today = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
    if (DATA.date < today) notice('服务器当前题单日期为 ' + DATA.date + '。若今日任务尚未发布，可先保留进度，稍后刷新；不要清空本地记录。');
  }
  function render() {
    shell();
    const run = current();
    if (run.index >= run.queue.length) { finish(); return; }
    const q = run.queue[run.index];
    const record = run.answers[run.index];
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
    run.answers[run.index] = {qid: q.id, family: q.family, pick, expected: q.a, ok: pick === q.a, ms: milliseconds(), uncertain: false};
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
      answers: root.answers.map(r => ({...r, kind: 'main'})),
      retrySummary: state.runs.filter(r => r.parentId === root.id).map(r => ({answered: r.answers.length, correct: r.answers.filter(a => a.ok).length}))};
  }
  function reportText() {
    const root = rootRun(), obj = report();
    const lines = ['<!-- kaoyan-english-training-result -->', '考研英语每日复习 ' + root.date,
      '题数 ' + root.answers.length + '｜正确 ' + root.answers.filter(r => r.ok).length, '', '【逐题：仅主测用于掌握度】'];
    root.answers.forEach((r, i) => lines.push('Q' + (i + 1) + ' ' + r.family + '：选' + LETTERS[r.pick] + '→正确' + LETTERS[r.expected] + '；' + (r.ok ? '正确' : '错误') + '；' + (r.ms / 1000).toFixed(1) + 's' + (r.uncertain ? '（仍不确定）' : '')));
    lines.push('', '<!-- review-json:v3', JSON.stringify(obj), '-->');
    return lines.join('\n');
  }
  function submit() {
    const root = rootRun();
    const title = '[TRAINING_RESULT] 每日复习 ' + root.date + ' ' + root.id;
    const url = 'https://github.com/' + DATA.repo + '/issues/new?title=' + encodeURIComponent(title) + '&body=' + encodeURIComponent(reportText());
    window.open(url, '_blank', 'noopener,noreferrer');
    notice('已打开预填报告。还需在 GitHub 点击 Submit new issue 才算提交；重复提交同一轮不会重复计算。仓库是公开的，报告只含题目表现，不含聊天全文。');
  }
  function exportReport() {
    const blob = new Blob([reportText()], {type: 'text/plain;charset=utf-8'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'english-review-' + state.date + '.txt'; a.click();
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
    paragraph(body, '网页本地记录不会自动上传。提交到 GitHub 后，服务端会重新计算复习优先级；今天这套题不会中途被替换。', 'muted');
  }
  function historyView() {
    shell(); const body = byId('body');
    paragraph(body, '本地历史（包括以前的主测和错题重做）', 'target');
    let keys = [];
    try { keys = Object.keys(localStorage).filter(k => k.startsWith(PREFIX)).sort().reverse(); }
    catch (_) { notice('浏览器暂时无法读取本地历史。'); return; }
    keys.forEach(key => {
      let stored; try { stored = JSON.parse(localStorage.getItem(key)); } catch (_) { return; }
      if (!Array.isArray(stored?.runs)) return;
      stored.runs.forEach((run, i) => {
        const correct = run.answers.filter(a => a.ok).length;
        const label = stored.date + ' · ' + (run.kind === 'retry' ? '错题重做' : '主测') + ' · ' + correct + '/' + run.answers.length + ' · ' + (run.index >= run.queue.length ? '已完成' : '继续作答');
        const p = document.createElement('p');
        p.appendChild(button(label, () => { restore(key); state.current = i; save(); render(); })); body.appendChild(p);
      });
    });
  }
  restore(storageKey); render();
})();
