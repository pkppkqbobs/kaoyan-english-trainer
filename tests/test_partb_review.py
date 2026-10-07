"""Ordering evidence is verified against immutable server keys, not client diagnostics."""
import copy
import json
from datetime import date
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import daily_review as review
import partb_review as partb
from run_daily import run


def fixture():
    text = ("A research group examined several proposed solutions before choosing one for a limited trial. "
            "The team recorded both the practical benefits and the remaining difficulties, since a successful "
            "trial would need to work outside the laboratory as well as under carefully controlled conditions.")
    links = [
        ("A", "B", ["topic-introduction"], False, "medium"),
        ("B", "C", ["anaphora", "problem-to-reason"], True, "strong"),
        ("C", "D", ["anaphora", "lexical-chain"], True, "strong"),
        ("D", "E", ["parallel"], False, "medium"),
        ("E", "F", ["conclusion"], True, "strong"),
    ]
    return {"id": "pb-test-v1", "kind": "paragraph_order", "published_on": "2026-10-04",
            "title": "Test ordering", "topic": "Research", "overview": "New context",
            "budget": 420, "paragraphs": [{"id": x, "text": text} for x in "ABCDEF"],
            "expectedOrder": list("ABCDEF"), "globalLogic": "Whole passage constraints", "themeTrap": "Themes alone",
            "links": [{"from": a, "to": b, "signals": signals, "anchor": anchor, "strength": strength,
                       "explanation": "Read the local evidence together with the whole passage.",
                       "evidence": [{"level": strength, "text": "Combined textual evidence."}]}
                      for a, b, signals, anchor, strength in links]}


def report(q, order=None, rid="pb-test-round", day="2026-10-04", mode="main", **fields):
    answer = {"kind": "paragraph_order", "mode": mode, "qid": q["id"],
              "pickOrder": list(order or q["expectedOrder"]), "expectedOrder": q["expectedOrder"],
              "ms": 180000, "uncertain": False, **fields}
    return {"version": 4, "module": "partb", "roundId": rid, "date": day, "answers": [answer]}


def issue(obj, number=200):
    return {"number": number, "user": {"login": "pkppkqbobs"},
            "title": "[TRAINING_RESULT] Part B " + obj["date"],
            "created_at": obj["date"] + "T13:00:00Z",
            "body": "<!-- kaoyan-english-training-result -->\n<!-- review-json:v4\n" + json.dumps(obj) + "\n-->"}


class PartBScoringTests(unittest.TestCase):
    def setUp(self):
        self.q = partb.validate_question(fixture())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        review.save(self.root / "data/partb-questions/test.json", [self.q])

    def parse(self, obj):
        return review.parse_issue(issue(obj), self.root)

    def test_full_order_and_anchor_accuracy(self):
        s = partb.score(self.q, list("ABCDEF"))
        self.assertTrue(s["fullOrderOk"])
        self.assertEqual(s["pairScore"], {"correct": 5, "total": 5})
        self.assertEqual(s["anchorScore"], {"correct": 3, "total": 3})
        self.assertTrue(s["startOk"] and s["endOk"])
        self.assertEqual(s["wrongPairs"], [])

    def test_all_wrong_reverse_order(self):
        s = partb.score(self.q, list("FEDCBA"))
        self.assertEqual(s["pairScore"]["correct"], 0)
        self.assertEqual(len(s["missedPairs"]), 5)
        self.assertEqual(len(s["wrongPairs"]), 5)
        self.assertFalse(s["startOk"] or s["endOk"])

    def test_partial_pairs_and_position_score_are_independent(self):
        s = partb.score(self.q, list("ACDBEF"))
        self.assertEqual(s["pairScore"]["correct"], 2)  # C→D and E→F
        self.assertEqual(s["hitPairs"], [{"from": "C", "to": "D"}, {"from": "E", "to": "F"}])
        self.assertIn({"from": "A", "to": "C"}, s["wrongPairs"])
        self.assertEqual(s["positionScore"]["correct"], 3)

    def test_correct_first_does_not_imply_correct_middle(self):
        s = partb.score(self.q, list("AFEDCB"))
        self.assertTrue(s["startOk"])
        self.assertFalse(s["endOk"] or s["fullOrderOk"])
        self.assertEqual(s["pairScore"]["correct"], 0)

    def test_correct_last_does_not_imply_correct_middle(self):
        s = partb.score(self.q, list("EDCBAF"))
        self.assertTrue(s["endOk"])
        self.assertFalse(s["startOk"] or s["fullOrderOk"])
        self.assertEqual(s["pairScore"]["correct"], 0)

    def test_duplicate_missing_extra_and_illegal_orders(self):
        for order in [[], list("ABCCEF"), list("ABCDE"), list("ABCDEFG"), list("ABCDEZ"),
                      "ABCDEF", None, [1, 2, 3, 4, 5, 6], {"A": 1}]:
            with self.subTest(order=order), self.assertRaises(ValueError):
                self.parse(report(self.q, pickOrder=order))

    def test_forged_ok_pairs_and_families_are_recomputed(self):
        _, rows = self.parse(report(self.q, "FEDCBA", ok=True, fullOrderOk=True,
                                  pairResults=[{"from": "A", "to": "B", "ok": True, "families": ["point"]}]))
        self.assertEqual({r["family"] for r in rows}, set(partb.FAMILIES))
        self.assertTrue(all(not r["ok"] for r in rows))
        self.assertEqual(rows[0]["partb_result"]["pairScore"]["correct"], 0)

    def test_expected_key_unknown_question_and_malformed_fields_fail(self):
        for field in [{"expectedOrder": list("FEDCBA")}, {"qid": "pb-unknown-v1"},
                      {"uncertain": "false"}, {"ms": True}, {"ms": float("nan")}, {"ms": -1},
                      {"mode": "observation"}, {"kind": "translation_difficulty"}]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.parse(report(self.q, **field))
        obj = report(self.q)
        obj["answers"].append(copy.deepcopy(obj["answers"][0]))
        with self.assertRaises(ValueError):
            self.parse(obj)

    def test_report_date_cannot_invent_a_future_day(self):
        obj = report(self.q, day="2026-10-05")
        entry = issue(obj)
        entry["created_at"] = "2026-10-04T13:00:00Z"
        with self.assertRaises(ValueError):
            review.parse_issue(entry, self.root)

    def test_later_issue_edit_can_report_later_actual_completion_but_not_a_future_day(self):
        obj = report(self.q, day="2026-10-05")
        edited = {**issue(obj), "created_at": "2026-10-04T13:00:00Z", "updated_at": "2026-10-05T13:00:00Z"}
        _, rows = review.parse_issue(edited, self.root)
        self.assertTrue(all(row["date"] == "2026-10-05" for row in rows))
        future = report(self.q, day="2026-10-06")
        with self.assertRaises(ValueError):
            review.parse_issue({**edited, "body": issue(future)["body"]}, self.root)

    def test_duplicate_issues_and_repeated_issue_are_counted_once(self):
        obj = report(self.q)
        one = issue(obj)
        rows, ids = review.evidence([one, one, issue(obj, 201)], "pkppkqbobs", self.root)
        self.assertEqual(len(rows), 2)
        self.assertEqual(ids, [200])

    def test_retry_does_not_overwrite_first_order_or_add_family_evidence(self):
        obj = report(self.q, "FEDCBA")
        obj["answers"].append(report(self.q, mode="retry")["answers"][0])
        _, rows = self.parse(obj)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["partb_result"]["pickOrder"], list("FEDCBA"))
        self.assertTrue(all(not r["ok"] for r in rows))
        self.assertEqual(self.parse(report(self.q, mode="retry"))[1], [])

    def test_many_missed_pairs_become_one_error_per_family(self):
        _, rows = self.parse(report(self.q, "FEDCBA"))
        items = [{"family": f, "budget": 55} for f in partb.FAMILIES]
        stats = review.make_stats(items, rows, [], date(2026, 10, 4))
        for f in partb.FAMILIES:
            self.assertEqual(stats[f]["errors"], 1)
            self.assertEqual(stats[f]["observed_days"], 1)
            self.assertEqual(stats[f]["streak"], 0)

    def test_same_day_daily_article_and_ordering_do_not_inflate_streak(self):
        _, rows = self.parse(report(self.q))
        items = [{"family": f, "budget": 55} for f in partb.FAMILIES]
        rows += [{"date": "2026-10-04", "family": f, "ok": True, "ms": 10000} for f in partb.FAMILIES]
        stats = review.make_stats(items, rows, [], date(2026, 10, 4))
        self.assertTrue(all(stats[f]["streak"] == 1 for f in partb.FAMILIES))
        # Three minutes for a whole passage is not a three-minute answer to a 55-second mini quiz.
        self.assertTrue(all(not stats[f]["slow_or_uncertain"] for f in partb.FAMILIES))
        self.assertTrue(all(stats[f]["observed_days"] == 1 for f in partb.FAMILIES))

    def test_cross_day_success_and_uncertain_remain_distinct(self):
        items = [{"family": f, "budget": 55} for f in partb.FAMILIES]
        rows = []
        for i in range(3):
            obj = report(self.q, rid="pb-day-" + str(i), day="2026-10-0" + str(4+i))
            rows += self.parse(obj)[1]
        stats = review.make_stats(items, rows, [], date(2026, 10, 6))
        self.assertTrue(all(stats[f]["streak"] == 3 for f in partb.FAMILIES))
        self.assertTrue(all(stats[f]["due"] == "2026-10-13" for f in partb.FAMILIES))
        rows += self.parse(report(self.q, rid="pb-uncertain", day="2026-10-07", uncertain=True))[1]
        stats = review.make_stats(items, rows, [], date(2026, 10, 7))
        self.assertTrue(all(stats[f]["errors"] == 0 and stats[f]["streak"] == 0 and
                            stats[f]["slow_or_uncertain"] for f in partb.FAMILIES))

    def test_translation_and_missing_2011_choices_never_create_pair_results(self):
        notes = review.load(ROOT / "data/learning-notes.json")
        source = review.load(ROOT / "data/source-checks/2011-english1.json")
        self.assertIn("缺少", source["performance_coverage"]["Part B"])
        items = [{"family": f, "budget": 55} for f in partb.FAMILIES]
        stats = review.make_stats(items, [], notes, date(2026, 10, 4))
        self.assertTrue(all(stats[f]["errors"] == 0 and stats[f]["observed_days"] == 0 for f in partb.FAMILIES))

    def test_v3_and_legacy_parser_are_unchanged(self):
        obj = {"roundId": "old-v3", "date": "2026-10-04", "answers": [
            {"family": "point", "pick": 1, "expected": 1, "ok": True, "ms": 1000}]}
        old = {"number": 1, "created_at": "2026-10-04T13:00:00Z", "body":
               "<!-- review-json:v3\n" + json.dumps(obj) + "\n-->"}
        rid, rows = review.parse_issue(old, self.root)
        self.assertEqual(rid, "old-v3")
        self.assertEqual(rows[0]["family"], "point")
        old["body"] = "Q1 point：选A→正确B；错误；1.0s"
        self.assertFalse(review.parse_issue(old)[1][0]["ok"])

    def test_published_question_cannot_be_rewritten_or_lost(self):
        review.save(self.root / "data/partb-reviews/pb-test-v1.json",
                    {"storageId": self.q["id"], "question": self.q})
        changed = copy.deepcopy(self.q)
        changed["expectedOrder"] = list("FEDCBA")
        review.save(self.root / "data/partb-questions/test.json", [changed])
        with self.assertRaises(ValueError):
            partb.bank(self.root)
        (self.root / "data/partb-questions/test.json").unlink()
        self.assertEqual(partb.bank(self.root), [self.q])


class PartBIntegrationTests(unittest.TestCase):
    def test_future_daily_has_only_one_partb_maintenance_slot(self):
        items = review.bank(ROOT)
        rows = review.load(ROOT / "data/result-evidence.json")["rows"]
        notes = review.load(ROOT / "data/learning-notes.json")
        for offset in range(5, 13):
            day = date(2026, 10, offset)
            stats = review.make_stats(items, rows, notes, day)
            selected = review.choose(items, stats, {}, day)
            self.assertEqual(len(selected), 8)
            self.assertLessEqual(sum(q["family"].startswith("paragraph-order-") for q in selected), 1)

    def test_new_materials_have_short_paragraphs_and_no_original_exam_passage(self):
        for q in partb.bank(ROOT):
            with self.subTest(qid=q["id"]):
                partb.validate_question(q)
                text = " ".join(p["text"] for p in q["paragraphs"])
                self.assertNotIn("Menand", text)
                self.assertNotIn("No disciplines have seized", text)
                self.assertNotIn("the great books are read", text)
                for p in q["paragraphs"]:
                    self.assertTrue(1 <= sum(p["text"].count(x) for x in (".", "?", "!")) <= 3)

    def test_actual_bank_quality_and_two_builds_preserve_every_old_training_file(self):
        questions = partb.bank(ROOT)
        self.assertGreaterEqual(len(questions), 6)
        self.assertGreaterEqual(len({q["topic"] for q in questions}), 6)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "web", root / "web")
            for p in ROOT.glob("*.html"):
                shutil.copy(p, root / p.name)
            protected = list(root.glob("article*.html")) + [root / "today.html", root / "data/daily.json",
                root / "data/days/2026-10-04.json", root / "data/result-evidence.json",
                root / "data/learning-notes.json", root / "data/source-checks/2011-english1.json",
                root / "data/review-state.json"]
            protected += list((root / "data/article-reviews").glob("*.json"))
            before = {p: p.read_bytes() for p in protected}
            first = partb.build(root)
            reported = review.load(root / "data/result-evidence.json")["rows"]
            self.assertEqual({r["roundId"] for r in first["results"]},
                             {r["partb_result"]["roundId"] for r in reported if r.get("partb_result")})
            second = {p: p.read_bytes() for p in list(root.glob("partb*.html")) +
                      list((root / "data/partb-reviews").glob("*.json"))}
            partb.build(root)
            self.assertTrue(all(p.read_bytes() == b for p, b in before.items()))
            self.assertTrue(all(p.read_bytes() == b for p, b in second.items()))
            for p in root.glob("partb*.html"):
                self.assertIn('name="viewport"', p.read_text())
                self.assertIn("partb-core.js?v=", p.read_text())

    def test_recommendation_changes_with_weak_and_stable_evidence_without_creating_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "web", root / "web")
            review.save(root / "data/result-evidence.json", {"rows": [], "issues": []})
            weak = {"as_of": "2026-10-04", "families": {f: {
                "streak": 0, "due": "2026-10-04", "reported_confusion": True,
                "errors": 0, "slow_or_uncertain": False} for f in partb.FAMILIES}}
            review.save(root / "data/review-state.json", weak)
            self.assertTrue(partb.build(root)["recommend"])
            self.assertEqual(review.load(root / "data/partb-results.json"), [])
            for stat in weak["families"].values():
                stat.update(streak=3, reported_confusion=False, errors=2, slow_or_uncertain=True)
            review.save(root / "data/review-state.json", weak)
            self.assertFalse(partb.build(root)["recommend"])
            self.assertEqual(review.load(root / "data/result-evidence.json"), {"rows": [], "issues": []})

    def test_compatible_shared_script_fix_keeps_published_pages_and_snapshots_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "web", root / "web")
            for page in ROOT.glob("partb*.html"):
                shutil.copy(page, root / page.name)
            protected = list(root.glob("partb*.html")) + list((root / "data/partb-reviews").glob("*.json"))
            before = {p: p.read_bytes() for p in protected}
            for name in ("partb.js", "partb-core.js", "partb-home.js"):
                with (root / "web" / name).open("a") as handle:
                    handle.write("\n// Compatible shared asset correction.\n")
            partb.build(root)
            self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))

    def test_sync_parser_updates_family_and_history_but_keeps_locked_questions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "web", root / "web")
            shutil.copy(ROOT / "today.html", root / "today.html")
            q = partb.bank(root)[0]
            entry = issue(report(q, list(reversed(q["expectedOrder"]))))
            original = copy.deepcopy(entry)
            old_qs = review.load(root / "data/daily.json")["questions"]
            locked_day = date.fromisoformat(review.load(root / "data/daily.json")["date"])
            with mock.patch.object(review, "get_issues", return_value=[entry, entry]):
                run(root, locked_day, True, "pkppkqbobs/kaoyan-english-trainer")
            self.assertEqual(entry, original)
            self.assertEqual(review.load(root / "data/daily.json")["questions"], old_qs)
            payload = partb.build(root)
            self.assertEqual(len(payload["results"]), 1)
            state = review.load(root / "data/review-state.json")["families"]
            self.assertTrue(all(state[f]["errors"] == 1 for f in partb.FAMILIES))

    def test_invalid_bank_leaves_previous_pages_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review.save(root / "data/partb-questions/bad.json", [fixture()])
            (root / "partb-review.html").write_text("previous usable page")
            (root / "partb-history.html").write_text("previous history")
            bad = fixture()
            bad["paragraphs"][1]["id"] = "A"
            review.save(root / "data/partb-questions/bad.json", [bad])
            with self.assertRaises(ValueError):
                partb.build(root)
            self.assertEqual((root / "partb-review.html").read_text(), "previous usable page")
            self.assertEqual((root / "partb-history.html").read_text(), "previous history")

    def test_real_frontend_report_and_python_node_scores_agree(self):
        result = subprocess.run(["node", "tests/partb-ui.mjs", "--report"], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        obj = json.loads(result.stdout)
        _, rows = review.parse_issue(issue(obj), ROOT)
        expected = rows[0]["partb_result"]
        self.assertEqual(expected["pickOrder"], obj["answers"][0]["pickOrder"])
        self.assertEqual(expected["pairResults"], obj["answers"][0]["pairResults"])
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
