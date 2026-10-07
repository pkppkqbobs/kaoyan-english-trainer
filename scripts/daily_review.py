"""Build the daily quiz with stdlib only; never execute issue text or call a paid API."""
from __future__ import annotations
import argparse
import copy
import hashlib
import html
import json
import math
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
    "logic": ("because / unless", "整句逻辑"),
    "transition": ("similarly / conversely",),
    "parallel-governance": ("共同动词支配",),
    "summary-location": ("总结词定位",),
    "result-direction": ("result from", "result in"),
    "have-little-use-for": ("have little use for",),
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
    if q.get("published_on"):
        date.fromisoformat(q["published_on"])
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
    # Maintenance metadata affects variant spacing only, never scoring or learning dates.
    contexts = load(root / "data/question-contexts.json", {}).get("contexts", {})
    for q in items:
        if q["id"] in contexts:
            q["context_id"] = contexts[q["id"]]
    return items


def available(q, day):
    stamp = day.isoformat() if isinstance(day, date) else day
    return all(not q.get(field) or q[field] <= stamp for field in ("introduced", "published_on"))


def variant_history(root, day, daily=None):
    """Published article/passage rounds inform qid spacing, not family priority."""
    history = {stamp: list(ids) for stamp, ids in (daily or {}).items() if stamp <= day.isoformat()}
    for path in sorted((root / "data/article-reviews").glob("*.json")):
        payload = load(path)
        if payload["date"] <= day.isoformat():
            history.setdefault(payload["date"], []).extend(q["id"] for q in payload["questions"])
    for path in sorted(root.glob("passage-drill-*.html")):
        text = path.read_text(encoding="utf-8")
        if "window.REVIEW_DATA=" in text:
            payload, _ = json.JSONDecoder().raw_decode(text.split("window.REVIEW_DATA=", 1)[1].lstrip())
            if payload["date"] <= day.isoformat():
                history.setdefault(payload["date"], []).extend(q["id"] for q in payload["questions"])
    return {stamp: sorted(set(ids)) for stamp, ids in history.items()}


def choose_variant(variants, history, rng, *, avoid_ids=(), prefer_date=None):
    variants = list(variants)
    all_contexts = {q["id"]: q.get("context_id", q["id"]) for q in variants}
    rng.shuffle(variants)
    unseen = [q for q in variants if q["id"] not in avoid_ids]
    variants = unseen or variants
    if prefer_date:
        dated = [q for q in variants if q.get("introduced") == prefer_date]
        variants = dated or variants
    last_shown, context_last = {}, {}
    # Include avoided variants when measuring context exposure; a new qid with the
    # same evidence path must not appear unseen simply because its sibling was used.
    for stamp, ids in history.items():
        for qid in ids:
            last_shown[qid] = max(stamp, last_shown.get(qid, ""))
            if qid in all_contexts:
                ctx = all_contexts[qid]
                context_last[ctx] = max(stamp, context_last.get(ctx, ""))
    return copy.deepcopy(min(variants, key=lambda q: (context_last.get(q.get("context_id", q["id"]), ""),
                                                       last_shown.get(q["id"], ""))))


def retry_variants(items, question, day):
    """Different qids are not automatically a fresh migration context."""
    context = question.get("context_id", question["id"])
    return [copy.deepcopy(q) for q in items if q["family"] == question["family"]
            and q["id"] != question["id"] and available(q, day)
            and q.get("context_id", q["id"]) != context]


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


def published_question(root, report, qid):
    """Resolve the immutable published question, not today's mutable source bank."""
    module, storage_id = report.get("module"), report.get("storageId")
    payloads = []
    if module is not None or storage_id is not None:
        if module not in {"daily", "article", "passage"} or not isinstance(storage_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", storage_id):
            raise ValueError("Invalid multiple-choice module/storageId")
        if module == "daily":
            if storage_id != report["date"]:
                raise ValueError("Daily storageId differs from its published date")
            payloads = [load(root / f"data/days/{storage_id}.json", {})]
        elif module == "article":
            payloads = [load(root / f"data/article-reviews/{storage_id}.json", {})]
    else:
        payloads = [load(root / f"data/days/{report['date']}.json", {})]
        payloads += [load(p) for p in sorted((root / "data/article-reviews").glob("*.json"))]
    if module in (None, "passage"):
        for path in sorted(root.glob("passage-drill-*.html")):
            text = path.read_text(encoding="utf-8")
            if "window.REVIEW_DATA=" not in text:
                continue
            payload, _ = json.JSONDecoder().raw_decode(text.split("window.REVIEW_DATA=", 1)[1].lstrip())
            if module is None or payload.get("storageId", payload["date"]) == storage_id:
                payloads.append(payload)
    matches = [q for p in payloads if p.get("date") == report["date"]
               for q in p.get("questions", []) if q["id"] == qid]
    definitions = {(q["family"], tuple(q["o"]), q["a"]) for q in matches}
    if len(definitions) != 1:
        raise ValueError("Unknown or ambiguous published question; refresh its original training page")
    return matches[0]


def issue_report_day(issue):
    """Bound an edited report by its server revision time, not its initial creation."""
    stamps = [issue["created_at"], issue.get("updated_at") or issue["created_at"]]
    moments = [datetime.fromisoformat(stamp.replace("Z", "+00:00")) for stamp in stamps]
    if any(moment.tzinfo is None for moment in moments):
        raise ValueError("GitHub report timestamps must include a timezone")
    return max(moments).astimezone(TZ).date()


def parse_issue(issue, root=ROOT):
    """Return one report id and evidence rows. Aggregate-only reports do not fabricate item order."""
    body = issue.get("body") or ""
    stamp = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
    title_date = re.search(r"\d{4}-\d{2}-\d{2}", issue.get("title", ""))
    if title_date:
        stamp = title_date.group()
    issue_day = issue_report_day(issue)
    markers = re.findall(r"<!--\s*review-json:(v\d+)", body)
    if markers and (len(markers) != 1 or markers[0] not in {"v3", "v4"}):
        raise ValueError("Ambiguous or unsupported structured report")
    ordering = re.search(r"<!-- review-json:v4\s*\n(.*?)\n-->", body, re.S)
    if markers == ["v4"] and not ordering:
        raise ValueError("Incomplete review-json:v4 block")
    if ordering:
        from partb_review import parse_report
        return parse_report(json.loads(ordering.group(1)), issue, root)
    structured = re.search(r"<!-- review-json:v3\s*\n(.*?)\n-->", body, re.S)
    if markers == ["v3"] and not structured:
        raise ValueError("Incomplete review-json:v3 block")
    if structured:
        obj = json.loads(structured.group(1))
        if not isinstance(obj, dict) or obj.get("version", 3) != 3:
            raise ValueError("Malformed review-json:v3 object")
        if not isinstance(obj.get("roundId"), str) or not obj["roundId"].strip():
            raise ValueError("Malformed structured report id")
        if not isinstance(obj.get("answers"), list):
            raise ValueError("Malformed structured answers")
        paper_day = date.fromisoformat(obj["date"])
        if paper_day > issue_day:
            raise ValueError("Report cannot claim a future learning date")
        rows, qids = [], set()
        for row in obj["answers"]:
            if not isinstance(row, dict):
                raise ValueError("Malformed structured answer")
            kind = row.get("kind", "main")
            if kind not in {"main", "retry"}:
                raise ValueError("Unknown structured answer kind")
            if kind != "main":
                continue
            if not isinstance(row.get("family"), str) or not row["family"].strip():
                raise ValueError("Malformed structured family")
            if "qid" in row and (not isinstance(row["qid"], str) or not row["qid"].strip()):
                raise ValueError("Malformed structured question id")
            family = canonical(row["family"])
            if row.get("qid") and row["qid"] in qids:
                raise ValueError("Duplicate main question in one report")
            if row.get("qid"):
                qids.add(row["qid"])
            if type(row.get("pick")) is not int or not 0 <= row["pick"] < 4:
                raise ValueError("Malformed structured choice")
            if type(row.get("expected")) is not int or not 0 <= row["expected"] < 4:
                raise ValueError("Malformed structured answer key")
            if type(row.get("ok")) is not bool:
                raise ValueError("Malformed structured correctness flag")
            verified = "optionOrder" in row or "pickText" in row or "expectedText" in row
            if (obj.get("module") is not None or obj.get("storageId") is not None) and not verified:
                raise ValueError("Published-page report must include its saved option permutation/text")
            ok = row["pick"] == row["expected"]
            if verified:
                q = published_question(root, obj, row.get("qid"))
                if canonical(q["family"]) != family:
                    raise ValueError("Reported family differs from the published question")
                if "optionOrder" in row:
                    order = row["optionOrder"]
                    if not isinstance(order, list) or len(order) != 4 or any(type(x) is not int for x in order) or set(order) != set(range(4)):
                        raise ValueError("Malformed option permutation")
                    if row["expected"] != order.index(q["a"]):
                        raise ValueError("Supplied answer key differs from the published key")
                    ok = order[row["pick"]] == q["a"]
                else:
                    if row.get("pickText") not in q["o"] or row.get("expectedText") != q["o"][q["a"]]:
                        raise ValueError("Choice text differs from the published options/key")
                    ok = row["pickText"] == q["o"][q["a"]]
                    if ok != (row["pick"] == row["expected"]):
                        raise ValueError("Choice text contradicts the saved first indices")
            elif row["ok"] != ok:
                # Historical v3 reports did not save the shuffled option order.
                # Keep their original evidence; never invent a missing permutation.
                raise ValueError("Structured answer does not match its choice and key")
            if "uncertain" in row and type(row["uncertain"]) is not bool:
                raise ValueError("Malformed uncertain flag")
            if type(row.get("ms")) not in (int, float) or not math.isfinite(row["ms"]) or not 0 <= row["ms"] <= 3600000:
                raise ValueError("Malformed answer time")
            unknown_day = verified and "answeredOn" not in row
            answered_day = issue_day if unknown_day else date.fromisoformat(row.get("answeredOn", obj["date"]))
            if not paper_day <= answered_day <= issue_day:
                raise ValueError("Answer date is outside publication/submission dates")
            parsed = {"date": answered_day.isoformat(), "family": family,
                      "ok": ok, "ms": row["ms"],
                      "uncertain": row.get("uncertain", False), "origin": issue["number"]}
            if "qid" in row:
                parsed["qid"] = row["qid"]
            if verified:
                parsed["round_id"] = obj["roundId"]
                parsed["source_date"] = obj["date"]
                if unknown_day:
                    # Submission is a known date; the original answer day is not.
                    # This can inform review, but never adds a mastery day.
                    parsed["date_unverified"] = True
            rows.append(parsed)
        if (obj.get("module") is not None or obj.get("storageId") is not None) and not rows:
            raise ValueError("Published-page report contains no primary answers")
        return str(obj["roundId"]), rows
    if date.fromisoformat(stamp) > issue_day:
        raise ValueError("Legacy report cannot claim a future learning date")
    rows, detailed = [], set()
    for line in body.splitlines():
        match = re.match(r"Q\d+\s+(?:\[[^\]]+\]\s*)?(.+?)：选([ABCD])→正确([ABCD])；.*?([0-9.]+)s\s*$", line)
        if match:
            family = canonical(match[1])
            detailed.add(family)
            rows.append({"date": stamp, "family": family, "ok": match[2] == match[3], "ms": float(match[4]) * 1000,
                         "uncertain": bool(re.search(r"不确定|猜答|猜对|蒙", line)), "origin": issue["number"]})
    for line in body.splitlines():
        match = re.match(r"(.+?)：(\d+)/(\d+)，平均\s*([0-9.]+)s", line)
        if match:
            family = canonical(match[1])
            if family not in detailed:
                correct, attempts = int(match[2]), int(match[3])
                if attempts <= 0 or correct < 0 or correct > attempts:
                    raise ValueError("Malformed aggregate result")
                rows.append({"date": stamp, "family": family, "ok": correct == attempts, "ms": float(match[4]) * 1000,
                             "uncertain": bool(re.search(r"不确定|猜答|猜对|蒙", line)), "aggregate": True,
                             "attempts": attempts, "errors": attempts - correct, "origin": issue["number"]})
    return "legacy-issue-" + str(issue["number"]), rows


def evidence(issues, owner, root=ROOT, *, rejected=None, fallback=None):
    rows, seen, accepted = [], set(), []
    for issue in sorted(issues, key=lambda x: (x.get("created_at", ""), x.get("number", 0))):
        if issue.get("pull_request") or issue.get("user", {}).get("login", "").lower() != owner.lower():
            continue
        if not issue.get("title", "").startswith("[TRAINING_RESULT]"):
            continue
        if "<!-- kaoyan-english-training-result -->" not in (issue.get("body") or ""):
            continue
        try:
            report_id, report_rows = parse_issue(issue, root)
            if not report_rows and (fallback or {}).get(issue["number"]):
                raise ValueError("Previously scored report no longer contains primary answers")
        except (ValueError, KeyError, TypeError, AttributeError, AssertionError) as error:
            if rejected is None:
                raise
            retained = issue["number"] in (fallback or {})
            rejected.append({"issue": issue["number"], "reason": str(error), "retained_previous": retained})
            if retained:
                seen.update(r["round_id"] for r in fallback[issue["number"]] if r.get("round_id"))
                rows.extend(copy.deepcopy(fallback[issue["number"]]))
                accepted.append(issue["number"])
            continue
        if report_id in seen:
            continue
        seen.add(report_id)
        rows.extend(report_rows)
        accepted.append(issue["number"])
    return rows, accepted


NOTE_PRIORITIES = {"user_reported_wrong": 3, "correct_but_uncertain": 2,
                   "user_reported_confusion": 2, "translation_difficulty": 1}


def note_priority(note):
    """An observation affects scheduling, never the scored attempt/error counters."""
    if note.get("review_importance") == "low":
        return 0.25
    return NOTE_PRIORITIES.get(note.get("kind"), 2)


def make_stats(items, rows, notes, day):
    result = {}
    for family in sorted({q["family"] for q in items}):
        per_day = {}
        threshold = max(q.get("budget", 60 if family in STRUCTURE else 35) for q in items if q["family"] == family) * 1000
        for row in rows:
            if row["family"] == family and row["date"] <= day.isoformat():
                per_day.setdefault(row["date"], []).append(row)
        streak, errors, slow = 0, 0, False
        last = None
        for stamp in sorted(per_day):
            observations = per_day[stamp]
            day_errors = sum(x.get("errors", int(not x["ok"])) for x in observations)
            ok = day_errors == 0
            day_slow = any(x["ms"] > x.get("slow_threshold_ms", threshold) or x.get("uncertain", False) for x in observations)
            errors += day_errors
            slow = slow or day_slow
            known_day = any(not x.get("date_unverified") for x in observations)
            if not ok or day_slow:
                streak = 0
            elif known_day:
                streak += 1
            if known_day or not ok or day_slow:
                last = stamp
        # Chat observations are evidence of confusion, not fictitious scored attempts.
        family_notes = [n for n in notes if n["family"] == family and n["date"] <= day.isoformat()]
        latest_note = max((n["date"] for n in family_notes), default=None)
        clear_days = 0
        if latest_note:
            for stamp in sorted(per_day):
                if stamp <= latest_note:
                    continue
                observations = per_day[stamp]
                day_errors = sum(x.get("errors", int(not x["ok"])) for x in observations)
                day_slow = any(x["ms"] > x.get("slow_threshold_ms", threshold) or x.get("uncertain", False) for x in observations)
                if not any(not x.get("date_unverified") for x in observations):
                    if day_errors or day_slow:
                        clear_days = 0
                    continue
                clear_days = clear_days + 1 if day_errors == 0 and not day_slow else 0
        active_notes = bool(family_notes and clear_days < 2)
        if active_notes:
            streak = 0
        interval = [1, 2, 4, 7, 14, 21][min(streak, 5)]
        due = (date.fromisoformat(last) + timedelta(days=interval)).isoformat() if last else day.isoformat()
        if active_notes:
            due = min(due, day.isoformat())
        result[family] = {"streak": streak, "errors": errors, "last": last, "due": due,
                          "slow_or_uncertain": slow, "reported_confusion": active_notes,
                          "observed_days": sum(any(not x.get("date_unverified") for x in group) for group in per_day.values()),
                          "observation_priority": max((note_priority(n) for n in family_notes), default=0) if active_notes else 0}
    return result


def choose(items, stats, history, day, *, count=8, seed=None, include_today=False, variant_shown=None):
    """Select directly from the candidate pool; article reviews request 4--6 slots."""
    if not 1 <= count <= 8:
        raise ValueError("Review count must be between one and eight")
    rng = random.Random(seed or "kaoyan-review:" + day.isoformat())
    groups = {}
    for q in items:
        if available(q, day):
            groups.setdefault(q["family"], []).append(q)
    def age(f):
        dates = [q.get("introduced") for q in groups[f]]
        return 9999 if None in dates else (day - date.fromisoformat(min(dates))).days
    last_shown, exposure = {}, {}
    for stamp, ids in history.items():
        if stamp > day.isoformat() or (stamp == day.isoformat() and not include_today):
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
        note_weight = s.get("observation_priority", 2) / 2 if s["reported_confusion"] else 0
        stable = 1 + s["streak"] if s["streak"] >= 2 and not s["reported_confusion"] else 1
        weight = (3 + (min(s["errors"], 4) * 3 + 2 * s["slow_or_uncertain"]) / stable
                  + 5 * note_weight + min(overdue, 10)) / (1 + exposure.get(f, 0))
        return (s["due"] <= day.isoformat(), weight + rng.random())
    def urgent_rank(f):
        s = stats[f]
        overdue = max(0, (day - date.fromisoformat(s["due"])).days)
        # A weak family must not disappear behind a large pool of merely due items.
        # Errors are strongest evidence; explicit confusion and slow/uncertain answers
        # remain high priority even after a later same-day or next-day correct answer.
        note_weight = s.get("observation_priority", 2) / 2 if s["reported_confusion"] else 0
        stable = 1 + s["streak"] if s["streak"] >= 2 and not s["reported_confusion"] else 1
        return ((min(s["errors"], 4) * 8 + 12 * bool(s["slow_or_uncertain"])) / stable
                + 9 * note_weight + min(overdue, 10)
                - min(exposure.get(f, 0) * 0.5, 2) + rng.random())
    ranked = sorted(groups, key=rank, reverse=True)
    urgent = sorted(groups, key=urgent_rank, reverse=True)
    chosen = []
    def allowed(f):
        # Full ordering belongs in the independent Part B page; at most one mini pair
        # maintains these two families in an ordinary multiple-choice round.
        partb_slot = not f.startswith("paragraph-order-") or not any(x.startswith("paragraph-order-") for x in chosen)
        return partb_slot and f not in chosen and (f not in STRUCTURE or sum(x in STRUCTURE for x in chosen) < 2) and (age(f) != 0 or sum(age(x) == 0 for x in chosen) < 2)
    def take(count, predicate, order=None):
        for f in (order or ranked):
            if count <= 0 or len(chosen) == requested:
                return
            if allowed(f) and predicate(f):
                chosen.append(f)
                count -= 1
    requested = count
    take(min(4, max(1, requested - 2)), lambda f: (stats[f]["due"] <= day.isoformat()
                       and (stats[f]["errors"] > 0 or stats[f]["reported_confusion"] or stats[f]["slow_or_uncertain"])), urgent)
    # Keep one slot for a weak family that has been overdue for several days.
    # Without this reserve, a large cluster of newer mistakes can repeatedly
    # displace older slow/uncertain targets such as subject/long-term grammar.
    take(1, lambda f: ((day - date.fromisoformat(stats[f]["due"])).days >= 2
                       and (stats[f]["errors"] > 0 or stats[f]["slow_or_uncertain"] or stats[f]["reported_confusion"])), urgent)
    take(1, lambda f: f in STRUCTURE)
    take(max(0, 3 - sum(age(f) > 3 for f in chosen)), lambda f: age(f) > 3)
    take(2, lambda f: 1 <= age(f) <= 3)
    take(1, lambda f: stats[f]["streak"] >= 2 and stats[f]["due"] <= day.isoformat())
    take(requested - len(chosen), lambda f: stats[f]["due"] <= day.isoformat())
    take(requested - len(chosen), lambda f: True)
    if len(chosen) != requested:
        raise ValueError("Insufficient diverse questions; old page retained instead of publishing an invalid quiz")
    for _ in range(100):
        rng.shuffle(chosen)
        if all(not (age(a) == 0 and age(b) == 0) for a, b in zip(chosen, chosen[1:])):
            break
    selected = []
    for f in chosen:
        shown = {stamp: ids for stamp, ids in (variant_shown if variant_shown is not None else history).items()
                 if stamp < day.isoformat() or (stamp == day.isoformat() and include_today)}
        selected.append(choose_variant(groups[f], shown, rng))
    return selected


def build(root, day, sync=False, repo="pkppkqbobs/kaoyan-english-trainer"):
    existing = load(root / "data/daily.json", {})
    if existing.get("date", "") > day.isoformat():
        raise ValueError("Refusing to rewind the live daily quiz/state to an older date")
    locked = load(root / f"data/days/{day.isoformat()}.json", {})
    items = bank(root)
    if sync:
        previous = load(root / "data/result-evidence.json", {"rows": [], "issues": []})
        saved_rows = previous["rows"] + load(root / "data/excluded-evidence.json", [])
        fallback = {number: [r for r in saved_rows if r["origin"] == number] for number in previous["issues"]}
        rejected = []
        rows, accepted = evidence(get_issues(repo), repo.split("/")[0], root, rejected=rejected, fallback=fallback)
        if rejected or (root / "data/rejected-results.json").exists():
            save(root / "data/rejected-results.json", {"issues": rejected})
        if rejected:
            print(json.dumps({"rejected_reports": rejected}, ensure_ascii=False))
        save(root / "data/result-evidence.json", {"rows": rows, "issues": accepted})
    evidence_data = load(root / "data/result-evidence.json", {"rows": [], "issues": []})
    notes = load(root / "data/learning-notes.json", [])
    stats = make_stats(items, evidence_data["rows"], notes, day)
    unmapped = sorted({r["family"] for r in evidence_data["rows"]} - set(stats))
    save(root / "data/review-state.json", {"as_of": day.isoformat(), "issues": evidence_data["issues"], "families": stats, "unmapped_targets": unmapped})
    history = load(root / "data/daily-history.json", {})
    # A submitted result or an evening bank expansion must not replace a quiz mid-session.
    if locked.get("date") == day.isoformat() or existing.get("date") == day.isoformat():
        payload = locked if locked.get("date") == day.isoformat() else existing
    else:
        selected = choose(items, stats, history, day, variant_shown=variant_history(root, day, history))
        payload = {"date": day.isoformat(), "repo": repo, "questions": selected,
                   "retry": {q["family"]: retry_variants(items, q, day) for q in selected},
                   "issues_used": evidence_data["issues"], "engine": 3}
        history[day.isoformat()] = [q["id"] for q in selected]
        save(root / "data/daily-history.json", history)
    payload["issues_used"] = evidence_data["issues"]
    save(root / "data/daily.json", payload)
    save(root / f"data/days/{day.isoformat()}.json", payload)
    script = root / "web/review.js"
    version = hashlib.sha256(script.read_bytes()).hexdigest()[:12]
    if locked.get("date") == day.isoformat() or existing.get("date") == day.isoformat():
        version = published_script_version(root / "today.html", version)
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


def published_script_version(page, fallback, asset="review.js"):
    """Keep immutable page bytes; the shared asset URL still serves compatible fixes.

    New rounds use the current hash. Existing rounds keep their URL/query and
    local storage IDs instead of rewriting every historical HTML on a JS fix.
    """
    if page.exists():
        match = re.search(r'(?:src|href)="\./web/' + re.escape(asset) + r'\?v=([a-f0-9]{12})"', page.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    return fallback


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--date", default=datetime.now(TZ).date().isoformat())
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "pkppkqbobs/kaoyan-english-trainer"))
    args = parser.parse_args()
    build(ROOT, date.fromisoformat(args.date), args.sync, args.repo)
