"""Follow-up and repeated-context regressions from the Oct 12--14 results."""
import copy
from datetime import date
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_review as review
from test_progress_audit import fixture, question


class RecentProgressTests(unittest.TestCase):
    def test_recent_unstable_scored_error_gets_one_followup_before_old_unanswered_notes(self):
        items, stats, history = fixture()
        for family in ('recent-error', 'old-note'):
            items.append(question(family))
            stats[family] = {**stats['urgent-0'], 'errors': 1, 'slow_or_uncertain': False}
        stats['recent-error'].update(last='2026-10-18', due='2026-10-19')
        stats['old-note'].update(last=None, errors=0, reported_confusion=True, observation_priority=3)
        history['2026-10-18'] = ['fixture-recent-error']
        history['2026-10-03'] = ['fixture-old-note']
        before = copy.deepcopy(stats)
        selected = review.choose(items, stats, history, date(2026, 10, 20))
        families = {q['family'] for q in selected}
        self.assertIn('recent-error', families)
        self.assertGreaterEqual(sum(f.startswith('urgent-') for f in families), 4)
        self.assertEqual(stats, before)

    def test_an_already_offered_recent_error_does_not_take_the_reserve_again(self):
        items, stats, history = fixture()
        for family in ('recent-error', 'neglected'):
            items.append(question(family))
            stats[family] = {**stats['urgent-0'], 'errors': 1, 'slow_or_uncertain': False}
        stats['recent-error'].update(last='2026-10-18', due='2026-10-19')
        history['2026-10-19'].append('fixture-recent-error')
        history['2026-10-03'] = ['fixture-neglected']
        families = {q['family'] for q in review.choose(items, stats, history, date(2026, 10, 20), count=5)}
        self.assertIn('neglected', families)
        self.assertNotIn('recent-error', families)

    def test_historical_error_after_two_clear_days_is_not_a_recent_unstable_error(self):
        items, stats, history = fixture()
        for family in ('stable', 'neglected'):
            items.append(question(family))
            stats[family] = {**stats['urgent-0'], 'errors': 1, 'slow_or_uncertain': False}
        stats['stable'].update(last='2026-10-18', due='2026-10-20', streak=2,
                               slow_or_uncertain=True)
        history['2026-10-18'] = ['fixture-stable']
        history['2026-10-03'] = ['fixture-neglected']
        families = {q['family'] for q in review.choose(items, stats, history, date(2026, 10, 20), count=5)}
        self.assertIn('neglected', families)
        self.assertNotIn('stable', families)

    def test_observations_without_scored_errors_do_not_claim_prompt_error_followup(self):
        for priority in (1, 2, 3):
            with self.subTest(priority=priority):
                items, stats, history = fixture()
                for family in ('observation', 'neglected'):
                    items.append(question(family))
                    stats[family] = {**stats['urgent-0'], 'errors': 1, 'slow_or_uncertain': False}
                stats['observation'].update(last='2026-10-18', due='2026-10-19', errors=0,
                                             reported_confusion=True, observation_priority=priority)
                history['2026-10-18'] = ['fixture-observation']
                history['2026-10-03'] = ['fixture-neglected']
                families = {q['family'] for q in review.choose(items, stats, history, date(2026, 10, 20), count=5)}
                self.assertIn('neglected', families)
                self.assertNotIn('observation', families)

    def test_real_summary_error_receives_a_followup_without_new_answers(self):
        items = [q for q in review.bank(ROOT) if review.available(q, date(2026, 10, 14))]
        rows = [r for r in review.load(ROOT / 'data/result-evidence.json')['rows'] if r['origin'] <= 16]
        notes = [n for n in review.load(ROOT / 'data/learning-notes.json') if n['date'] <= '2026-10-14']
        history = {d: ids for d, ids in review.load(ROOT / 'data/daily-history.json').items() if d <= '2026-10-15'}
        day = date(2026, 10, 16)
        stats = review.make_stats(items, rows, notes, day)
        self.assertTrue(any(r['origin'] == 16 and r['family'] == 'summary-location' and not r['ok'] for r in rows))
        before = copy.deepcopy(stats)
        selected = review.choose(items, stats, history, day,
                                 variant_shown=review.variant_history(ROOT, day, history))
        self.assertIn('summary-location', {q['family'] for q in selected})
        self.assertEqual(stats, before)

    def test_real_daily_ties_rotate_qids_without_changing_the_selected_families(self):
        items = [q for q in review.bank(ROOT) if review.available(q, date(2026, 10, 14))]
        rows = [r for r in review.load(ROOT / 'data/result-evidence.json')['rows'] if r['origin'] <= 16]
        notes = [n for n in review.load(ROOT / 'data/learning-notes.json') if n['date'] <= '2026-10-14']
        history = {d: ids for d, ids in review.load(ROOT / 'data/daily-history.json').items() if d < '2026-10-15'}
        day = date(2026, 10, 15)
        selected = review.choose(items, review.make_stats(items, rows, notes, day), history, day,
                                 variant_shown=review.variant_history(ROOT, day, history))
        published = review.load(ROOT / 'data/days/2026-10-15.json')['questions']
        self.assertEqual({q['family'] for q in selected}, {q['family'] for q in published})
        yesterday = {q['family']: q for q in review.load(ROOT / 'data/days/2026-10-14.json')['questions']}
        for family in ('process-stage-role', 'example-claim-scope'):
            q = next(q for q in selected if q['family'] == family)
            self.assertNotEqual(q['id'], yesterday[family]['id'])
            if family == 'example-claim-scope':
                self.assertNotEqual(q['context_id'], yesterday[family]['context_id'])

    def test_process_transfer_covers_new_roles_instead_of_counting_the_old_template_twice(self):
        items = review.bank(ROOT)
        byid = {q['id']: q for q in items}
        old = [byid[qid] for qid in ('process-stage-shelter-approval-a', 'process-stage-bridge-warning-b')]
        self.assertEqual(old[0]['context_id'], old[1]['context_id'])
        additions = review.load(ROOT / 'data/questions/2026-10-15-review-transfer.json')
        self.assertEqual(len(additions), 4)
        for family, contexts in [('process-stage-role', 3), ('example-claim-scope', 4)]:
            group = [q for q in items if q['family'] == family]
            self.assertEqual(len(group), 4)
            self.assertEqual(len({q['context_id'] for q in group}), contexts)
        for q in additions:
            family_old = [v for v in items if v['family'] == q['family'] and v['id'] not in {a['id'] for a in additions}]
            self.assertEqual(q['introduced'], min(v['introduced'] for v in family_old))
            self.assertEqual(q['published_on'], '2026-10-15')
            self.assertFalse(review.available(q, date(2026, 10, 14)))
            self.assertLessEqual(q['budget'], max(v['budget'] for v in family_old))
        retries = review.retry_variants(items, old[0], date(2026, 10, 15))
        self.assertEqual({q['id'] for q in retries},
                         {'process-stage-hospital-routine-authority-c', 'process-stage-shipment-hold-decision-d'})

    def test_equal_global_dates_use_the_current_modules_older_context(self):
        variants = [question('first'), question('second')]
        history = {'2026-10-14': [q['id'] for q in variants]}
        primary = {'2026-10-14': ['fixture-first'], '2026-10-13': ['fixture-second']}
        for seed in range(12):
            selected = review.choose_variant(variants, history, random.Random(seed), primary_history=primary)
            self.assertEqual(selected['id'], 'fixture-second')

    def test_primary_spacing_never_overrides_a_globally_older_context(self):
        variants = [question('first'), question('second')]
        history = {'2026-10-13': ['fixture-first'], '2026-10-14': ['fixture-second']}
        primary = {'2026-10-13': ['fixture-first']}
        selected = review.choose_variant(variants, history, random.Random(2), primary_history=primary)
        self.assertEqual(selected['id'], 'fixture-first')

    def test_unseen_near_duplicate_does_not_hide_yesterdays_context_in_a_tie(self):
        variants = [question('used'), question('new-id'), question('different')]
        variants[0]['context_id'] = variants[1]['context_id'] = 'shared-template'
        variants[2]['context_id'] = 'independent-context'
        history = {'2026-10-14': ['fixture-used', 'fixture-different']}
        primary = {'2026-10-14': ['fixture-used'], '2026-10-12': ['fixture-different']}
        selected = review.choose_variant(variants, history, random.Random(2), primary_history=primary)
        self.assertEqual(selected['id'], 'fixture-different')


if __name__ == '__main__':
    unittest.main()
