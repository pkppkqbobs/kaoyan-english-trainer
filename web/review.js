/* Opt-in, least-privilege GitHub Issues upload; no tokens in page source or reports. */
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
  let retryLoading = false, contextMap = null;
  const sources = new Map([...DATA.questions, ...Object.values(DATA.retry || {}).flat()].map(q => [q.id, q]));
  // Least-privilege GitHub access is opt-in and strictly local to the browser.
  // Never put an access token in GitHub Pages source, a report, an issue URL,
  // Actions logs, or a training answer. Only this repository can be targeted.
  const ISSUE_REPO = 'pkppkqbobs/kaoyan-english-trainer';
  const AUTH_KEY = 'kaoyan.github.issue-credential.v1.' + ISSUE_REPO;
  const RECEIPT_KEY = 'kaoyan.github.issue-receipts.v1.' + ISSUE_REPO;
  const receiptsInMemory = {};
  let volatileCredential = '';
  let submitBusy = false;
  const tokenTemplate = 'https://github.com/settings/personal-access-tokens/new' +
    '?name=English+Review+Uploader&description=Only+write+training+issues' +
    '&target_name=pkppkqbobs&expires_in=90&issues=write';

  function credential() {
    try { return volatileCredential || window.sessionStorage?.getItem(AUTH_KEY) ||
      localStorage.getItem(AUTH_KEY) || ''; }
    catch (_) { return volatileCredential; }
  }
  function keepCredential(token, persist) {
    volatileCredential = token;
    try {
      if (persist) {
        localStorage.setItem(AUTH_KEY, token);
        window.sessionStorage?.removeItem(AUTH_KEY);
      } else {
        localStorage.removeItem(AUTH_KEY);
        window.sessionStorage?.setItem(AUTH_KEY, token);
      }
      return true;
    } catch (_) { return false; }
  }
  function forgetCredential() {
    volatileCredential = '';
    try { localStorage.removeItem(AUTH_KEY); } catch (_) {}
    try { window.sessionStorage?.removeItem(AUTH_KEY); } catch (_) {}
  }
  function savedReceipts() {
    try {
      const saved = JSON.parse(localStorage.getItem(RECEIPT_KEY) || '{}');
      return saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {};
    } catch (_) { return {}; }
  }
  function saveReceipt(id, issue) {
    receiptsInMemory[id] = {number: issue.number, url: issue.html_url};
    try {
      const data = savedReceipts();
      data[id] = receiptsInMemory[id];
      localStorage.setItem(RECEIPT_KEY, JSON.stringify(data));
    } catch (_) {} // A local storage failure never changes the GitHub result.
  }
  function issueTitle(run) {
    return '[TRAINING_RESULT] ' + (DATA.reportTitle || '每日复习') + ' ' + run.date + ' ' + run.id;
  }
  function syncStatus(message, url) {
    notice(message);
    if (url && /^https:\/\/github\.com\/pkppkqbobs\/kaoyan-english-trainer\/issues\/\d+$/.test(url)) {
      const link = document.createElement('a');
      link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = ' 查看已提交的 Issue';
      byId('notice').appendChild(link);
    }
  }
  async function issueApi(path, token, options={}) {
    let response;
    try {
      response = await fetch('https://api.github.com' + path, {
        ...options, cache: 'no-store',
        headers: {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
          'Authorization': 'Bearer ' + token, ...(options.body ? {'Content-Type':'application/json'} : {})}
      });
    } catch (_) {
      throw Error('无法访问 GitHub API；可能是网络、浏览器跨域或扩展拦截。');
    }
    if (!response.ok) {
      const status = Number(response.status);
      if (status === 401) throw Error('授权已失效；请重新设置令牌。');
      if (status === 403) throw Error('没有 Issues 写入权限，或触发 GitHub API 限流。请核对令牌仓库和权限。');
      if (status === 404) throw Error('无法访问目标仓库，请核对令牌选择的仓库。');
      if (status === 422) throw Error('GitHub 拒绝了 Issue 内容；原始成绩仍保存在本地。');
      throw Error('GitHub API 请求失败（HTTP ' + status + '），未确认成绩提交。');
    }
    try { return await response.json(); }
    catch (_) { throw Error('GitHub 响应不完整。请点击重试检查是否已提交，不要手动创建重复 Issue。'); }
  }
  function isOurIssue(item, title, roundId) {
    return item && !item.pull_request && item.title === title &&
      typeof item.body === 'string' && item.body.includes('<!-- review-json:v3') &&
      item.body.includes('"roundId":"' + roundId + '"');
  }
  async function findSubmittedIssue(token, title, roundId) {
    // REST issue listing is immediately consistent and avoids search-index lag.
    // Never POST if previous submission status cannot be checked reliably.
    for (let page=1; page<=20; page++) {
      const found = await issueApi('/repos/' + ISSUE_REPO +
        '/issues?state=all&per_page=100&page=' + page, token);
      if (!Array.isArray(found)) throw Error('无法验证 GitHub 历史 Issue，已停止提交以免重复。');
      const existing = found.find(item => isOurIssue(item, title, roundId));
      if (existing) return existing;
      if (found.length < 100) return null;
    }
    throw Error('已有 Issue 超过自动查重上限，为避免重复提交，本次未上传。');
  }
  async function submitDirect() {
    if (submitBusy) return;
    const run = rootRun(), token = credential();
    if (DATA.repo !== ISSUE_REPO) { notice('仓库与授权目标不一致，已停止自动提交。'); return; }
    if (run.answers.length !== run.queue.length || run.index < run.queue.length) {
      notice('主测尚未完成，不能提交部分成绩。'); return;
    }
    if (!token) { showIssueSettings(); return; }
    submitBusy = true;
    syncStatus('正在检查是否已提交该轮，并通过 GitHub API 同步首次作答……');
    const originalKey = storageKey;
    const title = issueTitle(run);
    try {
      const cached = receiptsInMemory[run.id] || savedReceipts()[run.id];
      if (cached?.number && cached?.url) {
        const verified = await issueApi('/repos/' + ISSUE_REPO + '/issues/' + cached.number, token);
        if (isOurIssue(verified, title, run.id)) {
          syncStatus('已确认此前提交成功，Issue #' + verified.number + '；没有重复提交。', verified.html_url);
          return;
        }
      }
      const existing = await findSubmittedIssue(token, title, run.id);
      if (existing) {
        saveReceipt(run.id, existing);
        syncStatus('已找到同一轮的 Issue #' + existing.number + '，不会重复计分。', existing.html_url);
        return;
      }
      if (storageKey !== originalKey || rootRun().id !== run.id) {
        throw Error('正在查看的训练轮次已改变；取消本次上传以免提交错误记录。');
      }
      const issue = await issueApi('/repos/' + ISSUE_REPO + '/issues', token,
        {method:'POST',body:JSON.stringify({title, body:reportText()})});
      if (!Number.isInteger(issue.number) || !issue.html_url) {
        throw Error('GitHub 返回结果不完整，请重试核对是否已创建 Issue。');
      }
      saveReceipt(run.id, issue);
      syncStatus('GitHub 已接收首次作答：Issue #' + issue.number +
        '。成绩将在 Actions 成功处理后进入复习统计。', issue.html_url);
    } catch (error) {
      syncStatus('自动提交未确认成功：' + String(error.message || error) +
        ' 本地成绩保留，可以重试或使用导出报告。');
    } finally { submitBusy = false; }
  }
  function showIssueSettings() {
    const run = rootRun();
    shell();
    const body = byId('body');
    paragraph(body, '一次设置 GitHub 授权，以后完成主测即可自动生成 Issue。', 'target');
    paragraph(body, '先创建 Fine-grained personal access token：Resource owner = pkppkqbobs；Repository access = Only select repositories → kaoyan-english-trainer；Repository permissions → Issues = Read and write。其他权限不需要。', 'muted');
    const link = document.createElement('a');
    link.textContent = '① 打开 GitHub 最小权限令牌创建页';
    link.href = tokenTemplate; link.target = '_blank'; link.rel = 'noopener noreferrer';
    body.appendChild(link);
    paragraph(body, '② 只在下方粘贴令牌，不要把令牌发送给 ChatGPT、写入 Issue 或上传到仓库。', 'muted');
    const input = document.createElement('input');
    input.type = 'password'; input.autocomplete = 'off';
    input.placeholder = 'github_pat_…（此处不会公开显示）';
    input.style.width = '100%'; input.style.padding = '12px';
    input.style.marginTop = '10px'; input.style.marginBottom = '10px';
    body.appendChild(input);
    const label = document.createElement('label');
    const remember = document.createElement('input');
    remember.type = 'checkbox'; remember.checked = true;
    label.appendChild(remember);
    label.appendChild(document.createTextNode(' 记住此浏览器（以后无需再次粘贴）'));
    body.appendChild(label);
    paragraph(body, '安全提醒：选择记住会将限定权限的令牌保存在此网站的浏览器存储中，可能被同源脚本读取。公共电脑请取消勾选，或改用“导出本轮报告”。建议 90 天到期并可随时撤销。', 'muted');
    const actions = document.createElement('div'); actions.className = 'actions';
    actions.appendChild(button('③ 保存授权并自动同步', async () => {
      const token = String(input.value || '').trim(); input.value = '';
      if (!/^github_pat_[a-zA-Z0-9_]+$/.test(token)) {
        notice('请使用仅限此仓库、具有 Issues 写入权限的 Fine-grained token（github_pat_ 开头）。');
        return;
      }
      try {
        const person = await issueApi('/user', token);
        if (String(person.login || '').toLowerCase() !== ISSUE_REPO.split('/')[0]) {
          throw Error('令牌不属于仓库所有者；该仓库的成绩回流仅接受所有者创建的 Issue。');
        }
        const saved = keepCredential(token, remember.checked);
        render();
        if (!saved) notice('已连接，但浏览器无法持久保存令牌；此标签页仍可直接提交。');
        if (run.answers.length === run.queue.length && run.index === run.queue.length) await submitDirect();
        else notice('授权成功。以后每轮主测完成将直接同步，无需登录 GitHub Issue 页面。');
      } catch (error) {
        notice('授权未成功：' + String(error.message || error));
      }
    }, 'primary'));
    if (credential()) actions.appendChild(button('移除此浏览器中的 GitHub 授权', () => {
      forgetCredential(); render(); notice('已从此浏览器移除自动提交授权。');
    }));
    actions.appendChild(button('返回训练', render));
    body.appendChild(actions);
  }

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
        r.index <= r.answers.length && r.answers.every((a,i)=>a && a.qid===r.queue[i]?.id && a.family===r.queue[i]?.family && Number.isInteger(a.pick) &&
          a.pick >= 0 && a.pick < 4 && Number.isInteger(a.expected) && a.expected >= 0 && a.expected < 4 &&
          a.expected===r.queue[i].a && a.ok===(a.pick===a.expected) && Number.isFinite(a.ms) && a.ms >= 0) &&
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
      state = {version: 3, date: DATA.date, meta: DATA.meta, retry: copy(DATA.retry || {}), runs: [], current: 0};
      createRun('main', DATA.questions, null);
    } else if (key === PREFIX + (DATA.storageId || DATA.date)) {
      state.retry ??= copy(DATA.retry || {});
      state.meta ??= DATA.meta;
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
    app.innerHTML = '<header><h1>' + (DATA.title || '今日定制 · 8题') + '</h1><div id="meta" class="muted"></div><div class="actions"><a class="button" href="./">返回总训练站</a><button id="historyBtn">本地历史记录</button><button id="todayBtn">' + (DATA.progressLabel || '返回本轮进度') + '</button><button id="githubAuthBtn">GitHub 自动同步设置</button></div></header><p id="notice" class="notice hidden" role="status"></p><section id="body" class="card" aria-live="polite"></section>';
    byId('meta').textContent = state.meta || (state.date + (storageKey === PREFIX + (DATA.storageId || DATA.date) ? '' : ' · 历史题单') + ' · 约5–10分钟 · 答题后显示解析 · 刷新保留进度');
    byId('historyBtn').onclick = () => { checkpoint(); historyView(); };
    byId('todayBtn').onclick = () => { checkpoint(); restore(PREFIX + (DATA.storageId || DATA.date)); render(); };
    byId('githubAuthBtn').onclick = () => { checkpoint(); showIssueSettings(); };
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
    if (q.retryOriginal) paragraph(body, q.retryNotice || '此目标暂时没有另一道新语境题，当前重做原题；首次错误仍保留。', 'notice');
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
    actions.appendChild(button(run.index === run.queue.length - 1 ? '完成本轮' : '下一题', () => {
      run.index++; save(); render();
      // Only a real completion interaction can automatically submit. Refreshing
      // or opening an old completed round must not silently upload its records.
      if (run.kind === 'main' && run.index === run.queue.length && credential()) void submitDirect();
    }, 'primary'));
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
  function validRetryPool(pool) {
    return pool && typeof pool==='object' && !Array.isArray(pool) && Object.entries(pool).every(([family,items])=>
      Array.isArray(items) && items.every(q=>q && typeof q.id==='string' && q.family===family && typeof q.q==='string' &&
        Array.isArray(q.o) && q.o.length===4 && new Set(q.o).size===4 && q.o.every(x=>typeof x==='string') &&
        Number.isInteger(q.a) && q.a>=0 && q.a<4 && q.exp && ['trans','structure','other','meaning','rest'].every(k=>typeof q.exp[k]==='string')));
  }
  async function historicalRetryPool(root, key) {
    const id=key.slice(PREFIX.length);
    let path;
    if(PREFIX==='kaoyan.daily.v3.' && /^\d{4}-\d{2}-\d{2}$/.test(id))path='./data/days/'+id+'.json';
    else if(PREFIX==='kaoyan.article.v1.' && /^[a-zA-Z0-9_-]{1,160}$/.test(id))path='./data/article-reviews/'+id+'.json';
    if(!path)throw new Error('请从该轮的原页面打开迁移题。');
    const response=await fetch(path,{cache:'no-store'});
    if(!response.ok)throw new Error('历史题单暂时无法读取。');
    const payload=await response.json();
    if((payload.storageId||payload.date)!==id || payload.date!==root.date || !Array.isArray(payload.questions) || !validRetryPool(payload.retry) ||
        !root.queue.every(q=>payload.questions.some(source=>source.id===q.id && source.family===q.family && source.q===q.q &&
          source.o.length===4 && q.o.every(x=>source.o.includes(x)) && source.o[source.a]===q.o[q.a]))) {
      throw new Error('历史题单与保存的首次题目不一致。');
    }
    return payload;
  }
  async function retryWrong() {
    if(retryLoading)return;
    const root = rootRun();
    const wrong = wrongOf(root);
    if (!wrong.length) { notice('这次主测没有错题；可以查看解析或全部重做。'); return; }
    const key=storageKey;
    let pool=state.retry, retryNotice='';
    retryLoading=true;
    try {
      if(!validRetryPool(pool) || wrong.some(({q})=>!Object.prototype.hasOwnProperty.call(pool,q.family))) {
        notice('正在读取这份历史题单的迁移题；首次成绩保持不变。');
        const payload=await historicalRetryPool(root,key);
        if(storageKey!==key || rootRun().id!==root.id)return;
        pool=copy(payload.retry);state.retry=pool;state.meta=payload.meta;save();
      }
      const variants=wrong.flatMap(({q})=>pool[q.family]||[]);
      if(!contextMap && [...wrong.map(x=>x.q),...variants].some(q=>!q.context_id && !sources.get(q.id)?.context_id)) {
        try {
          const response=await fetch('./data/question-contexts.json',{cache:'no-store'});
          const metadata=response.ok?await response.json():null;
          contextMap=metadata?.contexts || {};
        }catch(_){contextMap={};}
      }
    }catch(_){pool={};retryNotice='当前页面无法取得这轮的迁移题。可从历史入口打开原页；当前先回顾原题，首次成绩保留。';}
    finally{retryLoading=false;}
    if(storageKey!==key || rootRun().id!==root.id)return;
    const contextOf=q=>q.context_id || sources.get(q.id)?.context_id || contextMap?.[q.id] || q.id;
    const used = new Set(state.runs.filter(r => r.parentId === root.id).flatMap(r => r.queue.map(q => q.id)));
    const usedContexts = new Set(state.runs.filter(r => r.parentId === root.id).flatMap(r => r.queue.map(contextOf)));
    const questions = wrong.map(({q}) => {
      const candidates = (pool[q.family] || []).filter(x => x.id!==q.id && x.q !== q.q && contextOf(x)!==contextOf(q));
      const fresh = candidates.filter(x => !used.has(x.id) && !usedContexts.has(contextOf(x)));
      if (fresh.length || candidates.length) return copy(shuffle(fresh.length ? fresh : candidates)[0]);
      return {...copy(q), retryOriginal: true, ...(retryNotice?{retryNotice}:{})};
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
  function showCopyFallback(text) {
    const body = byId('body');
    const area = document.createElement('textarea');
    area.value = text;
    area.rows = 14;
    area.readOnly = true;
    if (area.style) { area.style.width = '100%'; area.style.minHeight = '220px'; }
    body.appendChild(area);
    if (typeof area.focus === 'function') area.focus();
    if (typeof area.select === 'function') area.select();
    notice('备用 Issue 页面已打开。若报告未自动复制，下面已显示完整报告；按 Ctrl+C 后粘贴到 GitHub 内容框。');
  }
  function fallbackSubmit() {
    const root = rootRun();
    const title = '[TRAINING_RESULT] ' + (DATA.reportTitle || '每日复习') + ' ' + root.date + ' ' + root.id;
    const text = reportText();
    const clipboard = window.navigator && window.navigator.clipboard;
    // Request clipboard permission while this page still has focus and the
    // click is active, then open only a short Issue URL (no encoded JSON body).
    let pending = null;
    if (clipboard && typeof clipboard.writeText === 'function') {
      try { pending = clipboard.writeText(text); } catch (_) { /* manual fallback below */ }
    }
    window.open('https://github.com/' + DATA.repo + '/issues/new?title=' + encodeURIComponent(title), '_blank', 'noopener,noreferrer');
    if (pending && typeof pending.then === 'function') {
      pending.then(() => notice('报告已复制。请在 GitHub Issue 正文粘贴后点击 Submit new issue，才算提交。'))
        .catch(() => showCopyFallback(text));
    } else {
      showCopyFallback(text);
    }
  }
  function submit() {
    if (credential()) void submitDirect();
    else showIssueSettings();
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
    actions.appendChild(button('设置一键自动同步', showIssueSettings));
    actions.appendChild(button('备用提交：复制报告并打开空白 Issue', fallbackSubmit));
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
