"""Publish immutable, independently stored article rounds using the shared review selector."""
from __future__ import annotations
import copy
import hashlib
import html
import json
import random
import re
from datetime import date, datetime
from pathlib import Path

import daily_review as review

ROOT = Path(__file__).resolve().parents[1]


def sessions(root):
    result, ids, storage_ids = [], set(), set()
    for path in sorted((root / "data/article-sessions").glob("*.json")):
        obj = review.load(path, {})
        if not all(obj.get(k) for k in ("id", "date", "source", "focus_families")):
            raise ValueError("Article session is missing required fields")
        if not isinstance(obj["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,120}", obj["id"]):
            raise ValueError("Invalid article session id")
        if obj["id"] in ids:
            raise ValueError("Duplicate article session id")
        ids.add(obj["id"])
        date.fromisoformat(obj["date"])
        if not isinstance(obj["source"], str):
            raise ValueError("Invalid article source")
        if not isinstance(obj["focus_families"], list) or not all(isinstance(x, str) and x for x in obj["focus_families"]):
            raise ValueError("Invalid focus_families")
        revision = obj.get("revision", 1)
        if type(revision) is not int or revision < 1:
            raise ValueError("Invalid article revision")
        if storage_id(obj) in storage_ids:
            raise ValueError("Duplicate article storageId")
        storage_ids.add(storage_id(obj))
        if type(obj.get("max_current", 4)) is not int or not 1 <= obj.get("max_current", 4) <= 4:
            raise ValueError("max_current must be between one and four")
        # Legacy sessions keep their IDs; new sessions must record an explicit time.
        stamp = obj.get("created_at", obj["date"] + "T00:00:00+08:00")
        created = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("Article created_at must include a timezone")
        obj["_created_at"] = created
        obj["_path"] = str(path.relative_to(root))
        result.append(obj)
    return sorted(result, key=lambda obj: (obj["_created_at"], obj["id"]))


def latest_session(root):
    ordered = sessions(root)
    return ordered[-1] if ordered else None


def storage_id(session):
    revision = session.get("revision", 1)
    return session["id"] if revision == 1 else f"{session['id']}-r{revision}"


def choose_variant(groups, family, rng, avoid_ids, prefer_date=None, history=None):
    return review.choose_variant(groups[family], history or {}, rng,
                                 avoid_ids=avoid_ids, prefer_date=prefer_date)


def make_payload(root, session, items, archives, repo):
    day = date.fromisoformat(session["date"])
    groups = {}
    for q in items:
        if review.available(q, day):
            groups.setdefault(q["family"], []).append(q)
    evidence = review.load(root / "data/result-evidence.json", {"rows": [], "issues": []})
    notes = review.load(root / "data/learning-notes.json", [])
    stats = review.make_stats(items, evidence["rows"], notes, day)
    history = review.load(root / "data/daily-history.json", {})
    history = {stamp: ids[:] for stamp, ids in history.items() if stamp <= session["date"]}
    shown_current = {}
    for old in archives.values():
        if old["date"] <= session["date"]:
            history.setdefault(old["date"], []).extend(q["id"] for q in old["questions"])
        if old.get("article_session", {}).get("id") == session["id"]:
            for family in old["article_session"]["current_families"]:
                shown_current[family] = shown_current.get(family, 0) + 1
    today = review.load(root / "data/daily.json", {})
    today_ids = {q["id"] for q in today.get("questions", [])} if today.get("date") == session["date"] else set()
    history.setdefault(session["date"], []).extend(sorted(today_ids))
    # Keep family ranking on its existing history; use all published modules
    # only when deciding which context/qid to show for that family.
    variant_shown = review.variant_history(root, day, history)

    focus = sorted(set(session["focus_families"]) & groups.keys())
    if not focus:
        raise ValueError("Article session has no question-backed focus family")
    rng = random.Random("article-review:" + storage_id(session))
    priority = {}
    for family in focus:
        observations = [n for n in notes if n["family"] == family and n["date"] == session["date"]
                        and n.get("session_id", session["id"]) == session["id"]]
        priority[family] = max((review.note_priority(n) for n in observations), default=1)
    # Wrong > uncertain > translation. Equal-priority targets rotate across revisions.
    jitter = {family: rng.random() for family in focus}
    focus.sort(key=lambda f: (-priority[f], shown_current.get(f, 0), jitter[f]))
    max_current = max(1, min(4, int(session.get("max_current", 4)), len(focus)))
    current_families = focus[:max_current]
    historical_items = [q for q in items if q["family"] in groups and q["family"] not in focus]
    historical = review.choose(historical_items, stats, history, day, count=8-max_current,
                               seed="article-history:" + storage_id(session), include_today=True,
                               variant_shown=variant_shown)
    historical_families = [q["family"] for q in historical]
    selected = [choose_variant(groups, family, rng, today_ids, session["date"], variant_shown)
                for family in current_families]
    selected.extend(historical)
    rng.shuffle(selected)
    return {
        "date": session["date"], "repo": repo, "title": "文章复盘 · 8题",
        "meta": f"{session['source']} · 本篇问题 {max_current} 题 + 历史弱项 {8-max_current} 题 · 全部使用迁移语境",
        "progressLabel": "返回本篇进度", "storagePrefix": "kaoyan.article.v1.",
        "storageId": storage_id(session), "ignoreStale": True,
        "reportLabel": "考研英语文章复盘", "reportTitle": "文章复盘", "exportStem": "article-review",
        "footer": "本篇复盘结果只有在你点击“提交结果到 GitHub”并在 GitHub 再点 Submit new issue 后，才会进入后续间隔复习。",
        "questions": selected,
        "retry": {q["family"]: review.retry_variants(items, q, day) for q in selected},
        "article_session": {"id": session["id"], "source": session["source"],
                            "created_at": session["_created_at"].isoformat(), "revision": session.get("revision", 1),
                            "session_file": session["_path"], "current_families": current_families,
                            "deferred_families": focus[max_current:], "historical_families": historical_families},
        "issues_used": evidence.get("issues", []), "engine": 4,
    }


def render_page(root, payload):
    version = hashlib.sha256((root / "web/review.js").read_bytes()).hexdigest()[:12]
    version = review.published_script_version(root / f"article-review-{payload['storageId']}.html", version)
    embedded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    # Corrections are displayed beside immutable rounds, never written into answers.
    families = {q["family"] for q in payload["questions"]}
    notices = []
    for path in sorted((root / "data/source-checks").glob("*.json")):
        for notice in review.load(path, {}).get("article_notices", []):
            if families.intersection(notice["families"]):
                notices.append('<p>' + html.escape(notice["text"]) + '</p>')
    correction = ('<aside class="notice" role="note" style="max-width:860px;margin:16px auto;padding:12px">'
                  '<strong>真题来源订正</strong>' + ''.join(notices) + '</aside>') if notices else ''
    return PAGE.replace("__DATA__", embedded).replace("__VERSION__", version).replace("__CORRECTIONS__", correction)


def build(root=ROOT, repo="pkppkqbobs/kaoyan-english-trainer"):
    ordered = sessions(root)
    if not ordered:
        return None
    items = review.bank(root)
    archives = {}
    for path in sorted((root / "data/article-reviews").glob("*.json")):
        payload = review.load(path)
        if payload.get("storageId") != path.stem:
            raise ValueError("Article archive and storageId do not match")
        for q in payload["questions"]:
            review.validate(q)
        if len(payload["questions"]) != 8 or len({q["family"] for q in payload["questions"]}) != 8:
            raise ValueError("Invalid archived article round")
        archives[path.stem] = payload
    new = {}
    for session in ordered:
        key = storage_id(session)
        if key not in archives:
            payload = make_payload(root, session, items, archives, repo)
            archives[key] = payload
            new[key] = payload
    latest = archives[storage_id(ordered[-1])]
    # Validate and render everything before touching any published page.
    pages = {key: render_page(root, payload) for key, payload in archives.items()}
    links = []
    for key, payload in sorted(archives.items(), key=lambda pair: (pair[1]["date"], pair[0]), reverse=True):
        label = payload["article_session"]["source"] + " · " + key
        links.append(f'<li><a href="article-review-{html.escape(key)}.html">{html.escape(label)}</a></li>')
    index = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>历史文章复盘</title><body><h1>历史文章复盘</h1><p><a href="article-review.html">最新复盘</a> · <a href="./">总训练站</a></p><ul>' + ''.join(links) + '</ul></body></html>'
    for key, payload in new.items():
        review.save(root / f"data/article-reviews/{key}.json", payload)
    for key, page in pages.items():
        (root / f"article-review-{key}.html").write_text(page, encoding="utf-8")
    review.save(root / "data/article-review.json", latest)
    (root / "article-review.html").write_text(pages[latest["storageId"]], encoding="utf-8")
    (root / "article-reviews.html").write_text(index, encoding="utf-8")
    return latest


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>文章复盘8题 · 考研英语</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6fb;color:#192336;font-family:system-ui,"Microsoft YaHei",sans-serif}main{max-width:900px;margin:auto;padding:20px}h1{font-size:23px;margin:0 0 8px}.card{background:white;border:1px solid #e3e7ef;border-radius:16px;padding:22px;margin:16px 0}.muted{color:#667085;font-size:14px;line-height:1.6}.target{display:inline-block;padding:8px 12px;background:#eef2ff;color:#3045a0;border-radius:12px;font-weight:700}.sentence{white-space:pre-wrap;font-size:19px;line-height:1.8;margin:18px 0}.choices{display:grid;gap:10px}button,a.button{border:1px solid #dfe4ee;border-radius:10px;padding:12px 16px;background:#fff;color:#172033;font:inherit;cursor:pointer;text-decoration:none}button:hover,a.button:hover{border-color:#3157d5}button:focus-visible,a:focus-visible{outline:3px solid #f59e0b;outline-offset:3px}button:disabled{cursor:default}.choice{text-align:left;line-height:1.6}.primary{background:#3157d5;color:white}.good{background:#e9f9ef}.bad{background:#fff0ee}.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}.explanation{line-height:1.8;white-space:pre-wrap}.explanation h3{font-size:16px;margin:15px 0 3px}.hidden{display:none!important}.notice{padding:10px;background:#fff7e6;line-height:1.6}.review{border-top:1px solid #e4e7ee;padding-top:18px;margin-top:18px}@media(max-width:600px){main{padding:12px}.card{padding:16px}.sentence{font-size:17px}}
</style></head><body>__CORRECTIONS__<main id="app"></main><p style="max-width:900px;margin:auto;padding:0 20px"><a href="./article-reviews.html">历史文章复盘</a></p><noscript>请启用浏览器JavaScript后做题。</noscript>
<script>window.REVIEW_DATA=__DATA__;</script><script src="./web/review.js?v=__VERSION__"></script></body></html>"""


if __name__ == "__main__":
    result = build()
    print(json.dumps({"session": result["article_session"]["id"] if result else None,
                      "questions": len(result["questions"]) if result else 0}, ensure_ascii=False))
