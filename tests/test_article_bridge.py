"""Paper learning, published review opportunities and real grades stay separate."""
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import article_review as article
import daily_review as review
import build_session_handoff as handoff
from test_article_review import fixture, session, q


class ArticleBridgeTests(unittest.TestCase):
    def test_backfill_uses_original_learning_priority_without_backdating_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            focus, _ = fixture(root)
            session(root, 'original-round', focus)
            article.build(root)
            old = {p: p.read_bytes() for p in [*root.glob('article-review-original*.html'),
                   *root.glob('data/article-reviews/*.json'), root / 'today.html',
                   root / 'data/daily.json', root / 'data/result-evidence.json']}
            notes = review.load(root / 'data/learning-notes.json')
            for n in notes:
                n['session_id'] = 'backfilled-round'
            notes[1]['kind'] = 'user_reported_wrong'
            review.save(root / 'data/learning-notes.json', notes)
            path = session(root, 'backfilled-round', focus, created='2026-10-27T10:00:00+09:00', day='2026-10-27')
            obj = review.load(path)
            obj.update(learning_date='2026-10-03', max_current=1)
            review.save(path, obj)
            payload = article.build(root)
            self.assertEqual(payload['date'], '2026-10-27')
            self.assertEqual(payload['article_session']['learning_date'], '2026-10-03')
            self.assertEqual(payload['article_session']['current_families'], [focus[1]])
            self.assertEqual({p: p.read_bytes() for p in old}, old)
            # The newly published qid must not appear as an October 3 opportunity.
            current = next(item['id'] for item in payload['questions'] if item['family'] == focus[1])
            original_ids = {item['id'] for item in review.load(root / 'data/article-reviews/original-round.json')['questions']}
            history = review.variant_history(root, date(2026, 10, 27))
            self.assertIn(current, history['2026-10-27'])
            self.assertEqual(set(history['2026-10-03']), original_ids)

    def test_future_learning_date_fails_before_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root)
            path = session(root, 'invalid-dates', focus)
            obj = review.load(path); obj['learning_date'] = '2026-10-04'; review.save(path, obj)
            with self.assertRaisesRegex(ValueError, 'learning_date'):
                article.build(root)
            self.assertFalse((root / 'article-review.html').exists())

    def test_curated_focus_must_be_available_and_in_its_family(self):
        for qid in ('missing-question', 'history-0-one', 'future-target'):
            with self.subTest(qid=qid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); focus, _ = fixture(root)
                items = review.load(root / 'data/base-bank.json')
                items.append(q('future-target', focus[0], introduced='2026-10-04'))
                review.save(root / 'data/base-bank.json', items)
                path = session(root, 'curated-round', focus)
                obj = review.load(path); obj['focus_question_ids'] = {focus[0]: [qid]}; review.save(path, obj)
                with self.assertRaisesRegex(ValueError, 'Focus question'):
                    article.build(root)
                self.assertFalse((root / 'article-review.html').exists())

    def test_curated_focus_and_balancing_use_option_spread_not_answer_length(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root, current=1)
            items = review.load(root / 'data/base-bank.json')
            wanted = next(item for item in items if item['id'] == focus[0] + '-one')
            wanted['o'] = ['first', 'longer', 'third', 'final']
            review.save(root / 'data/base-bank.json', items)
            path = session(root, 'curated-round', focus)
            obj = review.load(path)
            obj.update(balanced_options=True, focus_question_ids={focus[0]: [wanted['id']]})
            review.save(path, obj)
            payload = article.build(root)
            chosen = next(item for item in payload['questions'] if item['family'] == focus[0])
            self.assertEqual(chosen['id'], wanted['id'])
            self.assertEqual(chosen['o'][chosen['a']], 'longer', 'Correct-longest is allowed within the sheet limit')

    def test_handoff_distinguishes_notes_missing_session_missing_round_and_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root)
            entries = [{'session_id': 'new-paper', 'family': focus[0], 'date': '2026-10-03',
                        'kind': 'user_reported_confusion', 'source_exam': '2014-english1',
                        'source_part': 'Reading Text 4'}]
            source = handoff.Inputs(root)
            missing = handoff.article_coverage(source, entries, {})
            self.assertEqual(missing['pending'][0]['status'], 'missing_session')
            self.assertTrue(any('尚无可用文章专项复盘' in warning for warning in source.warnings))
            path = session(root, 'new-paper', focus)
            sessions = {'new-paper': str(path.relative_to(root))}
            self.assertEqual(handoff.article_coverage(handoff.Inputs(root), entries, sessions)['pending'][0]['status'], 'missing_round')
            before = (root / 'data/result-evidence.json').read_bytes()
            article.build(root)
            coverage = handoff.article_coverage(handoff.Inputs(root), entries, sessions)
            self.assertEqual(coverage['pending'], [])
            self.assertEqual(coverage['recent'][0]['status'], 'published')
            self.assertEqual((root / 'data/result-evidence.json').read_bytes(), before)
            (root / 'article-review-new-paper.html').unlink()
            self.assertEqual(handoff.article_coverage(handoff.Inputs(root), entries, sessions)['pending'][0]['status'], 'missing_round')

    def test_recent_eight_paper_stages_have_published_rounds_without_fake_results(self):
        notes = review.load(ROOT / 'data/learning-notes.json')
        expected = {n['session_id'] for n in notes if '2026-10-19' <= n['date'] <= '2026-10-26' and n.get('session_id')}
        self.assertEqual(len(expected), 8)
        definitions = {s['id']: s for s in article.sessions(ROOT)}
        self.assertLessEqual(expected, definitions.keys())
        for sid in expected:
            payload = review.load(ROOT / f'data/article-reviews/{sid}.json')
            self.assertEqual(payload['date'], '2026-10-27')
            self.assertLess(payload['article_session']['learning_date'], payload['date'])
        evidence = review.load(ROOT / 'data/result-evidence.json')
        rows = [r for r in evidence['rows'] if r['origin'] == 29]
        rounds, _ = handoff.web_results(handoff.Inputs(ROOT), {'issues': [29], 'rows': rows})
        self.assertEqual((rounds['daily']['issue'], rounds['daily']['correct']), (29, 8))


if __name__ == '__main__':
    unittest.main()
