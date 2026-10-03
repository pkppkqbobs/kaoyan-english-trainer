import copy
import json
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

    def test_cling_climb_variant_has_one_viable_answer(self):
        source = Path(__file__).resolve().parents[1] / 'data/questions/2026-09-30-passage-review.json'
        rows = json.loads(source.read_text(encoding='utf-8'))
        item = next(row for row in rows if row['id'] == 'cling-rail-b')
        self.assertIn("his father's arm", item['q'])
        self.assertIn('safety barrier', item['q'])
        self.assertEqual(len(item['o']), 4)
        self.assertEqual(len(set(item['o'])), 4)
        self.assertEqual(item['a'], 1)
        self.assertIn('climbed over在第二空虽可成立，但第一空仍不对', item['exp']['rest'])


if __name__ == '__main__':
    unittest.main()
