# 题库覆盖与重复曝光维护

2026-10-05审计覆盖：daily/article源BANK、首页53题、旧独立词汇页11题、
自动化前归档8主测/8retry，以及六套完整Part B。生成HTML、latest别名和retry候选池
不重复算成独立变体。原始Issues只读取，旧成绩与题单不改写。

`data/question-contexts.json` 是人工审核的语境/证据路径聚类。
同qid的生成副本不另计；仅换名词、相同排除套路的题保守合并。
不同题号不能自动证明新语境，聚类也不是机器判断能力掌握。
维护者新增题时应更新分类；自动测试要求所有可用源题都有分类。

`data/question-bank-audit.json` 是本次日期的维护快照，**不参与计分**。
每family有qid数、有效语境数、main/retry候选、首次/末次出现、已发布次数、
已接受作答/错误/uncertain、3/7日曝光及覆盖风险。
`spaced_*` 单独统计真正能进入daily/article的池；旧首页题不等于可调度题。
完整Part B单独计数，不能用其六篇代替mini维护题的覆盖检查。

## 曝光的证据边界

- `times_shown` 指唯一已发布daily/article/passage轮次中的主测槽位，不能证明用户已打开。
- 3日含当天及之前两日，7日含当天及之前六日，按北京时间日期。
- 同题retry候选不代表已展示；旧报告的retrySummary没有qid，不猜其具体曝光。
- 同qid两个Part B family成绩行仍只是一篇实际作答。
- 老Issue没有qid的已接受成绩保留在family计数，`unknown_qid_attempts` 明示无法分配。
- 未提交浏览器成绩不可读取。`no_repository_exposure_record` 不能说成用户从未见过。
- legacy词汇页11题没有qid，使用仅供清点的定位键；未给它们补造成绩题号。
- 未映射的低频可组合词观察（如kitten-killing）不因此制造一个新family或attempt。

风险分开报告：`severe`为可调度语境不足2，`limited`为2，
`sufficient`为至少3；`structural_gap`由人工指出机制缺口。
`recent_repeat_risk`另外标记近期曝光偏多；语境数足够仍可能有重复风险。
人工聚类口径、历史局限和补题前数量都保存在JSON中，便于复核。

## 本次处理

新增19题到13个原family。新题有完整五段解析、文本错项解释，
不使用固定选项字母。`published_on`表示新题发布日期；
`introduced`沿用已有目标实际学习日期或null，不能把补题当首次学习。
新增题未提高已有family的slow阈值，旧error/streak结果不因扩容变化。

只小修变体选择：保持family优先级和8题规模，独立合并已发布article/passage历史，
按语境最近出现时间、再按qid最近出现时间选择。
未来retry只提供不同语境；没有合格变体时现有前端明确回顾原题。
旧daily/article轮次的题目和retry快照保持原样。

career/recruitment/nested/relative的跨日表现已稳定，暂不平均扩容；
部分单题翻译词汇缺乏真实作答证据，先观察。
六套完整Part B主题不同，但篇章骨架有相似性，等真实排序结果再决定下一批结构。
归档旧retry的套用解析未导入当前BANK；旧独立词汇页的介词滞后选项有可成立解，
该历史题不能当唯一语法答案的强掌握证据。本次没有改写这些旧页面记录。

## 重跑审计与回归

```sh
python3 scripts/question_bank_audit.py --date YYYY-MM-DD
python3 -m unittest discover -s tests -v
node --check scripts/question_bank_audit.mjs
node --check web/review.js
node tests/ui.mjs
node --check web/partb-core.js
node --check web/partb.js
node --check web/partb-home.js
node tests/partb-ui.mjs
```

审计按需由维护者重跑，不增加定时评分链路或网页UI；它不是实时成绩。
完整生成回归应在临时副本中做，并确认当前locked daily、已有成绩、
learning notes、source-check、文章及Part B历史逐字节不变。
