"""Build a per-article mixed review page from explicit chat-synced evidence plus historical weak targets."""
from __future__ import annotations
import copy
import hashlib
import json
import random
import re
from datetime import date
from pathlib import Path

import daily_review as review

ROOT = Path(__file__).resolve().parents[1]


def latest_session(root):
    folder = root / "data/article-sessions"
    if not folder.exists():
        return None
    sessions = sorted(folder.glob("*.json"))
    if not sessions:
        return None
    obj = review.load(sessions[-1], {})
    required = ("id", "date", "source", "focus_families")
    if not all(obj.get(k) for k in required):
        raise ValueError("Article session is missing required fields")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,120}", obj["id"]):
        raise ValueError("Invalid article session id")
    date.fromisoformat(obj["date"])
    if not isinstance(obj["focus_families"], list) or not all(isinstance(x, str) and x for x in obj["focus_families"]):
        raise ValueError("Invalid focus_families")
    obj["_path"] = str(sessions[-1].relative_to(root))
    return obj


def choose_variant(groups, family, rng, avoid_ids, prefer_date=None):
    variants = [copy.deepcopy(q) for q in groups.get(family, [])]
    if not variants:
        raise ValueError("No question variant for article-review family: " + family)
    rng.shuffle(variants)
    if prefer_date:
        dated = [q for q in variants if q.get("introduced") == prefer_date and q["id"] not in avoid_ids]
        if dated:
            return dated[0]
    unseen = [q for q in variants if q["id"] not in avoid_ids]
    return (unseen or variants)[0]


def build(root=ROOT, repo="pkppkqbobs/kaoyan-english-trainer"):
    session = latest_session(root)
    if not session:
        return None

    day = date.fromisoformat(session["date"])
    items = review.bank(root)
    groups = {}
    for q in items:
        if not q.get("introduced") or q["introduced"] <= session["date"]:
            groups.setdefault(q["family"], []).append(q)

    evidence = review.load(root / "data/result-evidence.json", {"rows": [], "issues": []})
    notes = review.load(root / "data/learning-notes.json", [])
    stats = review.make_stats(items, evidence["rows"], notes, day)
    history = review.load(root / "data/daily-history.json", {})
    today = review.load(root / "data/daily.json", {})
    today_ids = {q["id"] for q in today.get("questions", [])} if today.get("date") == session["date"] else set()

    focus = []
    for family in session["focus_families"]:
        if family in groups and family not in focus:
            focus.append(family)
    if not focus:
        raise ValueError("Article session has no question-backed focus family")

    max_current = int(session.get("max_current", 4))
    max_current = max(1, min(4, max_current, len(focus)))
    current_families = focus[:max_current]

    # Reuse the audited daily ranker for the historical half, then exclude the current article's targets.
    ranked_questions = review.choose(items, stats, history, day)
    historical_families = []
    for q in ranked_questions:
        if q["family"] not in current_families and q["family"] not in historical_families:
            historical_families.append(q["family"])
        if len(historical_families) >= 8 - max_current:
            break

    if len(historical_families) < 8 - max_current:
        fallback = sorted(
            (f for f in groups if f not in current_families and f not in historical_families),
            key=lambda f: (
                stats[f]["due"] > session["date"],
                -stats[f]["errors"],
                not stats[f]["reported_confusion"],
                not stats[f]["slow_or_uncertain"],
                stats[f]["due"],
                f,
            ),
        )
        historical_families.extend(fallback[:8 - max_current - len(historical_families)])

    families = current_families + historical_families[:8 - max_current]
    if len(families) != 8 or len(set(families)) != 8:
        raise ValueError("Could not build an eight-family article review")

    rng = random.Random("article-review:" + session["id"])
    selected = []
    used_ids = set()
    for family in current_families:
        q = choose_variant(groups, family, rng, today_ids | used_ids, prefer_date=session["date"])
        selected.append(q)
        used_ids.add(q["id"])
    for family in historical_families[:8 - max_current]:
        q = choose_variant(groups, family, rng, today_ids | used_ids)
        selected.append(q)
        used_ids.add(q["id"])

    rng.shuffle(selected)
    retry = {
        q["family"]: [copy.deepcopy(v) for v in groups[q["family"]] if v["id"] != q["id"]]
        for q in selected
    }
    payload = {
        "date": session["date"],
        "repo": repo,
        "title": "文章复盘 · 8题",
        "meta": f"{session['source']} · 本篇问题 {max_current} 题 + 历史弱项 {8-max_current} 题 · 全部使用迁移语境",
        "progressLabel": "返回本篇进度",
        "storagePrefix": "kaoyan.article.v1.",
        "storageId": session["id"],
        "ignoreStale": True,
        "reportLabel": "考研英语文章复盘",
        "reportTitle": "文章复盘",
        "exportStem": "article-review",
        "footer": "本篇复盘结果只有在你点击“提交结果到 GitHub”并在 GitHub 再点 Submit new issue 后，才会进入后续间隔复习。",
        "questions": selected,
        "retry": retry,
        "article_session": {
            "id": session["id"],
            "source": session["source"],
            "session_file": session["_path"],
            "current_families": current_families,
            "historical_families": historical_families[:8-max_current],
        },
        "issues_used": evidence.get("issues", []),
        "engine": 4,
    }
    review.save(root / "data/article-review.json", payload)
    review.save(root / f"data/article-reviews/{session['id']}.json", payload)

    version = hashlib.sha256((root / "web/review.js").read_bytes()).hexdigest()[:12]
    embedded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    page = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>文章复盘8题 · 考研英语</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6fb;color:#192336;font-family:system-ui,"Microsoft YaHei",sans-serif}main{max-width:900px;margin:auto;padding:20px}h1{font-size:23px;margin:0 0 8px}.card{background:white;border:1px solid #e3e7ef;border-radius:16px;padding:22px;margin:16px 0}.muted{color:#667085;font-size:14px;line-height:1.6}.target{display:inline-block;padding:8px 12px;background:#eef2ff;color:#3045a0;border-radius:12px;font-weight:700}.sentence{white-space:pre-wrap;font-size:19px;line-height:1.8;margin:18px 0}.choices{display:grid;gap:10px}button,a.button{border:1px solid #dfe4ee;border-radius:10px;padding:12px 16px;background:#fff;color:#172033;font:inherit;cursor:pointer;text-decoration:none}button:hover,a.button:hover{border-color:#3157d5}button:focus-visible,a:focus-visible{outline:3px solid #f59e0b;outline-offset:3px}button:disabled{cursor:default}.choice{text-align:left;line-height:1.6}.primary{background:#3157d5;color:white}.good{background:#e9f9ef}.bad{background:#fff0ee}.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}.explanation{line-height:1.8;white-space:pre-wrap}.explanation h3{font-size:16px;margin:15px 0 3px}.hidden{display:none!important}.notice{padding:10px;background:#fff7e6;line-height:1.6}.review{border-top:1px solid #e4e7ee;padding-top:18px;margin-top:18px}@media(max-width:600px){main{padding:12px}.card{padding:16px}.sentence{font-size:17px}}
</style></head><body><main id="app"></main><noscript>请启用浏览器JavaScript后做题。</noscript>
<script>window.REVIEW_DATA=__DATA__;</script><script src="./web/review.js?v=__VERSION__"></script></body></html>"""
    (root / "article-review.html").write_text(
        page.replace("__DATA__", embedded).replace("__VERSION__", version),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    result = build()
    if result:
        print(json.dumps({
            "session": result["article_session"]["id"],
            "questions": len(result["questions"]),
            "current": result["article_session"]["current_families"],
            "historical": result["article_session"]["historical_families"],
        }, ensure_ascii=False))
    else:
        print(json.dumps({"session": None, "questions": 0}, ensure_ascii=False))
