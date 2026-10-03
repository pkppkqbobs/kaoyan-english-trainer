import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import daily_review as review
import article_review


def q(qid, family, introduced=None):
    return {
        "id": qid,
        "family": family,
        "introduced": introduced,
        "target": family,
        "skill": family,
        "q": "A complete transfer question for " + family + " with enough text.",
        "o": ["one", "two", "three", "four"],
        "a": 1,
        "budget": 35,
        "exp": {key: "Explanation for " + key for key in review.EXP_KEYS},
    }


class ArticleReviewTests(unittest.TestCase):
    def test_no_session_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(article_review.build(root))

    def test_mixes_current_article_and_historical_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/article-sessions").mkdir(parents=True)
            (root / "data/questions").mkdir(parents=True)
            (root / "web").mkdir(parents=True)
            current = ["current-a", "current-b", "current-c", "current-d"]
            historical = [f"history-{i}" for i in range(8)]
            items = [q("q-" + f, f, "2026-10-03" if f in current else None) for f in current + historical]
            review.save(root / "data/base-bank.json", items)
            review.save(root / "data/result-evidence.json", {"rows": [], "issues": []})
            review.save(root / "data/learning-notes.json", [
                {"family": f, "date": "2026-10-03", "kind": "translation_difficulty"} for f in current
            ])
            review.save(root / "data/daily-history.json", {})
            review.save(root / "data/daily.json", {"date": "2026-10-03", "questions": []})
            review.save(root / "data/article-sessions/2026-10-03-test.json", {
                "id": "2026-10-03-test",
                "date": "2026-10-03",
                "source": "test passage",
                "focus_families": current,
                "max_current": 4,
            })
            (root / "web/review.js").write_text("// fixture", encoding="utf-8")
            payload = article_review.build(root)
            self.assertEqual(len(payload["questions"]), 8)
            families = [x["family"] for x in payload["questions"]]
            self.assertEqual(len(set(families)), 8)
            self.assertEqual(set(payload["article_session"]["current_families"]), set(current))
            self.assertEqual(len(payload["article_session"]["historical_families"]), 4)
            self.assertEqual(payload["storagePrefix"], "kaoyan.article.v1.")
            self.assertEqual(payload["storageId"], "2026-10-03-test")
            self.assertTrue((root / "article-review.html").exists())
            archived = root / "data/article-reviews/2026-10-03-test.json"
            self.assertTrue(archived.exists())
            self.assertEqual(json.loads(archived.read_text(encoding="utf-8"))["article_session"]["id"], "2026-10-03-test")


if __name__ == "__main__":
    unittest.main()
