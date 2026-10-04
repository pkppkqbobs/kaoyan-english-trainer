# Part B 独立排序训练

入口：`partb-review.html`。历史与简要机制统计：`partb-history.html`。
点击段落编号，支持撤销、清空、键盘按钮操作和刷新恢复；提交完整顺序后才显示答案及接缝解释。
所有页面由现有官方 GitHub Pages 分支发布器部署，无新增服务。

## 题库与不可变快照

`data/partb-questions/*.json` 是独立题库，不进入普通四选一 BANK。
每题 `kind: "paragraph_order"`，5–7 段，每段1–3句，共250–450英文词。
`scripts/partb_review.py::validate_question` 验证 schema；示例读取初始六套题库。

必填字段：

| 字段 | 含义 |
| --- | --- |
| id / published_on / title / topic | 唯一题号、首次发布时间、题名、主题 |
| paragraphs | `{id: "A", text: "..."}` 数组；段落ID不重复 |
| expectedOrder | 全部段落ID的唯一标准排列 |
| links | 按标准顺序排列的全部相邻接缝 |
| links[].signals | 回指、复现、问题到原因、平行、收束等12种稳定机制，可多选 |
| links[].strength / evidence | 强、中、辅助证据；解释支持什么，不能只凭代词宣称唯一相邻 |
| links[].anchor | 本题用于锚点指标的连接 |
| globalLogic / themeTrap | 全篇约束与干扰性主题联系 |
| budget | 全篇有效用时参考阈值，300–480秒，不等同于小题用时 |
| mechanism_source | 可选的真实题机制来源；必须引用存在的source-check及已核验连接 |

首次生成保存在 `data/partb-reviews/题号.json`。已发布ID不可改写正文、顺序、标签或答案；
订正需新ID，并保留旧快照以核验旧Issue。即使从源题库移走旧题，快照仍可恢复。
六套题分别覆盖科研、公司管理、交通、教育、医疗制度、环境政策。
每套的 `globalLogic` 记录全篇排除其他排列的理由；自动测试不能代替语义审核。

## 评分与 v4 Issue

报告保持旧训练标记，新增 `<!-- review-json:v4` JSON块。
旧逐题/汇总格式及 `review-json:v3` 不改变。

```json
{
  "version": 4,
  "module": "partb",
  "roundId": "pb-unique-round-id",
  "date": "2026-10-04",
  "answers": [{
    "kind": "paragraph_order",
    "mode": "main",
    "qid": "pb-river-sensors-v1",
    "pickOrder": ["D", "A", "F", "C", "B", "E"],
    "expectedOrder": ["D", "A", "F", "C", "B", "E"],
    "ms": 300000,
    "uncertain": true
  }]
}
```

前端附带 `pairResults` 和 `ok` 供报告阅读，脚本完全重新计算这些字段。
提供的 `expectedOrder` 必须与不可变仓库题目一致，非法、重复、缺段、多段顺序拒绝计分。
主测最多一条；`mode: "retry"` 可随主测附带，但不产生长期证据。
同轮重复Issue只计一次；只读取仓库所有者主动提交的训练Issue。

指标包括完整顺序对错、正确相邻连接数、锚点命中数、首尾对错及正确位置数。
保留命中、漏掉、错误建立的连接，不能把相邻分数说成原真题正确率。
`paragraph-order-anaphora` 对应anaphora；其他机制进入 `paragraph-order-discourse`。
同一连接可归两个机制；同一篇每family汇总一条“全部相关连接是否命中”的主测证据。
多条错误接缝不会制造多个attempt或多个跨日streak。同日daily/article/Part B仍按日期聚合。
全篇用时使用独立阈值，`uncertain` 即使全部排对也保留为优先级信号。

## 历史、重做和来源

localStorage独立前缀 `kaoyan.partb.v1.`；每题一个storageId，内部追加每轮记录。
首次提交顺序锁定，原题回顾不覆盖它。优先“下一篇新语境”；六套都练过后允许回顾，不冒充新掌握。
历史页可恢复本地未完成/已完成轮次，并展示从Issue核验生成的 `data/partb-results.json`。
统计合并本地与已提交结果，按roundId去重，最多取最近五次主测，不统计回顾。

2011只作为学习观察与机制来源，引用 `data/source-checks/2011-english1.json`。
没有用户41–45完整选项，不补写原题pair成绩。`translation_difficulty`与排序错误始终分开。
源题的B→D、G→B、D→E、E→A、A→C、C→F对应的问题解释、主题引入、回指、具体化、平行和收束，
已迁移到完全不同的材料；页面不包含2011原文全文。

普通daily仍8题，新生成轮次最多一道Part B小型pair维护题，完整排序放独立入口。
首页从静态 `data/partb-recommendation.json` 显示加练建议，不操作daily或其他localStorage。
Actions在成绩同步后生成Part B页与历史；生成输出不命中push输入路径，不建立commit loop或第二套deploy。

## 验证

```sh
python3 -m unittest discover -s tests -v
node --check web/review.js
node tests/ui.mjs
node --check web/partb-core.js
node --check web/partb.js
node --check web/partb-home.js
node tests/partb-ui.mjs
python3 scripts/run_daily.py --date 2026-10-04
python3 scripts/article_review.py
python3 scripts/partb_review.py
```

日期参数仅为本次开发复现示例，实际每日生产使用北京时间且不固定日期。
原生浏览器窄视口检查入口：`tests/partb-mobile.html`，可切换320/390像素。
它使用真实页面的内存预览，既不读写学习者记录，也不提供提交成绩按钮。
用原生按钮的Tab/Enter/Space测试键盘；检查撤销、清空、完整提交后的接缝说明和水平溢出。
