"""Independent paragraph ordering: immutable questions, deterministic scoring, static pages."""
from __future__ import annotations
import copy
import hashlib
import html
import json
import math
import re
from datetime import date, datetime
from pathlib import Path

import daily_review as review

ROOT = Path(__file__).resolve().parents[1]
SIGNALS = {
    "anaphora": "回指", "lexical-chain": "词汇复现", "synonym-chain": "同义复现",
    "problem-to-reason": "问题→原因", "cause-effect": "因果",
    "general-to-specific": "概括→具体", "example": "举例", "parallel": "平行",
    "contrast": "转折", "conclusion": "收束", "topic-introduction": "主题引入",
    "paragraph-end-hook": "段尾钩子",
}
STRENGTHS = {"strong": "强", "medium": "中", "support": "辅助"}
FAMILIES = ("paragraph-order-anaphora", "paragraph-order-discourse")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pair_families(link):
    return [f for f in FAMILIES if
            (f == FAMILIES[0] and "anaphora" in link["signals"]) or
            (f == FAMILIES[1] and any(s != "anaphora" for s in link["signals"]))]


def validate_question(q):
    require(isinstance(q, dict) and q.get("kind") == "paragraph_order", "Invalid Part B question")
    require(isinstance(q.get("id"), str) and re.fullmatch(r"pb-[a-z0-9-]{3,90}", q["id"]), "Invalid Part B id")
    require(all(isinstance(q.get(k), str) and q[k].strip()
                for k in ("title", "topic", "overview", "globalLogic", "themeTrap")), "Missing Part B explanation")
    require(type(q.get("budget")) is int and 300 <= q["budget"] <= 480, "Invalid Part B time budget")
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", q.get("published_on", "")) is not None, "Invalid publication date")
    date.fromisoformat(q["published_on"])
    paragraphs = q.get("paragraphs")
    require(isinstance(paragraphs, list) and 5 <= len(paragraphs) <= 7, "Part B needs 5–7 paragraphs")
    require(all(isinstance(p, dict) and re.fullmatch(r"[A-G]", p.get("id", "")) and
                isinstance(p.get("text"), str) and p["text"].strip() for p in paragraphs), "Invalid paragraph")
    ids = [p["id"] for p in paragraphs]
    require(len(set(ids)) == len(ids), "Duplicate paragraph id")
    words = re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)*", " ".join(p["text"] for p in paragraphs))
    require(250 <= len(words) <= 450, "Part B passage must contain 250–450 English words")
    validate_order(q.get("expectedOrder"), ids)
    links = q.get("links")
    require(isinstance(links, list) and len(links) == len(ids)-1, "Missing standard links")
    require([(l.get("from"), l.get("to")) for l in links] ==
            list(zip(q["expectedOrder"], q["expectedOrder"][1:])), "Links must follow the complete standard order")
    for link in links:
        require(isinstance(link.get("signals"), list) and link["signals"] and
                len(set(link["signals"])) == len(link["signals"]) and set(link["signals"]) <= SIGNALS.keys(),
                "Invalid connection mechanisms")
        require(link.get("strength") in STRENGTHS and type(link.get("anchor")) is bool, "Invalid evidence strength")
        require(isinstance(link.get("explanation"), str) and link["explanation"].strip(), "Missing link explanation")
        require(isinstance(link.get("evidence"), list) and link["evidence"] and
                all(isinstance(e, dict) and e.get("level") in STRENGTHS and
                    isinstance(e.get("text"), str) and e["text"].strip() for e in link["evidence"]),
                "Missing graded evidence")
    require(len({s for l in links for s in l["signals"]}) >= 3, "Need at least three connection mechanisms")
    require(any(l["strength"] != "strong" for l in links), "Need a connection requiring global judgment")
    require(any(l["anchor"] for l in links), "Need at least one anchor")
    return q


def validate_order(order, ids):
    require(isinstance(order, list) and all(isinstance(x, str) for x in order), "Invalid pickOrder")
    require(len(order) == len(ids) and len(set(order)) == len(order) and set(order) == set(ids),
            "Order must contain every paragraph exactly once")


def bank(root=ROOT):
    """Published IDs are immutable; old snapshots survive removal from the source pool."""
    sources = {}
    for path in sorted((root / "data/partb-questions").glob("*.json")):
        items = review.load(path)
        require(isinstance(items, list), "Part B bank must contain arrays")
        for q in items:
            validate_question(q)
            source = q.get("mechanism_source")
            if source:
                require(re.fullmatch(r"data/source-checks/[a-z0-9-]+\.json", source.get("source_check", "")),
                        "Invalid source-check reference")
                checked = review.load(root / source["source_check"], {})
                require(checked.get("exam") == source.get("exam") and checked.get("part_b_order"),
                        "Part B source must have a verified order")
                pairs = {a + ">" + b for a, b in zip(checked["part_b_order"], checked["part_b_order"][1:])}
                require(set(source.get("pairs", [])) <= pairs, "Unknown original Part B connection")
            require(q["id"] not in sources, "Duplicate Part B question id")
            sources[q["id"]] = q
    result = dict(sources)
    for path in sorted((root / "data/partb-reviews").glob("*.json")):
        snapshot = review.load(path)
        q = validate_question(snapshot["question"])
        require(snapshot.get("storageId") == q["id"] == path.stem, "Invalid Part B snapshot id")
        require(q["id"] not in sources or sources[q["id"]] == q,
                "Published Part B questions are immutable; use a new id for revisions")
        result[q["id"]] = q
    return list(result.values())


def score(q, order):
    validate_order(order, [p["id"] for p in q["paragraphs"]])
    chosen = set(zip(order, order[1:]))
    standard = set(zip(q["expectedOrder"], q["expectedOrder"][1:]))
    pairs = [{"from": l["from"], "to": l["to"], "signals": l["signals"][:],
              "families": pair_families(l), "anchor": l["anchor"],
              "ok": (l["from"], l["to"]) in chosen} for l in q["links"]]
    anchors = [p for p in pairs if p["anchor"]]
    return {
        "fullOrderOk": order == q["expectedOrder"],
        "pairScore": {"correct": sum(p["ok"] for p in pairs), "total": len(pairs)},
        "anchorScore": {"correct": sum(p["ok"] for p in anchors), "total": len(anchors)},
        "startOk": order[0] == q["expectedOrder"][0],
        "endOk": order[-1] == q["expectedOrder"][-1],
        "positionScore": {"correct": sum(a == b for a, b in zip(order, q["expectedOrder"])), "total": len(order)},
        "pairResults": pairs,
        "hitPairs": [{"from": p["from"], "to": p["to"]} for p in pairs if p["ok"]],
        "missedPairs": [{"from": p["from"], "to": p["to"]} for p in pairs if not p["ok"]],
        "wrongPairs": [{"from": a, "to": b} for a, b in zip(order, order[1:]) if (a, b) not in standard],
    }


def parse_report(obj, issue, root=ROOT):
    """Never trust client ok, pair scores, families, or a supplied answer key."""
    require(isinstance(obj, dict) and obj.get("version") == 4 and obj.get("module") == "partb",
            "Unknown review-json:v4 module")
    require(isinstance(obj.get("roundId"), str) and re.fullmatch(r"[a-zA-Z0-9_-]{6,120}", obj["roundId"]),
            "Invalid Part B round id")
    require(isinstance(obj.get("date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", obj["date"]),
            "Invalid Part B report date")
    day = date.fromisoformat(obj["date"])
    issue_day = review.issue_report_day(issue)
    require(day <= issue_day, "Part B report cannot claim a future learning date")
    require(isinstance(obj.get("answers"), list) and obj["answers"], "Missing Part B answers")
    questions = {q["id"]: q for q in bank(root)}
    main = []
    for answer in obj["answers"]:
        require(isinstance(answer, dict) and answer.get("kind") == "paragraph_order" and
                answer.get("mode") in ("main", "retry"), "Invalid Part B answer kind")
        require(isinstance(answer.get("qid"), str) and answer["qid"] in questions, "Unknown Part B question")
        q = questions[answer["qid"]]
        require(q["published_on"] <= obj["date"], "Part B report predates the question")
        computed = score(q, answer.get("pickOrder"))
        require(answer.get("expectedOrder") == q["expectedOrder"], "Part B supplied key differs from repository key")
        require(type(answer.get("uncertain")) is bool, "Invalid Part B uncertain flag")
        ms = answer.get("ms")
        require(type(ms) in (int, float) and math.isfinite(ms) and 0 <= ms <= 3600000,
                "Invalid Part B time")
        if answer["mode"] == "main":
            main.append((answer, q, computed))
    # A retry-only report is review, not fresh evidence. Two claimed first results are ambiguous.
    require(len(main) <= 1, "Part B report must not contain multiple first results")
    report_id = "partb:" + obj["roundId"]
    if not main:
        return report_id, []
    answer, q, computed = main[0]
    result = {"roundId": obj["roundId"], "date": obj["date"], "qid": q["id"], "title": q["title"],
              "pickOrder": answer["pickOrder"][:], "expectedOrder": q["expectedOrder"][:],
              "ms": answer["ms"], "uncertain": answer["uncertain"], "origin": issue["number"], **computed}
    rows = []
    for family in FAMILIES:
        relevant = [p for p in computed["pairResults"] if family in p["families"]]
        if relevant:
            # One family result per passage; three missed anaphora links are not three attempts.
            rows.append({"date": obj["date"], "family": family, "ok": all(p["ok"] for p in relevant),
                         "ms": answer["ms"], "slow_threshold_ms": q["budget"] * 1000,
                         "uncertain": answer["uncertain"], "origin": issue["number"], "qid": q["id"],
                         "round_id": report_id,
                         "pair_score": {"correct": sum(p["ok"] for p in relevant), "total": len(relevant)}})
    if rows:
        rows[0]["partb_result"] = result
    return report_id, rows


def build(root=ROOT, repo="pkppkqbobs/kaoyan-english-trainer"):
    questions = bank(root)
    if not questions:
        return None
    questions.sort(key=lambda q: q["id"])
    rows = review.load(root / "data/result-evidence.json", {"rows": []})["rows"]
    results = {}
    for row in rows:
        if row.get("partb_result"):
            result = row["partb_result"]
            results[result["roundId"]] = result
    state = review.load(root / "data/review-state.json", {"families": {}})
    stats = {f: state["families"].get(f, {}) for f in FAMILIES}
    day = state.get("as_of", datetime.now(review.TZ).date().isoformat())
    recommended = any(s and s.get("streak", 0) < 2 and s.get("due", "9999") <= day and
                      (s.get("reported_confusion") or s.get("errors") or s.get("slow_or_uncertain"))
                      for s in stats.values())
    payload = {"schema": 1, "repo": repo, "storagePrefix": "kaoyan.partb.v1.", "questions": questions,
               "signals": SIGNALS, "strengths": STRENGTHS, "results": list(results.values()),
               "recommend": recommended, "as_of": day}
    versions = {name: hashlib.sha256((root / ("web/" + name)).read_bytes()).hexdigest()[:12]
                for name in ("partb-core.js", "partb.js", "partb.css")}
    template = (root / "web/partb-page.html").read_text()
    pages = {}
    for mode, path in (("review", "partb-review.html"), ("history", "partb-history.html")):
        page = template.replace("__MODE__", mode)
        page = page.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c"))
        for name, version in versions.items():
            cached_version = review.published_script_version(root / path, version, asset=name)
            page = page.replace("__" + name + "__", cached_version)
        pages[path] = page
    # Everything has been validated/rendered before any published file is written.
    for q in questions:
        snapshot = root / ("data/partb-reviews/" + q["id"] + ".json")
        if not snapshot.exists():
            review.save(snapshot, {"schema": 1, "storageId": q["id"], "question": q})
    review.save(root / "data/partb-results.json", payload["results"])
    review.save(root / "data/partb-recommendation.json", {"as_of": day, "recommend": recommended})
    for path, page in pages.items():
        (root / path).write_text(page, encoding="utf-8")
    return payload


if __name__ == "__main__":
    payload = build()
    print(json.dumps({"partb_questions": len(payload["questions"]) if payload else 0}, ensure_ascii=False))
