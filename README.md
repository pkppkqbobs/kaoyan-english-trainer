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
