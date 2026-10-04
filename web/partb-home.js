/* A static recommendation never edits a daily quiz or another module's storage. */
(() => {
  'use strict';
  const node=document.getElementById('partbSuggestion');
  if(!node)return;
  fetch('./data/partb-recommendation.json',{cache:'no-cache'})
    .then(response=>{if(!response.ok)throw new Error('Unavailable recommendation');return response.json();})
    .then(data=>{
      if(!data.recommend)return;
      const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
      node.textContent=data.as_of===today?'今日建议加练：Part B 排序 1 篇':'根据 '+data.as_of+' 的已提交记录，建议加练 Part B 排序 1 篇';
      node.hidden=false;
    }).catch(()=>{}); // The permanent training link remains available.
})();
