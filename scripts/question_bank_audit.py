"""Read-only inventory/exposure audit. Its output is never a scoring input.

Context groups are manually reviewed, conservative semantic judgments, not a
similarity score. Published rounds are opportunities to see a question, not
proof the learner opened them. Unknown legacy qids and browser retries stay
unknown. New question files do not create exposures or attempts.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess

import daily_review as review
import partb_review as partb

ROOT = Path(__file__).resolve().parents[1]


def literal(path, marker):
    return json.JSONDecoder().raw_decode(path.read_text(encoding="utf-8").split(marker, 1)[1].lstrip())[0]


def catalogue(root):
    """Source definitions once; generated copies/retries are not extra variants."""
    records = {}
    def add(key, q, pool, source, *, qid=None, family=None, schema="five_part"):
        if key in records:
            raise ValueError("Duplicate inventory key: " + key)
        records[key] = {"key": key, "qid": qid, "family": family or q["family"],
                        "families": [family or q["family"]], "pool": pool,
                        "source": source, "schema": schema, "question": q}
    locations = {q["id"]: "data/base-bank.json" for q in review.load(root / "data/base-bank.json", [])}
    for path in sorted((root / "data/questions").glob("*.json")):
        for q in review.load(path):
            locations[q["id"]] = str(path.relative_to(root))
    for q in review.bank(root):
        add(q["id"], q, "daily_article", locations[q["id"]], qid=q["id"])
    helper = Path(__file__).with_suffix(".mjs")
    legacy = json.loads(subprocess.run(["node", str(helper), str(root)], check=True,
                                     capture_output=True, text=True, timeout=10).stdout)
    for q in legacy:
        add(q["id"], q, "home_legacy", "index.html", qid=q["id"],
            family=review.canonical(q["skill"]), schema="legacy_compact")
    vocabulary = root / "vocab-quiz-2026-09-27.html"
    if vocabulary.exists():
        for i, q in enumerate(literal(vocabulary, "const bank="), 1):
            add(f"vocab-2026-09-27#{i:02}", q, "legacy_fixed", vocabulary.name,
                family=review.canonical(q["target"]), schema="legacy_five_part_array")
    for q in partb.bank(root):
        add(q["id"], q, "partb_full", "data/partb-questions", qid=q["id"],
            family="paragraph-order-anaphora", schema="paragraph_order")
        records[q["id"]]["families"] = sorted(set(f for l in q["links"] for f in partb.pair_families(l)))
    archived = root / "archive/2026-09-29-before-automation.html"
    if archived.exists():
        originals = literal(archived, "const BANK = ")
        for q in originals:
            add("archive:" + q["id"], q, "archive_only", str(archived.relative_to(root)),
                family=review.canonical(q["skill"]))
        by_id = {q["id"]: q for q in originals}
        for qid, variant in literal(archived, "const RETRY = ").items():
            add("archive:retry-" + qid, variant, "archive_retry_only", str(archived.relative_to(root)),
                family=review.canonical(by_id[qid]["skill"]), schema="legacy_inherited_explanation")
    ids = [x["qid"] for x in records.values() if x["qid"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Qids collide across live banks")
    return records


def published_rounds(root):
    """Aliases such as latest article/daily HTML never double-count a round."""
    rounds = {}
    for path in sorted((root / "data/days").glob("*.json")):
        payload = review.load(path)
        rounds["daily:" + payload["date"]] = payload
    daily = review.load(root / "data/daily.json", {})
    if daily.get("date"):
        rounds.setdefault("daily:" + daily["date"], daily)
    for path in sorted((root / "data/article-reviews").glob("*.json")):
        payload = review.load(path)
        rounds["article:" + payload["storageId"]] = payload
    for path in sorted(root.glob("passage-drill-*.html")):
        payload = literal(path, "window.REVIEW_DATA=")
        rounds["passage:" + payload.get("storageId", path.stem)] = payload
    # A bank being available on the home/Part B page does not mean it was selected.
    return [{"id": key, "date": p["date"], "qids": [q["id"] for q in p["questions"]],
             "retry_qids": sorted({q["id"] for v in p.get("retry", {}).values() for q in v})}
            for key, p in sorted(rounds.items())]


def in_window(stamp, day, days):
    return day - timedelta(days=days - 1) <= date.fromisoformat(stamp) <= day


def report(root, day):
    records = catalogue(root)
    manifest = review.load(root / "data/question-contexts.json", {"contexts": {}, "family_assessments": {}})
    contexts = manifest["contexts"]
    missing = set(records) - set(contexts)
    if missing:
        raise ValueError("Context review missing: " + ", ".join(sorted(missing)))
    events, rounds = [], [r for r in published_rounds(root) if r["date"] <= day.isoformat()]
    for round_ in rounds:
        if round_["date"] <= day.isoformat():
            events.extend({"date": round_["date"], "round": round_["id"], "qid": qid}
                          for qid in round_["qids"])
    # One full passage can emit two family rows; retain only one round exposure.
    partb_rounds = set()
    for r in review.load(root / "data/partb-results.json", []):
        if r["date"] <= day.isoformat() and r["roundId"] not in partb_rounds:
            partb_rounds.add(r["roundId"])
            events.append({"date": r["date"], "round": "partb:" + r["roundId"], "qid": r["qid"]})
    evidence = review.load(root / "data/result-evidence.json", {"rows": [], "issues": []})
    rows = [r for r in evidence["rows"] if r["date"] <= day.isoformat()]
    state = review.load(root / "data/review-state.json", {"families": {}})["families"]
    notes = review.load(root / "data/learning-notes.json", [])
    qids = {v["qid"]: v for v in records.values() if v["qid"]}
    qevents = defaultdict(list)
    for event in events:
        qevents[event["qid"]].append(event)
    per_question = {}
    for key, item in records.items():
        qid = item["qid"]
        exposures = qevents[qid] if qid else []
        answered = list({(r["origin"], r["date"], r.get("round_id", "")): r
                         for r in reversed(rows) if qid and r.get("qid") == qid}.values())
        stamps = [x["date"] for x in exposures + answered]
        per_question[key] = {"qid": qid, "family": item["family"], "families": item["families"],
            "pool": item["pool"], "source": item["source"], "schema": item["schema"],
            "context_id": contexts[key], "first_seen": min(stamps, default=None), "last_seen": max(stamps, default=None),
            "times_shown": len(exposures), "times_answered": len(answered),
            "errors": sum(int(not r["partb_result"]["fullOrderOk"]) if r.get("partb_result")
                          else r.get("errors", int(not r["ok"])) for r in answered),
            "uncertain": sum(bool(r.get("uncertain")) for r in answered),
            "recent_exposure_3d": sum(in_window(e["date"], day, 3) for e in exposures),
            "recent_exposure_7d": sum(in_window(e["date"], day, 7) for e in exposures),
            "published_rounds": exposures,
            "visibility": "reported_answered" if answered else "published_unconfirmed" if exposures else "no_repository_exposure_record"}
    families = {}
    for family in sorted(set(f for x in records.values() for f in x["families"]) | set(state)):
        members = [x for x in per_question.values() if family in x["families"] and not x["pool"].startswith("archive")]
        spaced = [x for x in members if x["pool"] == "daily_article"]
        family_rows = [r for r in rows if r["family"] == family]
        shown = [e for e in events if e["qid"] in qids and family in qids[e["qid"]]["families"]]
        stamps = [x["date"] for x in shown + family_rows]
        assessment = manifest.get("family_assessments", {}).get(family, {})
        n = len({x["context_id"] for x in spaced or members})
        risk = "structural_gap" if assessment.get("coverage_gap") else "severe" if n < 2 else "limited" if n < 3 else "sufficient"
        exposure_risk = len([e for e in shown if in_window(e["date"], day, 7)]) > 2 * max(1, n)
        s = state.get(family, {})
        budget = max((records[x["qid"]]["question"].get("budget", 35) for x in spaced), default=35) * 1000
        recent_rows = [r for r in family_rows if in_window(r["date"], day, 7)]
        priority = (100 * sum(r.get("errors", int(not r["ok"])) for r in recent_rows)
                    + 30 * sum(r.get("uncertain", False) or r["ms"] > r.get("slow_threshold_ms", budget) for r in recent_rows)
                    + 20 * bool(s.get("reported_confusion"))
                    + sum(in_window(e["date"], day, 7) for e in shown))
        if s.get("streak", 0) >= 2 and not s.get("reported_confusion"):
            priority /= 1 + s["streak"]
        families[family] = {"question_count": len(members),
            "effective_context_count": len({x["context_id"] for x in members}),
            "spaced_question_count": len(spaced), "spaced_effective_context_count": len({x["context_id"] for x in spaced}),
            "full_partb_variants": sum(x["pool"] == "partb_full" for x in members),
            "main_variants": [x["qid"] for x in spaced], "retry_variants": [x["qid"] for x in spaced],
            "retry_pool_note": "Same candidate pool, not additional questions or evidence. Historical retry selections mostly unknown.",
            "first_seen": min(stamps, default=None), "last_seen": max(stamps, default=None),
            "times_shown": len(shown), "times_answered": sum(r.get("attempts", 1) for r in family_rows),
            "unknown_qid_attempts": sum(r.get("attempts", 1) for r in family_rows if not r.get("qid")),
            "errors": sum(r.get("errors", int(not r["ok"])) for r in family_rows),
            "uncertain": sum(bool(r.get("uncertain")) for r in family_rows),
            "recent_exposure_3d": sum(in_window(e["date"], day, 3) for e in shown),
            "recent_exposure_7d": sum(in_window(e["date"], day, 7) for e in shown),
            "status": risk, "recent_repeat_risk": exposure_risk, "assessment": assessment, "review_state": s,
            "maintenance_priority": round(priority, 2)}
    groups = defaultdict(list)
    for key, item in per_question.items():
        if not item["pool"].startswith("archive"):
            groups[item["context_id"]].append(key)
    context_report = []
    for context, keys in sorted(groups.items()):
        shown = [e for key in keys for e in per_question[key]["published_rounds"]]
        context_report.append({"context_id": context, "items": keys,
            "times_shown": len(shown), "recent_exposure_3d": sum(in_window(e["date"], day, 3) for e in shown),
            "recent_exposure_7d": sum(in_window(e["date"], day, 7) for e in shown),
            "rationale": manifest.get("cluster_rationales", {}).get(context, "Manually reviewed distinct situation and evidence path.")})
    active = [x for x in per_question.values() if not x["pool"].startswith("archive")]
    return {"schema_version": 1, "generated_at": day.isoformat(), "as_of": day.isoformat(),
        "source_commit": manifest.get("source_commit"),
        "definitions": {"effective_context_count": "Conservative manual context/evidence-path clusters, not qid counts or automatic semantic proof.",
            "times_shown": "Main slots in unique published daily/article/passage rounds; not confirmed reading.",
            "windows": "3d includes today and two previous dates; 7d includes today and six previous dates (Asia/Shanghai).",
            "unknown": "No repository exposure record cannot prove never seen. Browser-only attempts and retrySummary qids are unavailable.",
            "legacy": "Existing compact/array schemas are grandfathered inventory items; archive-only questions are excluded from live totals.",
            "families": "Part B passages contribute to both existing families; global passage/context counts count each passage once."},
        "summary": {"live_qid_count": sum(x["qid"] is not None for x in active), "live_item_count": len(active),
            "legacy_items_without_qid": sum(x["qid"] is None for x in active),
            "live_family_count": len(families), "spaced_family_count": len(state),
            "spaced_qid_count": sum(x["pool"] == "daily_article" for x in active),
            "home_legacy_qid_count": sum(x["pool"] == "home_legacy" for x in active),
            "full_partb_count": sum(x["pool"] == "partb_full" for x in active),
            "effective_context_count": len(groups),
            "spaced_effective_context_count": len({x["context_id"] for x in active if x["pool"] == "daily_article"}),
            "archive_only_items": len(per_question) - len(active),
            "published_rounds": len(rounds), "published_main_slots": len(events), "issues_used": evidence["issues"]},
        "families": families, "questions": per_question, "contexts": context_report,
        "observations_without_scheduled_family": [n["family"] for n in notes if n["family"] not in state],
        "historical_content_findings": manifest.get("historical_content_findings", []),
        "before_additions": manifest.get("before_additions", {}),
        "source_checks_are_not_question_sources": True, "audit_is_not_scoring_evidence": True}


def build(root=ROOT, day=None):
    day = day or date.fromisoformat(review.load(root / "data/review-state.json")["as_of"])
    result = report(root, day)
    review.save(root / "data/question-bank-audit.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    print(json.dumps(build(day=args.date)["summary"], ensure_ascii=False))
