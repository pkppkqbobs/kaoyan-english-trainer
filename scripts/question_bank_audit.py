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
        # Runtime eligibility is operational metadata, not an edit to the
        # original definition or its previously reviewed option fingerprint.
        retired_on = q.get("retired_on")
        definition = {k: v for k, v in q.items() if k != "retired_on"}
        add(q["id"], definition, "daily_article", locations[q["id"]], qid=q["id"])
        if retired_on:
            records[q["id"]]["retired_on"] = retired_on
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
    spaced_sources = {key: item for key, item in records.items() if item["pool"] == "daily_article"}
    spaced_available = {
        key for key, item in spaced_sources.items()
        if review.available({**item["question"], "retired_on": item.get("retired_on")}, day)
    }
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
        if key in spaced_sources:
            per_question[key]["available_for_spaced_review"] = key in spaced_available
            if item.get("retired_on"):
                per_question[key]["retired_on"] = item["retired_on"]
    families = {}
    for family in sorted(set(f for x in records.values() for f in x["families"]) | set(state)):
        members = [x for x in per_question.values() if family in x["families"] and not x["pool"].startswith("archive")]
        source_spaced = [x for x in members if x["qid"] in spaced_sources]
        spaced = [x for x in source_spaced if x["qid"] in spaced_available]
        family_rows = [r for r in rows if r["family"] == family]
        shown = [e for e in events if e["qid"] in qids and family in qids[e["qid"]]["families"]]
        stamps = [x["date"] for x in shown + family_rows]
        assessment = manifest.get("family_assessments", {}).get(family, {})
        coverage_members = spaced if source_spaced or family in state else members
        n = len({x["context_id"] for x in coverage_members})
        risk = "structural_gap" if assessment.get("coverage_gap") else "severe" if n < 2 else "limited" if n < 3 else "sufficient"
        exposure_risk = len([e for e in shown if in_window(e["date"], day, 7)]) > 2 * max(1, n)
        s = state.get(family, {})
        budget = max((records[x["qid"]]["question"].get("budget", 35) for x in source_spaced), default=35) * 1000
        recent_rows = [r for r in family_rows if in_window(r["date"], day, 7)]
        priority = (100 * sum(r.get("errors", int(not r["ok"])) for r in recent_rows)
                    + 30 * sum(r.get("uncertain", False) or r["ms"] > r.get("slow_threshold_ms", budget) for r in recent_rows)
                    + 20 * bool(s.get("reported_confusion"))
                    + sum(in_window(e["date"], day, 7) for e in shown))
        if s.get("streak", 0) >= 2 and not s.get("reported_confusion"):
            priority /= 1 + s["streak"]
        families[family] = {"question_count": len(members),
            "effective_context_count": len({x["context_id"] for x in members}),
            "spaced_source_question_count": len(source_spaced),
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
    sources = [x for x in per_question.values() if not x["pool"].startswith("archive")]
    scheduled_families = {records[key]["family"] for key in spaced_available}
    return {"schema_version": 1, "generated_at": day.isoformat(), "as_of": day.isoformat(),
        "source_commit": manifest.get("source_commit"),
        "definitions": {"effective_context_count": "Conservative manual context/evidence-path clusters, not qid counts or automatic semantic proof.",
            "times_shown": "Main slots in unique published daily/article/passage rounds; not confirmed reading.",
            "windows": "3d includes today and two previous dates; 7d includes today and six previous dates (Asia/Shanghai).",
            "unknown": "No repository exposure record cannot prove never seen. Browser-only attempts and retrySummary qids are unavailable.",
            "legacy": "Live inventory excludes archive-only questions and retains source definitions of retired questions for traceability.",
            "spaced_eligibility": "Spaced candidate counts, context counts and variant lists reflect publication and retirement dates at as_of. Historical exposures and scores remain under their original question IDs.",
            "families": "Part B passages contribute to both existing families; global passage/context counts count each passage once."},
        "summary": {"live_qid_count": sum(x["qid"] is not None for x in sources), "live_item_count": len(sources),
            "legacy_items_without_qid": sum(x["qid"] is None for x in sources),
            "live_family_count": len(families), "spaced_family_count": len(scheduled_families),
            "spaced_source_qid_count": len(spaced_sources),
            "spaced_qid_count": len(spaced_available),
            "spaced_retired_qid_count": sum(bool(item.get("retired_on") and item["retired_on"] <= day.isoformat())
                                           for item in spaced_sources.values()),
            "home_legacy_qid_count": sum(x["pool"] == "home_legacy" for x in sources),
            "full_partb_count": sum(x["pool"] == "partb_full" for x in sources),
            "effective_context_count": len(groups),
            "spaced_effective_context_count": len({contexts[key] for key in spaced_available}),
            "archive_only_items": len(per_question) - len(sources),
            "published_rounds": len(rounds), "published_main_slots": len(events), "issues_used": evidence["issues"]},
        "families": families, "questions": per_question, "contexts": context_report,
        "observations_without_scheduled_family": [n["family"] for n in notes
            if n["family"] not in scheduled_families and review.observation_dates(n, day)[1] <= day.isoformat()],
        "historical_content_findings": manifest.get("historical_content_findings", []),
        "before_additions": manifest.get("before_additions", {}),
        "source_checks_are_not_question_sources": True, "audit_is_not_scoring_evidence": True}


def build(root=ROOT, day=None):
    day = day or date.fromisoformat(review.load(root / "data/review-state.json")["as_of"])
    result = report(root, day)
    review.save(root / "data/question-bank-audit.json", result)
    return result


def coverage(root, day):
    """Candidate counts derived from question definitions for public sharing."""
    questions = review.bank(root)
    available = [q for q in questions if review.available(q, day)]
    counts = Counter(q["family"] for q in available)
    contexts = defaultdict(set)
    for q in available:
        contexts[q["family"]].add(q.get("context_id", q["id"]))
    return {
        "schema_version": 1,
        "as_of": day.isoformat(),
        "scope": "Question definitions and candidate availability on the report date.",
        "summary": {
            "source_questions": len(questions),
            "available_candidates": len(available),
            "available_contexts": len(set().union(*contexts.values())),
            "available_families": len(counts),
            "retired_questions": sum(bool(q.get("retired_on") and q["retired_on"] <= day.isoformat())
                                     for q in questions),
            "available_reading_passages": sum(q.get("format") == "english1_reading" for q in available),
        },
        "families": {family: {"candidates": counts[family], "contexts": len(contexts[family])}
                     for family in sorted(counts)},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--coverage-only", action="store_true", help="Generate the source-only coverage snapshot")
    args = parser.parse_args()
    if args.coverage_only:
        day = args.date or date.fromisoformat(review.load(ROOT / "data/daily.json")["date"])
        result = coverage(ROOT, day)
        review.save(ROOT / "data/question-bank-coverage.json", result)
    else:
        result = build(day=args.date)
    print(json.dumps(result["summary"], ensure_ascii=False))
