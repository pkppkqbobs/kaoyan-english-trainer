import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('review', ROOT / 'scripts/daily_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def issue(number, body, day='2026-09-28', owner='pkppkqbobs'):
    return {'number': number, 'created_at': day + 'T12:00:00Z', 'user': {'login': owner},
            'title': '[TRAINING_RESULT] test ' + day, 'body': '<!-- kaoyan-english-training-result -->\n' + body}


def sample(qid, family, introduced=None):
    return {'id': qid, 'family': family, 'introduced': introduced, 'target': family, 'skill': family,
            'q': 'A complete test sentence for ' + qid + '.', 'o': ['one', 'two', 'three', 'four'], 'a': 1,
            'exp': {key: 'Explanation for ' + key for key in review.EXP_KEYS}}


class ReviewTests(unittest.TestCase):
    def test_old_detailed_report(self):
        body = 'Q1 be subject to / be subjected to：选A→正确A；正确；48.5s\nQ2 原词复现 vs 明确回指：选B→正确A；错误；28.7s\nQ3 介词 + which：选A→正确A；正确；45.4s'
        _, rows = review.parse_issue(issue(2, body))
        self.assertEqual([r['family'] for r in rows], ['subject', 'reference', 'relative'])
        self.assertEqual([r['ok'] for r in rows], [True, False, True])
        self.assertEqual(rows[0]['ms'], 48500)

    def test_original_aggregate_and_diagnosis(self):
        body = '原词复现干扰：1/2，平均 14s\nsubject / be subject to：1/1，平均 128s\nQ1 原词复现干扰：选C→正确A；出现 costs 但对象换了；18.1s'
        _, rows = review.parse_issue(issue(1, body))
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(r['family'] == 'reference' for r in rows), 1)
        self.assertFalse(rows[0]['ok'])
        self.assertEqual(rows[1]['ms'], 128000)

    def test_only_owner_reports_and_dedup(self):
        obj = {'roundId': 'same-round', 'date': '2026-09-28', 'answers': [{'family': 'point', 'ok': False, 'ms': 9000}]}
        body = '<!-- review-json:v3\n' + json.dumps(obj) + '\n-->'
        rows, ids = review.evidence([issue(1, body), issue(2, body), issue(3, body, owner='stranger')], 'pkppkqbobs')
        self.assertEqual(len(rows), 1)
        self.assertEqual(ids, [1])

    def test_same_day_successes_do_not_fake_mastery(self):
        items = [sample('point-one', 'point')]
        rows = [{'family': 'point', 'date': '2026-09-28', 'ok': True, 'ms': 1000}] * 3
        stats = review.make_stats(items, rows, [], date(2026, 9, 29))
        self.assertEqual(stats['point']['streak'], 1)
        rows += [{'family': 'point', 'date': '2026-09-29', 'ok': True, 'ms': 1000}]
        stats = review.make_stats(items, rows, [], date(2026, 9, 29))
        self.assertEqual(stats['point']['streak'], 2)
        self.assertEqual(stats['point']['due'], '2026-10-03')

    def test_retry_is_not_mastery_evidence(self):
        obj = {'roundId': 'r', 'date': '2026-09-28', 'answers': [
            {'family': 'point', 'ok': False, 'ms': 9000, 'kind': 'main'},
            {'family': 'point', 'ok': True, 'ms': 1000, 'kind': 'retry'}]}
        _, rows = review.parse_issue(issue(1, '<!-- review-json:v3\n' + json.dumps(obj) + '\n-->'))
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['ok'])

    def test_chat_note_not_a_scored_attempt(self):
        stats = review.make_stats([sample('point-one', 'point')], [], [{'family': 'point', 'date': '2026-09-29'}], date(2026, 9, 29))
        self.assertEqual(stats['point']['errors'], 0)
        self.assertEqual(stats['point']['observed_days'], 0)
        self.assertTrue(stats['point']['reported_confusion'])

    def test_mix_across_many_dates(self):
        items = [sample('old-' + f, f) for f in ['relative', 'with', 'account', 'remote', 'reference', 'standard', 'subject', 'even']]
        for i, f in enumerate(['nested', 'point', 'faint', 'unpretentious']):
            items.append(sample('new-' + f, f, '2026-09-29'))
        for offset in range(20):
            day = date(2026, 9, 29) + timedelta(days=offset)
            stats = review.make_stats(items, [], [], day)
            selected = review.choose(items, stats, {}, day)
            self.assertEqual(len(selected), 8)
            self.assertEqual(len({q['family'] for q in selected}), 8)
            self.assertLessEqual(sum(q.get('introduced') == day.isoformat() for q in selected), 2)
            n_structure = sum(q['family'] in review.STRUCTURE for q in selected)
            self.assertGreaterEqual(n_structure, 1)
            self.assertLessEqual(n_structure, 2)
            self.assertEqual(selected, review.choose(items, stats, {}, day))

    def test_actual_bank_and_two_builds_are_stable(self):
        items = review.bank(ROOT)
        self.assertGreaterEqual(len({q['family'] for q in items}), 8)
        self.assertEqual(len({q['id'] for q in items}), len(items))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data/questions').mkdir(parents=True)
            (root / 'web').mkdir()
            review.save(root / 'data/base-bank.json', items)
            (root / 'web/review.js').write_text('// engine fixture')
            (root / 'index.html').write_text('<h1>unchanged home</h1>')
            first = review.build(root, date(2026, 9, 30))
            second = review.build(root, date(2026, 9, 30))
            self.assertEqual(first['questions'], second['questions'])
            self.assertEqual((root / 'index.html').read_text(), '<h1>unchanged home</h1>')
            self.assertTrue((root / '_site/today.html').exists())
            self.assertTrue((root / 'data/days/2026-09-30.json').exists())
            for q in second['questions']:
                for retry in second['retry'][q['family']]:
                    self.assertNotEqual(retry['id'], q['id'])
                    review.validate(retry)


if __name__ == '__main__':
    unittest.main()
