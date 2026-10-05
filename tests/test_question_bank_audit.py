from datetime import date, datetime, timedelta
from pathlib import Path
import random
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import article_review
import daily_review as review
import partb_review
import question_bank_audit as audit
from run_daily import run


def item(qid, context=None, family="point"):
    q = {"id": qid, "family": family, "introduced": None, "target": family,
         "q": "A distinct fixture question about " + qid, "o": ["one", "two", "three", "four"],
         "a": 0, "budget": 35, "exp": {k: "Fixture explanation" for k in review.EXP_KEYS}}
    if context:
        q["context_id"] = context
    return q


class BankCoverageTests(unittest.TestCase):
    def test_every_scheduled_active_family_has_a_question(self):
        items = review.bank(ROOT)
        self.assertLessEqual(set(review.load(ROOT / "data/review-state.json")["families"]),
                             {q["family"] for q in items})
        # Low-frequency compositional observations need not create a new family.
        self.assertNotIn("kitten-killing", {q["family"] for q in items})

    def test_live_qids_unique_across_all_sources_and_curation_complete(self):
        records = audit.catalogue(ROOT)
        ids = [r["qid"] for r in records.values() if r["qid"]]
        self.assertEqual(len(ids), len(set(ids)))
        contexts = review.load(ROOT / "data/question-contexts.json")["contexts"]
        self.assertLessEqual(set(records), set(contexts))
        self.assertTrue(all(isinstance(v, str) and v for v in contexts.values()))

    def test_main_schema_five_explanations_options_and_key(self):
        for q in review.bank(ROOT):
            with self.subTest(qid=q["id"]):
                review.validate(q)
                self.assertEqual(len(q["o"]), 4)
                self.assertEqual(len(set(q["o"])), 4)
                self.assertIn(q["a"], range(4))
                self.assertEqual(set(q["exp"]), set(review.EXP_KEYS))

    def test_full_explanations_are_shuffle_safe(self):
        pattern = r"第[一二三四1234]项|前三项|[ABCD]选项|选项[ABCD]|\b[ABCD]\s*[.、：]"
        for q in review.bank(ROOT):
            with self.subTest(qid=q["id"]):
                self.assertIsNone(re.search(pattern, q["exp"]["rest"]))
                # Keys are canonical option indices, which review.js remaps when
                # shuffling. Only index-dependent prose would be unsafe.
                for key, explanation in q.get("diag", {}).items():
                    self.assertIn(str(key), {"0", "1", "2", "3"})
                    self.assertIsInstance(explanation, str)
                    self.assertIsNone(re.search(pattern, explanation))

    def test_new_dates_do_not_reintroduce_old_targets_or_change_slow_thresholds(self):
        additions = review.load(ROOT / "data/questions/2026-10-05-context-gaps.json")
        ids = {q["id"] for q in additions}
        old = [q for q in review.bank(ROOT) if q["id"] not in ids]
        for q in additions:
            with self.subTest(qid=q["id"]):
                self.assertEqual(date.fromisoformat(q["published_on"]), date(2026, 10, 5))
                group = [v for v in old if v["family"] == q["family"]]
                expected = None if any(v.get("introduced") is None for v in group) else min(v["introduced"] for v in group)
                self.assertEqual(q["introduced"], expected)
                self.assertLessEqual(q["budget"], max(v.get("budget", 35) for v in group))
                self.assertFalse(review.available(q, date(2026, 10, 4)))
                self.assertTrue(review.available(q, date(2026, 10, 5)))
                self.assertNotIn("source_question", q)

    def test_retry_candidates_are_new_contexts_not_merely_new_ids(self):
        items = review.bank(ROOT)
        for q in items:
            retries = review.retry_variants(items, q, date(2026, 10, 5))
            for retry in retries:
                self.assertNotEqual(retry["id"], q["id"])
                self.assertNotEqual(retry.get("context_id", retry["id"]), q.get("context_id", q["id"]))
                self.assertEqual(retry["family"], q["family"])
        self.assertEqual(review.retry_variants([item("main", "same"), item("other", "same")],
                                              item("main", "same"), date(2026, 10, 5)), [])

    def test_recent_qid_spacing_and_older_or_unseen_variant(self):
        day = date(2026, 10, 6)
        variants = [item("recent"), item("old"), item("unseen")]
        history = {"2026-10-05": ["recent"], "2026-10-01": ["old"]}
        self.assertEqual(review.choose_variant(variants, history, random.Random(2))["id"], "unseen")
        history["2026-10-06"] = ["unseen"]
        self.assertEqual(review.choose_variant(variants, history, random.Random(2))["id"], "old")

    def test_unseen_qid_with_recent_near_duplicate_is_not_unseen_context(self):
        variants = [item("used", "same-template"), item("unused-sibling", "same-template"), item("old-context", "different")]
        shown = {"2026-10-05": ["used"], "2026-10-01": ["old-context"]}
        for avoid in [(), {"used"}]:
            selected = review.choose_variant(variants, shown, random.Random(7), avoid_ids=avoid)
            self.assertEqual(selected["id"], "old-context")

    def test_cross_module_variant_history_does_not_change_family_priority(self):
        day = date(2026, 10, 6)
        items = review.bank(ROOT)
        evidence = review.load(ROOT / "data/result-evidence.json")["rows"]
        stats = review.make_stats(items, evidence, review.load(ROOT / "data/learning-notes.json"), day)
        daily = review.load(ROOT / "data/daily-history.json")
        combined = review.variant_history(ROOT, day, daily)
        self.assertIn("point-waiting", combined["2026-10-04"])
        self.assertNotIn("point-waiting", daily["2026-10-04"])
        old = review.choose(items, stats, daily, day)
        new = review.choose(items, stats, daily, day, variant_shown=combined)
        self.assertEqual([q["family"] for q in old], [q["family"] for q in new])

    def test_same_family_rotates_qids_and_contexts_across_recent_rounds(self):
        items = [item("alpha", "a"), item("beta", "b"), item("gamma", "c")]
        history, picks = {}, []
        for offset in range(3):
            day = date(2026, 10, 6) + timedelta(days=offset)
            stats = review.make_stats(items, [], [], day)
            q = review.choose(items, stats, history, day, count=1)[0]
            picks.append(q["id"])
            history[day.isoformat()] = [q["id"]]
        self.assertEqual(len(set(picks)), 3)

    def test_article_variant_reads_passage_history_without_changing_family_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.rmtree(root / "data/article-reviews")
            shutil.copy(ROOT / "passage-drill-2026-09-30.html", root)
            review.save(root / "data/daily-history.json", {})
            review.save(root / "data/daily.json", {})
            session = {"id": "audit-passage-spacing", "date": "2026-10-05", "source": "Fixture",
                       "focus_families": ["cling-climb"], "max_current": 1,
                       "_created_at": datetime.fromisoformat("2026-10-05T12:00:00+08:00"), "_path": "fixture"}
            with mock.patch.object(review, "choose", wraps=review.choose) as choose:
                payload = article_review.make_payload(root, session, review.bank(root), {}, "owner/repo")
            self.assertNotIn("2026-09-30", choose.call_args.args[2])
            self.assertIn("cling-policy-a", choose.call_args.kwargs["variant_shown"]["2026-09-30"])
            self.assertEqual(next(q["id"] for q in payload["questions"] if q["family"] == "cling-climb"),
                             "cling-rail-b")

    def test_archived_retry_availability_and_aliases_do_not_inflate_exposure(self):
        rounds = audit.published_rounds(ROOT)
        keys = [r["id"] for r in rounds]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertFalse(any(r.startswith("latest:") for r in keys))
        result = audit.report(ROOT, date(2026, 10, 5))
        for key, row in result["questions"].items():
            if row["pool"].startswith("archive"):
                self.assertEqual(row["times_shown"], 0)
        self.assertTrue(all(event["round"] for q in result["questions"].values() for event in q["published_rounds"]))

    def test_new_bank_items_do_not_create_exposures_answers_or_errors(self):
        result = audit.report(ROOT, date(2026, 10, 5))
        actual_qids = {r.get("qid") for r in review.load(ROOT / "data/result-evidence.json")["rows"]}
        published_qids = {qid for r in audit.published_rounds(ROOT) if r["date"] <= "2026-10-05" for qid in r["qids"]}
        for q in review.load(ROOT / "data/questions/2026-10-05-context-gaps.json"):
            row = result["questions"][q["id"]]
            self.assertEqual(row["times_answered"], sum(r.get("qid") == q["id"] and r["date"] <= "2026-10-05"
                for r in review.load(ROOT / "data/result-evidence.json")["rows"]))
            if q["id"] not in published_qids and q["id"] not in actual_qids:
                self.assertEqual(row["times_shown"], 0)
                self.assertEqual(row["errors"], 0)
                self.assertEqual(row["visibility"], "no_repository_exposure_record")

    def test_unknown_legacy_question_identity_is_not_fabricated(self):
        result = audit.report(ROOT, date(2026, 10, 5))
        self.assertGreater(result["families"]["reference"]["unknown_qid_attempts"], 0)
        for row in result["questions"].values():
            if row["pool"] == "legacy_fixed":
                self.assertIsNone(row["qid"])
                self.assertEqual(row["times_answered"], 0)

    def test_locked_daily_all_evidence_and_article_partb_history_remain_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "web", root / "web")
            for path in ROOT.glob("*.html"):
                shutil.copy(path, root / path.name)
            locked_day = date.fromisoformat(review.load(root / "data/daily.json")["date"])
            paths = [*root.glob("*.html"), *(root / "data").rglob("*.json")]
            before = {p: p.read_bytes() for p in paths}
            run(root, locked_day, False, "pkppkqbobs/kaoyan-english-trainer")
            article_review.build(root)
            partb_review.build(root)
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content, str(path))

    def test_audit_and_extra_source_check_cannot_enter_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copy(ROOT / "index.html", root / "index.html")
            rows = review.load(root / "data/result-evidence.json")["rows"]
            notes = review.load(root / "data/learning-notes.json")
            day = date.fromisoformat(review.load(root / "data/review-state.json")["as_of"])
            before = review.make_stats(review.bank(root), rows, notes, day)
            review.save(root / "data/question-bank-audit.json", {"rows": [{"family": "point", "errors": 99}]})
            review.save(root / "data/source-checks/not-a-question.json", [item("fake-question")])
            self.assertNotIn("fake-question", {q["id"] for q in review.bank(root)})
            self.assertEqual(review.make_stats(review.bank(root), rows, notes, day), before)
            self.assertNotIn("fake-question", audit.catalogue(root))

    def test_existing_scores_and_streaks_are_identical_after_bank_expansion(self):
        data = review.load(ROOT / "data/result-evidence.json")
        state = review.load(ROOT / "data/review-state.json")
        stats = review.make_stats(review.bank(ROOT), data["rows"], review.load(ROOT / "data/learning-notes.json"),
                                  date.fromisoformat(state["as_of"]))
        self.assertEqual(stats, state["families"])

    def test_partb_pair_family_rows_count_as_one_passage_in_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copy(ROOT / "index.html", root / "index.html")
            q = partb_review.bank(root)[0]
            obj = {"version": 4, "module": "partb", "roundId": "audit-fixture", "date": "2026-10-05", "answers": [{
                "kind": "paragraph_order", "qid": q["id"], "mode": "main", "pickOrder": list(reversed(q["expectedOrder"])),
                "expectedOrder": q["expectedOrder"], "ms": 120000, "uncertain": True}]}
            issue = {"number": 999, "created_at": "2026-10-05T07:00:00Z"}
            _, rows = partb_review.parse_report(obj, issue, root)
            review.save(root / "data/result-evidence.json", {"rows": rows, "issues": [999]})
            result = audit.report(root, date(2026, 10, 5))
            self.assertEqual(result["questions"][q["id"]]["times_answered"], 1)
            self.assertEqual(result["questions"][q["id"]]["errors"], 1)


if __name__ == "__main__":
    unittest.main()
