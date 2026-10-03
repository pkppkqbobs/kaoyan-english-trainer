import copy
import json
from datetime import date
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_daily import apply_exclusions


class QualityTests(unittest.TestCase):
    def test_exclusion_is_scoped_and_preserves_original(self):
        rows = [{'origin': 3, 'family': 'subject', 'ok': False},
                {'origin': 2, 'family': 'subject', 'ok': True},
                {'origin': 3, 'family': 'point', 'ok': True}]
        original = copy.deepcopy(rows)
        accepted, excluded = apply_exclusions(rows, [{'origin': 3, 'family': 'subject', 'reason': 'ambiguous legacy item'}])
        self.assertEqual(rows, original)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(len(excluded), 1)
        self.assertFalse(excluded[0]['ok'])
        self.assertEqual(excluded[0]['exclusion_reason'], 'ambiguous legacy item')

    def test_family_only_exclusion_cannot_erase_valid_history(self):
        with self.assertRaises(ValueError):
            apply_exclusions([], [{'family': 'cling-climb', 'reason': 'missing scope'}])

    def test_locked_ambiguous_question_is_excluded_without_hiding_other_evidence(self):
        from daily_review import bank, make_stats, parse_issue
        obj = {'roundId': 'today-main', 'date': '2026-10-03', 'answers': [
            {'qid': 'cling-rail-b', 'family': 'cling-climb', 'pick': 3, 'expected': 1,
             'ok': False, 'ms': 12000, 'uncertain': True},
            {'qid': 'cling-policy-a', 'family': 'cling-climb', 'pick': 1, 'expected': 1,
             'ok': True, 'ms': 10000, 'uncertain': False}]}
        issue = {'number': 7, 'created_at': '2026-10-03T03:00:00Z',
                 'body': '<!-- review-json:v3\n' + json.dumps(obj) + '\n-->'}
        _, rows = parse_issue(issue)
        rows.append({**rows[0], 'date': '2026-10-04'})
        original = copy.deepcopy(rows)
        rules = json.loads((Path(__file__).resolve().parents[1] / 'data/quality-exclusions.json').read_text())
        accepted, excluded = apply_exclusions(rows, rules)
        self.assertEqual(rows, original)
        self.assertEqual([r['qid'] for r in accepted], ['cling-policy-a', 'cling-rail-b'])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]['origin'], 7)
        self.assertFalse(excluded[0]['ok'])
        self.assertTrue(excluded[0]['uncertain'])
        items = bank(Path(__file__).resolve().parents[1])
        today_rows = [r for r in accepted if r['date'] == '2026-10-03']
        stats = make_stats(items, today_rows, [], date(2026, 10, 3))['cling-climb']
        self.assertEqual(stats['errors'], 0)
        self.assertEqual(stats['streak'], 1)
        self.assertFalse(stats['slow_or_uncertain'])


if __name__ == '__main__':
    unittest.main()
