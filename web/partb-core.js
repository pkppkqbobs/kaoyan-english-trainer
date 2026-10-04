/* Shared pure scorer. Browser rendering and Node tests use this exact module. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.PARTB_CORE = api;
})(typeof window === 'object' ? window : this, function () {
  'use strict';
  const families = link => [
    ...(link.signals.includes('anaphora') ? ['paragraph-order-anaphora'] : []),
    ...(link.signals.some(s => s !== 'anaphora') ? ['paragraph-order-discourse'] : [])
  ];
  function validateOrder(q, order) {
    const ids = q.paragraphs.map(p => p.id);
    if (!Array.isArray(order) || order.length !== ids.length ||
        order.some(x => typeof x !== 'string' || !ids.includes(x)) || new Set(order).size !== ids.length) {
      throw new Error('顺序必须包含每个段落一次。');
    }
  }
  function score(q, order) {
    validateOrder(q, order);
    const chosen = new Set(order.slice(1).map((b, i) => order[i] + '>' + b));
    const standard = new Set(q.links.map(l => l.from + '>' + l.to));
    const pairResults = q.links.map(l => ({from:l.from, to:l.to, signals:l.signals.slice(),
      families:families(l), anchor:l.anchor, ok:chosen.has(l.from + '>' + l.to)}));
    const anchors = pairResults.filter(p => p.anchor);
    const endpoints = p => ({from:p.from, to:p.to});
    return {fullOrderOk:order.every((x,i) => x === q.expectedOrder[i]),
      pairScore:{correct:pairResults.filter(p=>p.ok).length,total:pairResults.length},
      anchorScore:{correct:anchors.filter(p=>p.ok).length,total:anchors.length},
      startOk:order[0] === q.expectedOrder[0], endOk:order.at(-1) === q.expectedOrder.at(-1),
      positionScore:{correct:order.filter((x,i)=>x===q.expectedOrder[i]).length,total:order.length},
      pairResults, hitPairs:pairResults.filter(p=>p.ok).map(endpoints),
      missedPairs:pairResults.filter(p=>!p.ok).map(endpoints),
      wrongPairs:order.slice(1).map((b,i)=>({from:order[i],to:b})).filter(p=>!standard.has(p.from+'>'+p.to))};
  }
  function shuffle(ids, random = Math.random) {
    const out = ids.slice();
    for (let i=out.length-1; i>0; i--) {
      const j = Math.floor(random() * (i+1)); [out[i],out[j]] = [out[j],out[i]];
    }
    return out;
  }
  function report(main, question, retries = []) {
    if (!main.result || main.mode !== 'main') throw new Error('只能提交完整首次主测。');
    const answer = r => ({kind:'paragraph_order',mode:r.mode,qid:question.id,pickOrder:r.pickOrder.slice(),
      expectedOrder:question.expectedOrder.slice(),pairResults:score(question,r.pickOrder).pairResults,
      ok:score(question,r.pickOrder).fullOrderOk,ms:r.result.ms,uncertain:r.uncertain});
    return {version:4,module:'partb',roundId:main.id,date:main.date,
      answers:[answer(main),...retries.filter(r=>r.result).map(answer)]};
  }
  return {score, validateOrder, shuffle, report};
});
