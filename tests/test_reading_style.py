import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_review as review
import article_review


def question(qid, family, reading=False):
    q = {'id': qid, 'family': family, 'introduced': None, 'budget': 35,
         'target': 'internal mechanism', 'q': 'The author suggests that' if reading else 'A legacy question about ' + qid,
         'o': ['first', 'other', 'third', 'final'], 'a': 1,
         'exp': {key: 'Explanation ' + key for key in review.EXP_KEYS}}
    if reading:
        q.update(format='english1_reading', published_on='2026-10-03', reading_budget=120,
                 passage=('The report describes a local project and the people who rely on it. ' * 6) + qid,
                 answer_support='The report describes a local project')
    return q


def fixture(root):
    (root / 'web').mkdir()
    (root / 'web/review.js').write_text('// fixture')
    (root / 'today.html').write_text('locked daily')
    items = [question(f'old-{i}', f'family-{i}') for i in range(8)]
    items += [question(f'reading-{i}', f'family-{i}', True) for i in range(8)]
    review.save(root / 'data/base-bank.json', items)
    review.save(root / 'data/result-evidence.json', {'rows': [], 'issues': []})
    review.save(root / 'data/learning-notes.json', [])
    return items


class ReadingStyleTests(unittest.TestCase):
    def test_common_exam_stem_requires_distinct_material_and_exact_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = fixture(root)
            self.assertEqual(len(review.bank(root)), 16)
            items[-1]['passage'] = items[-2]['passage']
            review.save(root / 'data/base-bank.json', items)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                review.bank(root)

    def test_reading_requires_material_locatable_support_and_its_own_time_allowance(self):
        q = question('reading-test', 'reading', True)
        for key, value in [('passage', ''), ('answer_support', 'not in the material'), ('reading_budget', 0)]:
            broken = copy.deepcopy(q)
            broken[key] = value
            with self.assertRaises(AssertionError):
                review.validate(broken)
        review.validate(question('legacy-test', 'reading'))

    def test_retirement_changes_future_availability_and_retry_not_scores_or_original_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = fixture(root)
            before = (root / 'data/base-bank.json').read_bytes()
            rows = [{'family': 'family-0', 'date': '2026-10-02', 'ok': False, 'ms': 40000}]
            stats = review.make_stats(items, rows, [], date(2026, 10, 3))
            review.save(root / 'data/question-retirements.json', {'questions': {
                'old-0': {'family': 'family-0', 'retired_on': '2026-10-03'}}})
            changed = review.bank(root)
            retired = next(q for q in changed if q['id'] == 'old-0')
            self.assertTrue(review.available(retired, date(2026, 10, 2)))
            self.assertFalse(review.available(retired, date(2026, 10, 3)))
            self.assertEqual([q['id'] for q in review.retry_variants(changed, retired, date(2026, 10, 3))], ['reading-0'])
            self.assertEqual(review.make_stats(changed, rows, [], date(2026, 10, 3)), stats)
            self.assertEqual((root / 'data/base-bank.json').read_bytes(), before)

    def test_retirement_cannot_silently_refer_to_unknown_or_different_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            for qid, family in [('unknown-id', 'family-0'), ('old-0', 'another-family')]:
                review.save(root / 'data/question-retirements.json', {'questions': {
                    qid: {'family': family, 'retired_on': '2026-10-03'}}})
                with self.assertRaisesRegex(AssertionError, 'Retirement'):
                    review.bank(root)

    def test_reading_round_filters_current_history_and_retry_without_rewriting_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            def session(key, day, reading=False):
                value = {'id': key, 'date': day, 'source': key,
                         'focus_families': [f'family-{i}' for i in range(4)], 'balanced_options': True,
                         'created_at': day + 'T12:00:00+08:00'}
                if reading:
                    value['question_format'] = 'english1_reading'
                review.save(root / f'data/article-sessions/{key}.json', value)
            session('legacy-session', '2026-10-02')
            article_review.build(root)
            paths = [root / 'data/article-reviews/legacy-session.json', root / 'article-review-legacy-session.html']
            before = [p.read_bytes() for p in paths]
            session('reading-session', '2026-10-03', True)
            payload = article_review.build(root)
            self.assertEqual(len(payload['questions']), 8)
            self.assertTrue(all(q['format'] == 'english1_reading' for q in payload['questions']))
            self.assertEqual(len(payload['article_session']['current_families']), 4)
            self.assertEqual(len(payload['article_session']['historical_families']), 4)
            self.assertTrue(all(q['format'] == 'english1_reading' for pool in payload['retry'].values() for q in pool))
            self.assertEqual([p.read_bytes() for p in paths], before)
            self.assertEqual((root / 'today.html').read_text(), 'locked daily')

    def test_reading_time_threshold_comes_from_verified_snapshot_and_does_not_change_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = fixture(root)
            for reading, day in [(False, '2026-10-02'), (True, '2026-10-03')]:
                q = items[8 if reading else 0]
                review.save(root / f'data/days/{day}.json', {'date': day, 'questions': [q]})
                obj = {'version': 3, 'roundId': 'round-' + day, 'date': day, 'module': 'daily', 'storageId': day,
                       'answers': [{'qid': q['id'], 'family': q['family'], 'kind': 'main', 'answeredOn': day,
                                    'pick': 1, 'expected': 1, 'ok': True, 'ms': 90000, 'optionOrder': [0, 1, 2, 3],
                                    'slow_threshold_ms': 999999}]}
                issue = {'number': 1, 'created_at': '2026-10-03T12:00:00Z',
                         'title': '[TRAINING_RESULT] ' + day,
                         'body': '<!-- review-json:v3\n' + json.dumps(obj) + '\n-->'}
                _, rows = review.parse_issue(issue, root)
                if reading:
                    self.assertEqual(rows[0]['slow_threshold_ms'], 120000)
                else:
                    self.assertNotIn('slow_threshold_ms', rows[0])
                stats = review.make_stats(items, rows, [], date(2026, 10, 3))
                self.assertEqual(stats['family-0']['slow_or_uncertain'], not reading)


if __name__ == '__main__':
    unittest.main()
