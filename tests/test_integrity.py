"""Adversarial reports and regeneration use temporary data only."""
import contextlib
import copy
from datetime import date
import io
import itertools
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import daily_review as review
from run_daily import run, apply_exclusions


def fixture(root, day="2026-10-07"):
    items = [{"id": f"fixture-{i}", "family": f"family-{i}", "introduced": None,
              "published_on": "2026-10-05", "target": f"Target {i}",
              "q": f"A distinct complete fixture sentence number {i}.",
              "o": ["one", "two", "three", "four"], "a": 1, "budget": 35,
              "exp": {key: "Fixture explanation" for key in review.EXP_KEYS}} for i in range(8)]
    review.save(root / "data/base-bank.json", items)
    review.save(root / "data/result-evidence.json", {"rows": [], "issues": []})
    review.save(root / "data/learning-notes.json", [])
    (root / "web").mkdir()
    shutil.copy(ROOT / "web/review.js", root / "web/review.js")
    with contextlib.redirect_stdout(io.StringIO()):
        run(root, date.fromisoformat(day), False, "pkppkqbobs/kaoyan-english-trainer")
    return items


def report(q, day="2026-10-07", **answer_fields):
    answer = {"qid": q["id"], "family": q["family"], "kind": "main", "pick": 1,
              "expected": 1, "ok": True, "ms": 1000, "uncertain": False,
              "optionOrder": [0, 1, 2, 3], "answeredOn": "2026-10-07", **answer_fields}
    return {"version": 3, "module": "daily", "storageId": day, "date": day,
            "roundId": "fixture-round", "answers": [answer]}


def issue(obj, number=71):
    return {"number": number, "created_at": "2026-10-07T08:00:00Z", "user": {"login": "pkppkqbobs"},
            "title": "[TRAINING_RESULT] fixture " + obj.get("date", "2026-10-07"),
            "body": "<!-- kaoyan-english-training-result -->\n<!-- review-json:v3\n" + json.dumps(obj) + "\n-->"}


class ReportIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.items = fixture(self.root)
        self.q = self.items[0]

    def parse(self, obj):
        return review.parse_issue(issue(obj), self.root)[1]

    def test_all_24_option_permutations_and_four_choices_use_repository_key(self):
        for order in itertools.permutations(range(4)):
            for pick in range(4):
                expected = list(order).index(self.q["a"])
                with self.subTest(order=order, pick=pick):
                    obj = report(self.q, pick=pick, expected=expected,
                                 optionOrder=list(order), ok=not (pick == expected))
                    rows = self.parse(obj)
                    self.assertEqual(rows[0]["ok"], order[pick] == self.q["a"])

    def test_consistent_but_false_client_key_is_rejected(self):
        with self.assertRaises(ValueError):
            self.parse(report(self.q, pick=0, expected=0, ok=True))

    def test_duplicate_main_question_rows_are_rejected(self):
        obj = report(self.q)
        for extra in [copy.deepcopy(obj["answers"][0]), {**obj["answers"][0], "family": "family-1"}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.parse({**obj, "answers": obj["answers"] + [extra]})

    def test_retry_row_does_not_add_an_attempt(self):
        obj = report(self.q)
        obj["answers"].append({"kind": "retry"})
        self.assertEqual(len(self.parse(obj)), 1)

    def test_broken_or_ambiguous_json_marker_cannot_fall_back_to_plaintext_grading(self):
        original = issue(report(self.q))
        for block in ["<!-- review-json:v3\n{", "<!-- review-json:v4\n{", "<!-- review-json:v5\n{}\n-->",
                      original["body"] + "\n<!-- review-json:v3\n{}\n-->"]:
            body = "Q1 family-0：选A→正确A；正确；1s\n" + block
            with self.subTest(block=block), self.assertRaises(ValueError):
                review.parse_issue({**original, "body": body}, self.root)

    def test_future_report_and_future_or_prepublication_answer_dates_are_rejected(self):
        obj = report(self.q, day="2026-10-08")
        with self.assertRaises(ValueError):
            self.parse(obj)
        for stamp in ["2026-10-08", "2026-10-06", "not-a-date"]:
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                self.parse(report(self.q, answeredOn=stamp))

    def test_later_issue_edit_accepts_actual_answer_day_without_redating_prior_answers(self):
        review.save(self.root / "data/days/2026-10-05.json", {"date": "2026-10-05", "questions": self.items})
        obj = report(self.q, day="2026-10-05")
        old = {**obj["answers"][0], "qid": self.items[1]["id"], "family": self.items[1]["family"], "answeredOn": "2026-10-06"}
        obj["answers"].append(old)
        edited = {**issue(obj), "created_at": "2026-10-06T08:00:00Z", "updated_at": "2026-10-07T08:00:00Z"}
        rows = review.parse_issue(edited, self.root)[1]
        self.assertEqual([r["date"] for r in rows], ["2026-10-07", "2026-10-06"])
        obj["answers"][0]["answeredOn"] = "2026-10-08"
        with self.assertRaises(ValueError):
            review.parse_issue({**edited, "body": issue(obj)["body"]}, self.root)

    def test_revision_timestamp_uses_beijing_day_and_never_invents_answer_day(self):
        obj = report(self.q, answeredOn="2026-10-08")
        edited = {**issue(obj), "updated_at": "2026-10-07T16:05:00Z"}
        self.assertEqual(review.parse_issue(edited, self.root)[1][0]["date"], "2026-10-08")
        del obj["answers"][0]["answeredOn"]
        unknown = review.parse_issue({**edited, "body": issue(obj)["body"]}, self.root)[1][0]
        self.assertTrue(unknown["date_unverified"])
        self.assertEqual(review.make_stats(self.items, [unknown], [], date(2026, 10, 8))[self.q["family"]]["streak"], 0)

    def test_unknown_question_family_and_storage_namespace_are_rejected(self):
        for extra in [{"qid": "unknown-id"}, {"family": "family-1"}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.parse(report(self.q, **extra))
        for module, key in [("article", "2026-10-07"), ("daily", "../secret"), ("daily", "2026-10-06"), ("unknown", "2026-10-07")]:
            with self.subTest(module=module, key=key), self.assertRaises(ValueError):
                self.parse({**report(self.q), "module": module, "storageId": key})

    def test_invalid_option_mappings_are_rejected(self):
        for order in [[0, 0, 2, 3], [0, 1, 2], [0, 1, 2, 3, 4], [True, 0, 2, 3], [0, 1, 2, 3.0], "0123", None]:
            with self.subTest(order=order), self.assertRaises(ValueError):
                self.parse(report(self.q, optionOrder=order))

    def test_old_local_history_can_use_saved_choice_text_without_reset(self):
        obj = report(self.q, pick=0, expected=1, ok=True, pickText="one", expectedText="two")
        del obj["answers"][0]["optionOrder"]
        self.assertFalse(self.parse(obj)[0]["ok"])
        obj["answers"][0]["expectedText"] = "one"
        with self.assertRaises(ValueError):
            self.parse(obj)

    def test_wrong_current_bank_key_cannot_regrade_a_published_round(self):
        changed = copy.deepcopy(self.items)
        changed[0]["a"] = 0
        review.save(self.root / "data/base-bank.json", changed)
        self.assertTrue(self.parse(report(self.q))[0]["ok"])

    def test_legacy_v3_without_permutation_keeps_its_original_evidence(self):
        obj = report(self.q)
        del obj["module"]
        del obj["storageId"]
        del obj["answers"][0]["optionOrder"]
        del obj["answers"][0]["answeredOn"]
        self.assertEqual(self.parse(obj), [{"date": "2026-10-07", "family": self.q["family"], "ok": True,
                                         "ms": 1000, "uncertain": False, "origin": 71, "qid": self.q["id"]}])

    def test_new_page_report_cannot_silently_drop_its_verifiable_choices(self):
        obj = report(self.q)
        del obj["answers"][0]["optionOrder"]
        with self.assertRaises(ValueError):
            self.parse(obj)

    def test_new_page_report_requires_at_least_one_primary_answer(self):
        obj = report(self.q)
        for answers in [[], [{"kind": "retry"}]]:
            with self.subTest(answers=answers), self.assertRaises(ValueError):
                self.parse({**obj, "answers": answers})

    def test_empty_edited_legacy_report_keeps_previously_accepted_scores(self):
        original = issue(report(self.q))
        with mock.patch.object(review, "get_issues", return_value=[original]), contextlib.redirect_stdout(io.StringIO()):
            run(self.root, date(2026, 10, 7), True, "pkppkqbobs/kaoyan-english-trainer")
        accepted = (self.root / "data/result-evidence.json").read_bytes()
        empty = {"version": 3, "roundId": "fixture-round", "date": "2026-10-07", "answers": []}
        with mock.patch.object(review, "get_issues", return_value=[issue(empty)]), contextlib.redirect_stdout(io.StringIO()):
            run(self.root, date(2026, 10, 7), True, "pkppkqbobs/kaoyan-english-trainer")
        self.assertEqual((self.root / "data/result-evidence.json").read_bytes(), accepted)
        self.assertTrue(review.load(self.root / "data/rejected-results.json")["issues"][0]["retained_previous"])

    def test_two_old_daily_papers_completed_today_are_one_observed_day(self):
        for stamp in ["2026-10-05", "2026-10-06"]:
            review.save(self.root / f"data/days/{stamp}.json", {"date": stamp, "questions": self.items})
        a = report(self.q, day="2026-10-05")
        b = report(self.q, day="2026-10-06"); b["roundId"] = "second-round"
        rows, accepted = review.evidence([issue(a), issue(b, 72)], "pkppkqbobs", self.root)
        self.assertEqual(accepted, [71, 72])
        stats = review.make_stats(self.items, rows, [], date(2026, 10, 7))
        self.assertEqual(stats[self.q["family"]]["observed_days"], 1)
        self.assertEqual(stats[self.q["family"]]["streak"], 1)

    def test_old_local_answer_without_saved_date_never_creates_or_clears_mastery(self):
        obj = report(self.q); del obj["answers"][0]["answeredOn"]
        rows = self.parse(obj)
        self.assertTrue(rows[0]["date_unverified"])
        stats = review.make_stats(self.items, rows, [], date(2026, 10, 7))[self.q["family"]]
        self.assertEqual(stats["streak"], 0)
        self.assertEqual(stats["observed_days"], 0)
        self.assertIsNone(stats["last"])
        self.assertEqual(stats["errors"], 0)
        known = {**rows[0], "date": "2026-10-06"}; del known["date_unverified"]
        stats = review.make_stats(self.items, [known, *rows], [], date(2026, 10, 7))[self.q["family"]]
        self.assertEqual(stats["streak"], 1)
        self.assertEqual(stats["last"], "2026-10-06")

    def test_unknown_answer_day_does_not_clear_notes_and_unresolved_error_keeps_priority(self):
        row = self.parse(report(self.q))[0]
        notes = [{"family": self.q["family"], "date": "2026-10-04", "kind": "translation_difficulty"}]
        known = {**row, "date": "2026-10-05"}
        unknown = {**row, "date_unverified": True}
        stats = review.make_stats(self.items, [known, unknown], notes, date(2026, 10, 7))[self.q["family"]]
        self.assertTrue(stats["reported_confusion"])
        self.assertEqual(stats["errors"], 0)
        second_known = {**row, "date": "2026-10-06"}
        stats = review.make_stats(self.items, [known, second_known, {**unknown, "ok": False}], notes, date(2026, 10, 7))[self.q["family"]]
        self.assertTrue(stats["reported_confusion"])
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["streak"], 0)

    def test_dated_quality_exclusion_follows_source_not_late_answer_day(self):
        review.save(self.root / "data/days/2026-10-05.json", {"date": "2026-10-05", "questions": self.items})
        rows = self.parse(report(self.q, day="2026-10-05", pick=0, expected=1, ok=False))
        self.assertEqual(rows[0]["date"], "2026-10-07")
        accepted, excluded = apply_exclusions(rows, [{"family": self.q["family"], "date": "2026-10-05",
                                                     "qid": self.q["id"], "reason": "bad original version"}])
        self.assertEqual(accepted, [])
        self.assertEqual(len(excluded), 1)

    def test_same_second_duplicate_uses_first_issue_number(self):
        obj = report(self.q)
        _, ids = review.evidence([issue(obj, 72), issue(obj, 71)], "pkppkqbobs", self.root)
        self.assertEqual(ids, [71])

    def test_malformed_new_issue_is_quarantined_and_prior_grade_is_retained_and_deduped(self):
        original = issue(report(self.q))
        with mock.patch.object(review, "get_issues", return_value=[original]), contextlib.redirect_stdout(io.StringIO()):
            run(self.root, date(2026, 10, 7), True, "pkppkqbobs/kaoyan-english-trainer")
        saved = review.load(self.root / "data/result-evidence.json")["rows"][0]
        damaged = {**original, "body": "<!-- kaoyan-english-training-result -->\n<!-- review-json:v3\n[\n-->"}
        future = issue(report(self.q, day="2026-10-30"), 72)
        good = report(self.items[1]); good["roundId"] = "new-round"
        duplicate = {**original, "number": 74}
        with mock.patch.object(review, "get_issues", return_value=[damaged, future, issue(good, 73), duplicate]), contextlib.redirect_stdout(io.StringIO()):
            run(self.root, date(2026, 10, 7), True, "pkppkqbobs/kaoyan-english-trainer")
        data = review.load(self.root / "data/result-evidence.json")
        self.assertEqual(data["issues"], [71, 73])
        self.assertEqual(data["rows"][0], saved)
        self.assertEqual(len(data["rows"]), 2)
        rejected = review.load(self.root / "data/rejected-results.json")["issues"]
        self.assertEqual([(r["issue"], r["retained_previous"]) for r in rejected], [(71, True), (72, False)])

    def test_invalid_report_cannot_reintroduce_previously_excluded_evidence(self):
        review.save(self.root / "data/quality-exclusions.json", [{"origin": 71, "family": self.q["family"], "reason": "fixture exclusion"}])
        original = issue(report(self.q))
        with mock.patch.object(review, "get_issues", return_value=[original]), contextlib.redirect_stdout(io.StringIO()):
            run(self.root, date(2026, 10, 7), True, "pkppkqbobs/kaoyan-english-trainer")
        excluded = (self.root / "data/excluded-evidence.json").read_bytes()
        damaged = {**original, "body": "<!-- kaoyan-english-training-result -->\n<!-- review-json:v3\n[]\n-->"}
        with mock.patch.object(review, "get_issues", return_value=[damaged]), contextlib.redirect_stdout(io.StringIO()):
            run(self.root, date(2026, 10, 7), True, "pkppkqbobs/kaoyan-english-trainer")
        self.assertEqual(review.load(self.root / "data/result-evidence.json")["rows"], [])
        self.assertEqual((self.root / "data/excluded-evidence.json").read_bytes(), excluded)

    def test_rewinding_date_fails_before_any_data_or_page_write(self):
        paths = [*self.root.glob("*.html"), *(self.root / "data").rglob("*.json")]
        before = {p: p.read_bytes() for p in paths}
        with mock.patch.object(review, "get_issues") as fetch, self.assertRaises(ValueError):
            run(self.root, date(2026, 10, 6), True, "pkppkqbobs/kaoyan-english-trainer")
        fetch.assert_not_called()
        self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))

    def test_existing_dated_lock_is_reused_if_current_alias_is_missing(self):
        locked = review.load(self.root / "data/days/2026-10-07.json")
        (self.root / "data/daily.json").unlink()
        changed = copy.deepcopy(self.items); changed[0]["a"] = 0
        review.save(self.root / "data/base-bank.json", changed)
        with contextlib.redirect_stdout(io.StringIO()):
            payload = run(self.root, date(2026, 10, 7), False, "pkppkqbobs/kaoyan-english-trainer")
        self.assertEqual(payload["questions"], locked["questions"])
        self.assertEqual(payload["retry"], locked["retry"])


if __name__ == "__main__":
    unittest.main()
