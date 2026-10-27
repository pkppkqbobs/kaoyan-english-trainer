# 考研英语自适应训练站

一个纯静态、无需后端的考研英语训练网页。

## 功能
- 一屏一题，A/B/C/D 直接点击
- 记录首次选择、答题时间、正确率、连续答对
- 按错误机制做诊断，而不只显示对/错
- 错误机制重复出现会自动提高训练权重
- 连续答对会自动降低频率
- 错题本、能力分析、只练错题机制
- 一键复制“给 ChatGPT 的学习报告”
- 本地记录默认不上传；主动提交训练 Issue 后进入间隔复习
- 独立 Part B 多段排序、逐接缝评分、历史恢复及机制统计

## GitHub Pages
将 `index.html` 放到仓库根目录，然后在仓库 Settings → Pages 中选择从默认分支根目录部署。

Part B：[排序训练](partb-review.html) · [历史与统计](partb-history.html)。
模块 schema、成绩回流与维护约定见 [PARTB_REVIEW.md](PARTB_REVIEW.md)；
每日/文章复盘约定见 [DAILY_REVIEW.md](DAILY_REVIEW.md)。
题库语境覆盖、曝光口径与维护审计见 [QUESTION_BANK_AUDIT.md](QUESTION_BANK_AUDIT.md)。

## 跨对话交接

新对话先读 [SESSION_HANDOFF.md](SESSION_HANDOFF.md)，需要逐项追溯时读取
[data/session-handoff.json](data/session-handoff.json) 和其中标出的原始记录。
摘要在现有 Actions 同步成绩、生成文章与 Part B 后自动更新，只索引已同步的学习观察和已接受主测；
不能读取尚未交给 Work 的聊天、照片或未提交的浏览器作答。日常对话负责教学，Work负责仓库维护、测试与部署验收。

固定分工如下，避免两个对话同时维护仓库：

| 入口 | 职责 |
|---|---|
| 普通学习对话 | 解题、分析错因，确认首次考虑、最终选项、犹豫与框词，整理结构化交接；GitHub写入交给Work。 |
| 这个Work维护对话 | 统一核对并保存观察，按需要补迁移题和文章session，运行测试、提交、验收Actions与Pages，再更新交接摘要。 |
| GitHub Actions | 同步已提交成绩、生成每日8题和已登记的复盘、更新摘要；不读取聊天，也不自行判断新错因或编写迁移题。 |

Work直接读取仓库里已有的反馈，不要求重复抄写；尚未同步的材料需要交给Work。
新篇维护须核对“观察已保存、对应复盘可做、交接已更新”三件事；仅笔记入库或Actions成功都不能代替完整验收。
常规维护沿用既有授权；只有平台明确拦截或真正超出委托范围时，再说明具体原因和待确认范围。

学习笔记与可做的文章复盘分别核对：摘要会列出已登记篇目中尚未生成复盘的缺口。
补发复盘分别记录原学习日期与实际题单发布日期；新入口在 [文章复盘](article-review.html)，
各篇独立轮次保存在 [历史文章复盘](article-reviews.html)，原成绩与旧轮次继续保留。

## 成绩自动回流（可选）

每日 8 题和文章专项复盘可在完成主测时自动创建 GitHub Issue，避免每次手动打开 GitHub 表单。
第一次在 [每日训练](today.html) 或 [文章复盘](article-review.html) 点击 **GitHub 自动同步设置**：

1. 打开页面提供的 GitHub **Fine-grained personal access token** 创建链接。
2. Resource owner 选 `pkppkqbobs`，Repository access 选 **Only select repositories → kaoyan-english-trainer**。
3. Repository permissions **Issues → Read and write**（其他权限不需要）；推荐设置 90 天有效期。
4. 只在训练网页的密码输入框粘贴令牌，点击 **保存授权并自动同步**。以后完成主测后会自动提交，并核查旧 Issue 避免重复提交。

**安全提醒：令牌等同于密码。** 网页代码公开，但**令牌不写进源码、GitHub Issue 或成绩记录**。勾选“记住此浏览器”时，令牌只存储于当前浏览器的 localStorage，同源脚本可能读取；公共电脑应取消勾选，或仍使用手动导出。可以通过训练页面移除本地授权，也可以在 GitHub Settings 撤销令牌。**不要把令牌发到 ChatGPT 或任何聊天窗口**。

GitHub API 只有返回创建成功的 Issue 后，网页才显示已提交；Actions 完成后才会进入正式成绩证据。接口失败、授权过期或网络断开时保留本地作答，不虚构 Issue 或 streak。Part B 独立模块暂继续原有成绩提交流程。

请在完成主测前标记犹豫。提交后新增的本地标记不会改写原 Issue；再次提交时会明确提示差异，保留本地记录并避免重复计分。网络超时可以重试，网页会先核验是否已经收到该轮。

如果不愿创建令牌，可以导出完整报告发到已连接 GitHub 的 ChatGPT，由我提交原始成绩；不要只发正确率截图。
