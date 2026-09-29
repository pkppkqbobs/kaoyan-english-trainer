import copy
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


if __name__ == '__main__':
    unittest.main()
