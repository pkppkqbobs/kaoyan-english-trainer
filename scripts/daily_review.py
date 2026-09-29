"""Build the daily quiz with stdlib only; never execute issue text or call a paid API."""
from __future__ import annotations
import argparse
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import random
import re
import shutil
import time
from datetime import date, datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
EXP_KEYS = ("trans", "structure", "other", "meaning", "rest")
STRUCTURE = {"nested", "relative", "with"}
ALIASES = {
    "subject": ("subject",), "reference": ("these", "such", "回指", "原词复现"),
    "relative": ("which", "whom", "介词 +", "preposition"),
    "nested": ("who 定语", "从句边界"), "unpretentious": ("unpretentious",),
    "faint": ("faint",), "point": ("miss the point", "point 熟词"),
    "even": ("even",), "account": ("account",), "with": ("with +",),
    "compromise": ("compromise",), "standard": ("standard",),
    "remote": ("remote",), "conceivably": ("conceivably",), "tone": ("tone",),
    "conditions": ("so long as", "in case"), "end-up": ("end up",),
}


def load(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else copy.deepcopy(default)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical(label):
    label = label.lower().strip()
    for family, names in ALIASES.items():
        if label == family or any(name.lower() in label for name in names):
            return family
    return label


def validate(q):
    assert isinstance(q, dict), "Question must be an object"
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,100}", q["id"]), q.get("id")
    assert isinstance(q["family"], str) and q["family"], q["id"]
    assert isinstance(q["q"], str) and len(q["q"]) > 12, q["id"]
    assert isinstance(q["target"], str) and q["target"], q["id"]
    assert len(q["o"]) == 4 and len(set(q["o"])) == 4, q["id"]
    assert all(isinstance(x, str) and x for x in q["o"]), q["id"]
    assert type(q["a"]) is int and 0 <= q["a"] < 4, q["id"]
    assert all(isinstance(q["exp"].get(k), str) and q["exp"][k].strip() for k in EXP_KEYS), q["id"]
    if q.get("introduced"):
        date.fromisoformat(q["introduced"])
    return q


def bank(root):
    """Import the existing JSON bank once, without importing its mismatched RETRY explanations."""
    base = root / "data/base-bank.json"
    if not base.exists():
        old = (root / "today.html").read_text(encoding="utf-8")
        marker = "const BANK = "
        if marker not in old:
            raise ValueError("Bootstrap expects the existing JSON BANK; refusing to overwrite an unknown page")
        imported, _ = json.JSONDecoder().raw_decode(old.split(marker, 1)[1].lstrip())
        items = []
        for q in imported:
            # The old refund-verification sentence could permit both subject forms.
            if q["id"] == "subject":
                continue
            q = copy.deepcopy(q)
            q["family"] = canonical(q["skill"])
            q["introduced"] = "2026-09-29" if q.get("source") == "today" else None
            q["id"] = "legacy-" + q["id"]
            q["budget"] = 60 if q["family"] in STRUCTURE else 35
            # Correct the old passive/continuous predicate labels.
            if q["family"] == "point":
                q["exp"]["structure"] = "第一句：The committee（主语）+ spent（谓语）+ twenty minutes（宾语）；arguing...说明时间花在何事上。while连接对比；whether the bridge was safe作表语从句。第二句：They（主语）+ were missing（现在进行时谓语）+ the point（宾语）。"
            if q["family"] == "faint":
                q["exp"]["structure"] = "Maya（主语）+ said（谓语）+ 引语（内容）。问句 Her remark is best described as... 中 is described是被动谓语，不是is加形容词表语。引语主干为the slides were readable；at least限制了肯定的力度。"
            items.append(validate(q))
        archive = root / "archive/2026-09-29-before-automation.html"
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            archive.write_text(old, encoding="utf-8")
        save(base, items)
    items = load(base, [])
    for path in sorted((root / "data/questions").glob("*.json")):
        extra = load(path)
        if not isinstance(extra, list):
            raise ValueError(f"{path} must contain a question array")
        items += extra
    ids, stems = set(), set()
    for q in items:
        validate(q)
        if q["id"] in ids or q["q"] in stems:
            raise ValueError("Duplicate question id or exact stem: " + q["id"])
        ids.add(q["id"])
        stems.add(q["q"])
    if len({q["family"] for q in items}) < 8:
        raise ValueError("At least eight target families are required")
    return items


def get_issues(repo):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "kaoyan-daily-review"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    all_issues = []
    for page in range(1, 101):
        url = f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100&page={page}"
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers=headers), timeout=30) as response:
                    batch = json.load(response)
                break
            except (HTTPError, URLError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        if not isinstance(batch, list):
            raise ValueError("Unexpected issues response")
        all_issues.extend(batch)
        if len(batch) < 100:
            return all_issues
    raise RuntimeError("Issue pagination limit reached; refusing a partial history")


def parse_issue(issue):
    """Return one report id and evidence rows. Aggregate-only reports do not fabricate item order."""
    body = issue.get("body") or ""
    stamp = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
    title_date = re.search(r"\d{4}-\d{2}-\d{2}", issue.get("title", ""))
    if title_date:
        stamp = title_date.group()
    structured = re.search(r"<!-- review-json:v3\s*\n(.*?)\n-->", body, re.S)
    if structured:
        obj = json.loads(structured.group(1))
        date.fromisoformat(obj["date"])
        rows = []
        for row in obj["answers"]:
            if type(row.get("ok")) is not bool or not isinstance(row.get("ms"), (int, float)):
                raise ValueError("Malformed structured answer")
            if row.get("kind", "main") != "main":
                continue
            rows.append({"date": obj["date"], "family": canonical(row["family"]), "ok": row["ok"],
                         "ms": max(0, min(row["ms"], 3600000)), "uncertain": bool(row.get("uncertain")), "origin": issue["number"]})
        return str(obj["roundId"]), rows
    rows, detailed = [], set()
    for line in body.splitlines():
        match = re.match(r"Q\d+\s+(?:\[[^\]]+\]\s*)?(.+?)：选([ABCD])→正确([ABCD])；.*?([0-9.]+)s\s*$", line)
        if match:
            family = canonical(match[1])
            detailed.add(family)
            rows.append({"date": stamp, "family": family, "ok": match[2] == match[3], "ms": float(match[4]) * 1000, "uncertain": False, "origin": issue["number"]})
    for line in body.splitlines():
        match = re.match(r"(.+?)：(\d+)/(\d+)，平均\s*([0-9.]+)s", line)
        if match:
            family = canonical(match[1])
            if family not in detailed:
                rows.append({"date": stamp, "family": family, "ok": int(match[2]) == int(match[3]), "ms": float(match[4]) * 1000,
                             "uncertain": int(match[3]) > 1, "aggregate": True, "origin": issue["number"]})
    return "legacy-issue-" + str(issue["number"]), rows


def evidence(issues, owner):
    rows, seen, accepted = [], set(), []
    for issue in sorted(issues, key=lambda x: x.get("created_at", "")):
        if issue.get("pull_request") or issue.get("user", {}).get("login", "").lower() != owner.lower():
            continue
        if not issue.get("title", "").startswith("[TRAINING_RESULT]"):
            continue
        if "<!-- kaoyan-english-training-result -->" not in (issue.get("body") or ""):
            continue
        report_id, report_rows = parse_issue(issue)
        if report_id in seen:
            continue
        seen.add(report_id)
        rows.extend(report_rows)
        accepted.append(issue["number"])
    return rows, accepted


def make_stats(items, rows, notes, day):
    result = {}
    for family in {q["family"] for q in items}:
        per_day = {}
        threshold = max(q.get("budget", 60 if family in STRUCTURE else 35) for q in items if q["family"] == family) * 1000
        for row in rows:
            if row["family"] == family and row["date"] <= day.isoformat():
                per_day.setdefault(row["date"], []).append(row)
        streak, errors, slow = 0, 0, False
        last = None
        for stamp in sorted(per_day):
            observations = per_day[stamp]
            ok = all(x["ok"] for x in observations)
            slow = any(x["ms"] > threshold or x.get("uncertain") for x in observations)
            errors += sum(not x["ok"] for x in observations)
            streak = streak + 1 if ok and not slow else 0
            last = stamp
        # Chat observations are evidence of confusion, not fictitious scored attempts.
        active_notes = [n for n in notes if n["family"] == family and n["date"] <= day.isoformat() and (not last or n["date"] >= last)]
        if active_notes:
            streak = 0
        interval = [1, 2, 4, 7, 14, 21][min(streak, 5)]
        due = (date.fromisoformat(last) + timedelta(days=interval)).isoformat() if last else day.isoformat()
        if active_notes:
            due = min(due, day.isoformat())
        result[family] = {"streak": streak, "errors": errors, "last": last, "due": due,
                          "slow_or_uncertain": slow, "reported_confusion": bool(active_notes), "observed_days": len(per_day)}
    return result


def choose(items, stats, history, day):
    rng = random.Random("kaoyan-review:" + day.isoformat())
    groups = {}
    for q in items:
        if not q.get("introduced") or q["introduced"] <= day.isoformat():
            groups.setdefault(q["family"], []).append(q)
    def age(f):
        dates = [q.get("introduced") for q in groups[f]]
        return 9999 if None in dates else (day - date.fromisoformat(min(dates))).days
    last_shown, exposure = {}, {}
    for stamp, ids in history.items():
        if stamp >= day.isoformat():
            continue
        for qid in ids:
            last_shown[qid] = max(stamp, last_shown.get(qid, ""))
            if (day - date.fromisoformat(stamp)).days <= 3:
                for f, variants in groups.items():
                    if any(q["id"] == qid for q in variants):
                        exposure[f] = exposure.get(f, 0) + 1
    def rank(f):
        s = stats[f]
        overdue = max(0, (day - date.fromisoformat(s["due"])).days)
        weight = (3 + min(s["errors"], 4) * 3 + 5 * s["reported_confusion"] + 2 * s["slow_or_uncertain"] + min(overdue, 10)) / (1 + exposure.get(f, 0))
        return (s["due"] <= day.isoformat(), weight + rng.random())
    ranked = sorted(groups, key=rank, reverse=True)
    chosen = []
    def allowed(f):
        return f not in chosen and (f not in STRUCTURE or sum(x in STRUCTURE for x in chosen) < 2) and (age(f) != 0 or sum(age(x) == 0 for x in chosen) < 2)
    def take(count, predicate):
        for f in ranked:
            if count <= 0 or len(chosen) == 8:
                return
            if allowed(f) and predicate(f):
                chosen.append(f)
                count -= 1
    take(1, lambda f: f in STRUCTURE)
    take(max(0, 3 - sum(age(f) > 3 for f in chosen)), lambda f: age(f) > 3)
    take(2, lambda f: 1 <= age(f) <= 3)
    take(1, lambda f: stats[f]["streak"] >= 2 and stats[f]["due"] <= day.isoformat())
    take(8 - len(chosen), lambda f: stats[f]["due"] <= day.isoformat())
    take(8 - len(chosen), lambda f: True)
    if len(chosen) != 8:
        raise ValueError("Insufficient diverse questions; old page retained instead of publishing an invalid quiz")
    for _ in range(100):
        rng.shuffle(chosen)
        if all(not (age(a) == 0 and age(b) == 0) for a, b in zip(chosen, chosen[1:])):
            break
    selected = []
    for f in chosen:
        variants = groups[f][:]
        rng.shuffle(variants)
        variants.sort(key=lambda q: last_shown.get(q["id"], ""))
        selected.append(copy.deepcopy(variants[0]))
    return selected


def build(root, day, sync=False, repo="pkppkqbobs/kaoyan-english-trainer"):
    items = bank(root)
    if sync:
        rows, accepted = evidence(get_issues(repo), repo.split("/")[0])
        save(root / "data/result-evidence.json", {"rows": rows, "issues": accepted})
    evidence_data = load(root / "data/result-evidence.json", {"rows": [], "issues": []})
    notes = load(root / "data/learning-notes.json", [])
    stats = make_stats(items, evidence_data["rows"], notes, day)
    unmapped = sorted({r["family"] for r in evidence_data["rows"]} - set(stats))
    save(root / "data/review-state.json", {"as_of": day.isoformat(), "issues": evidence_data["issues"], "families": stats, "unmapped_targets": unmapped})
    history = load(root / "data/daily-history.json", {})
    existing = load(root / "data/daily.json", {})
    # A submitted result or an evening bank expansion must not replace a quiz mid-session.
    if existing.get("date") == day.isoformat():
        payload = existing
    else:
        selected = choose(items, stats, history, day)
        payload = {"date": day.isoformat(), "repo": repo, "questions": selected,
                   "retry": {q["family"]: [v for v in items if v["family"] == q["family"] and v["id"] != q["id"]] for q in selected},
                   "issues_used": evidence_data["issues"], "engine": 3}
        history[day.isoformat()] = [q["id"] for q in selected]
        save(root / "data/daily-history.json", history)
    payload["issues_used"] = evidence_data["issues"]
    save(root / "data/daily.json", payload)
    save(root / f"data/days/{day.isoformat()}.json", payload)
    script = root / "web/review.js"
    version = hashlib.sha256(script.read_bytes()).hexdigest()[:12]
    embedded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    page = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>今日定制8题 · 考研英语</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6fb;color:#192336;font-family:system-ui,"Microsoft YaHei",sans-serif}main{max-width:900px;margin:auto;padding:20px}h1{font-size:23px;margin:0 0 8px}.card{background:white;border:1px solid #e3e7ef;border-radius:16px;padding:22px;margin:16px 0}.muted{color:#667085;font-size:14px;line-height:1.6}.target{display:inline-block;padding:8px 12px;background:#eef2ff;color:#3045a0;border-radius:12px;font-weight:700}.sentence{white-space:pre-wrap;font-size:19px;line-height:1.8;margin:18px 0}.choices{display:grid;gap:10px}button,a.button{border:1px solid #dfe4ee;border-radius:10px;padding:12px 16px;background:#fff;color:#172033;font:inherit;cursor:pointer;text-decoration:none}button:hover,a.button:hover{border-color:#3157d5}button:focus-visible,a:focus-visible{outline:3px solid #f59e0b;outline-offset:3px}button:disabled{cursor:default}.choice{text-align:left;line-height:1.6}.primary{background:#3157d5;color:white}.good{background:#e9f9ef}.bad{background:#fff0ee}.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}.explanation{line-height:1.8;white-space:pre-wrap}.explanation h3{font-size:16px;margin:15px 0 3px}.hidden{display:none!important}.notice{padding:10px;background:#fff7e6;line-height:1.6}.review{border-top:1px solid #e4e7ee;padding-top:18px;margin-top:18px}@media(max-width:600px){main{padding:12px}.card{padding:16px}.sentence{font-size:17px}}
</style></head><body><main id="app"></main><noscript>请启用浏览器JavaScript后做题。</noscript>
<script>window.REVIEW_DATA=__DATA__;</script><script src="./web/review.js?v=__VERSION__"></script></body></html>'''
    (root / "today.html").write_text(page.replace("__DATA__", embedded).replace("__VERSION__", version), encoding="utf-8")
    site = root / "_site"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir()
    for p in root.iterdir():
        if p.is_file() and p.suffix in {".html", ".css", ".js", ".png", ".svg", ".ico"}:
            shutil.copy2(p, site / p.name)
    for directory in ("web", "archive"):
        if (root / directory).exists():
            shutil.copytree(root / directory, site / directory)
    (site / ".nojekyll").touch()
    print(json.dumps({"date": day.isoformat(), "questions": len(payload["questions"]), "bank_size": len(items), "families": len(stats), "issues_used": evidence_data["issues"], "unmapped_targets": unmapped}, ensure_ascii=False))
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--date", default=datetime.now(TZ).date().isoformat())
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "pkppkqbobs/kaoyan-english-trainer"))
    args = parser.parse_args()
    build(ROOT, date.fromisoformat(args.date), args.sync, args.repo)
