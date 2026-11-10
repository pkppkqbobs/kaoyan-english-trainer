"""New confusion needs later evidence; old real results are never rewritten."""
import copy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import daily_review as review


class ObservationDateTests(unittest.TestCase):
    item = {'id': 'fixture-revisited', 'family': 'revisited',
            'introduced': '2026-10-01', 'budget': 35}

    def rows(self, *days):
        return [{'family': 'revisited', 'date': '2026-10-' + day,
                 'ok': True, 'ms': 1000} for day in days]

    def stats(self, rows, notes, day):
        return review.make_stats([self.item], rows, notes, date(2026, 10, day))['revisited']

    def test_old_correct_days_cannot_clear_a_later_clarification(self):
        notes = [{'family': 'revisited', 'date': '2026-10-01',
                  'clarified_on': '2026-10-05', 'kind': 'user_reported_confusion'}]
        rows = self.rows('02', '03')
        before = copy.deepcopy((rows, notes))
        stats = self.stats(rows, notes, 5)
        self.assertTrue(stats['reported_confusion'])
        self.assertEqual((stats['streak'], stats['errors'], stats['observed_days']), (0, 0, 2))
        queue = review.pending_observation_reviews([self.item], {'revisited': stats}, notes,
                                                  rows, {'2026-10-03': ['fixture-revisited']}, date(2026, 10, 5))
        self.assertEqual(queue['revisited']['latest'], '2026-10-05')
        self.assertEqual((rows, notes), before)

    def test_two_later_clear_days_restore_only_the_post_clarification_streak(self):
        note = {'family': 'revisited', 'date': '2026-10-01',
                'clarified_on': '2026-10-05', 'kind': 'user_reported_confusion'}
        one = self.stats(self.rows('02', '03', '06'), [note], 6)
        self.assertTrue(one['reported_confusion'])
        two = self.stats(self.rows('02', '03', '06', '07'), [note], 7)
        self.assertFalse(two['reported_confusion'])
        self.assertEqual((two['streak'], two['errors'], two['observed_days']), (2, 0, 4))
        self.assertEqual(two['due'], '2026-10-11')

    def test_a_new_difficulty_cannot_resurrect_four_older_mastery_days(self):
        note = {'family': 'revisited', 'date': '2026-10-05', 'kind': 'user_reported_confusion'}
        stats = self.stats(self.rows('01', '02', '03', '04', '06', '07'), [note], 7)
        self.assertFalse(stats['reported_confusion'])
        self.assertEqual((stats['streak'], stats['errors'], stats['observed_days']), (2, 0, 6))
        self.assertEqual(stats['due'], '2026-10-11')

    def test_late_import_preserves_verified_reviews_after_the_actual_learning_day(self):
        note = {'family': 'revisited', 'date': '2026-10-01',
                'received_on': '2026-10-10', 'kind': 'user_reported_confusion'}
        stats = self.stats(self.rows('02', '03'), [note], 10)
        self.assertFalse(stats['reported_confusion'])
        self.assertEqual((stats['streak'], stats['observed_days']), (2, 2))

    def test_future_receipt_and_future_clarification_do_not_leak_into_earlier_state(self):
        rows = self.rows('02', '03')
        delayed = {'family': 'revisited', 'date': '2026-10-03',
                   'received_on': '2026-10-10', 'kind': 'user_reported_confusion'}
        self.assertFalse(self.stats(rows, [delayed], 5)['reported_confusion'])
        self.assertTrue(self.stats(rows, [delayed], 10)['reported_confusion'])
        later = {'family': 'revisited', 'date': '2026-10-01',
                 'clarified_on': '2026-10-10', 'kind': 'user_reported_confusion'}
        self.assertFalse(self.stats(rows, [later], 5)['reported_confusion'])
        self.assertTrue(self.stats(rows, [later], 10)['reported_confusion'])

    def test_unverified_and_same_day_answers_do_not_clear_a_clarification(self):
        note = {'family': 'revisited', 'date': '2026-10-01',
                'clarified_on': '2026-10-05', 'kind': 'user_reported_confusion'}
        rows = self.rows('05', '06')
        rows += [{**self.rows('07')[0], 'date_unverified': True}]
        stats = self.stats(rows, [note], 7)
        self.assertTrue(stats['reported_confusion'])
        self.assertEqual((stats['streak'], stats['errors'], stats['observed_days']), (0, 0, 2))
        self.assertFalse(self.stats(rows + self.rows('08'), [note], 8)['reported_confusion'])

    def test_no_note_keeps_the_existing_verified_streak(self):
        stats = self.stats(self.rows('01', '02', '03', '04', '06', '07'), [], 7)
        self.assertEqual((stats['streak'], stats['errors'], stats['observed_days']), (6, 0, 6))


if __name__ == '__main__':
    unittest.main()
