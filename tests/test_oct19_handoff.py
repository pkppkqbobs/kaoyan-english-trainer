"""Regression checks for the October 18 conversation handoff and real upload."""
from datetime import date
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_review as review


class HandoffTests(unittest.TestCase):
    def test_text4_observations_have_checked_answers_without_invented_choices(self):
        source = review.load(ROOT / 'data/source-checks/2013-english1.json')
        self.assertEqual([source['answers'][str(n)] for n in range(36, 41)], list('CCDAB'))
        self.assertIn('Text 4', source['performance_coverage'])
        self.assertTrue(any('yz.chsi.com.cn/' in s['url'] for s in source['sources']))
        notes = [n for n in review.load(ROOT / 'data/learning-notes.json')
                 if n.get('session_id') == '2026-10-18-2013-text4']
        self.assertEqual({n['source_question']: n['reported_pick'] for n in notes},
                         {36: 'D', 37: 'D', 38: 'C', 40: 'A'})
        for note in notes:
            self.assertEqual(note['expected'], source['answers'][str(note['source_question'])])
            self.assertNotEqual(note['reported_pick'], note['expected'])
            self.assertEqual(note['kind'], 'user_reported_wrong')

    def test_real_article_issue_is_original_round_and_counts_only_first_answers(self):
        rows = review.load(ROOT / 'data/result-evidence.json')['rows']
        submitted = [r for r in rows if r['origin'] == 21]
        original = review.load(ROOT / 'data/article-reviews/2026-10-18-2013-text4.json')
        self.assertEqual(len(submitted), 8)
        self.assertEqual({r['qid'] for r in submitted}, {q['id'] for q in original['questions']})
        self.assertEqual(sum(r['ok'] for r in submitted), 7)
        self.assertEqual([r['family'] for r in submitted if not r['ok']],
                         ['text4-historical-inference'])
        unsure = next(r for r in submitted if r['family'] == 'example-claim-scope')
        self.assertTrue(unsure['ok'])
        self.assertTrue(unsure['uncertain'])

    def test_paper_mistakes_keep_priority_without_becoming_web_errors(self):
        items = review.bank(ROOT)
        # Freeze this counterexample before the first actual Text 4 web report.
        rows = [r for r in review.load(ROOT / 'data/result-evidence.json')['rows'] if r['origin'] < 21]
        notes = [n for n in review.load(ROOT / 'data/learning-notes.json') if n['date'] <= '2026-10-18']
        stats = review.make_stats(items, rows, notes, date(2026, 10, 19))
        for note in notes:
            if note.get('session_id') == '2026-10-18-2013-text4':
                with self.subTest(family=note['family']):
                    state = stats[note['family']]
                    self.assertEqual(state['observed_days'], 0)
                    self.assertEqual(state['errors'], 0)
                    self.assertEqual(state['streak'], 0)
                    self.assertTrue(state['reported_confusion'])
                    self.assertEqual(state['observation_priority'], 3)


if __name__ == '__main__':
    unittest.main()
