"""Daily opportunities for paper feedback must survive saturated scored-error queues."""
import copy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_review as review
from test_progress_audit import fixture, question


class ObservationSchedulingTests(unittest.TestCase):
    day = date(2026, 10, 20)

    def pending(self, items, notes, rows=(), history=None, day=None):
        day = day or self.day
        stats = review.make_stats(items, rows, notes, day)
        return review.pending_observation_reviews(items, stats, notes, rows, history or {}, day)

    def test_article_publication_is_not_completion_but_a_verified_later_answer_is(self):
        items = [question('paper')]
        notes = [{'family': 'paper', 'date': '2026-10-18', 'kind': 'user_reported_wrong'}]
        published_article = {'2026-10-19': ['fixture-paper']}
        self.assertIn('paper', self.pending(items, notes))
        # Only the daily history is passed to the first-daily-opportunity queue.
        # Article publication still informs normal variant spacing separately.
        stats = review.make_stats(items, [], notes, self.day)
        queue = review.pending_observation_reviews(items, stats, notes, [], {}, self.day)
        selected = review.choose(items, stats, {}, self.day, count=1,
                                 variant_shown=published_article, initial_reviews=queue)
        self.assertEqual(selected[0]['family'], 'paper')
        row = {'family': 'paper', 'date': '2026-10-19', 'ok': False, 'ms': 1000, 'module': 'article'}
        self.assertEqual(self.pending(items, notes, [row]), {})
        self.assertIn('paper', self.pending(items, notes, [{**row, 'date_unverified': True}]))
        self.assertIn('paper', self.pending(items, notes, [{**row, 'date': '2026-10-21'}]))

    def test_same_day_ordering_is_unknown_and_later_daily_offer_is_not_a_grade(self):
        items = [question('paper')]
        notes = [{'family': 'paper', 'date': '2026-10-18', 'received_on': '2026-10-19',
                  'kind': 'user_reported_confusion'}]
        history = {'2026-10-19': ['fixture-paper']}
        before = copy.deepcopy((items, notes, history))
        self.assertIn('paper', self.pending(items, notes, history=history))
        history['2026-10-20'] = ['fixture-paper']
        self.assertEqual(self.pending(items, notes, history=history), {})
        stats = review.make_stats(items, [], notes, self.day)['paper']
        self.assertEqual((stats['errors'], stats['streak'], stats['observed_days']), (0, 0, 0))
        self.assertTrue(stats['reported_confusion'])
        self.assertEqual((items, notes, {'2026-10-19': history['2026-10-19']}), before)

    def test_new_strong_feedback_on_an_old_family_is_recent_but_translation_is_not(self):
        items = [question('paper')]
        history = {'2026-10-10': ['fixture-paper']}
        old = {'family': 'paper', 'date': '2026-10-02', 'kind': 'user_reported_wrong'}
        translation = {'family': 'paper', 'date': '2026-10-19', 'kind': 'translation_difficulty'}
        self.assertEqual(self.pending(items, [old, translation], history=history), {})
        new = {**translation, 'kind': 'user_reported_confusion', 'received_on': '2026-10-20'}
        queue = self.pending(items, [old, new], history=history)
        self.assertEqual(queue['paper']['latest'], '2026-10-20')
        self.assertEqual(queue['paper']['since'], '2026-10-20')
        self.assertEqual(self.pending(items, [old, {**new, 'review_importance': 'low'}], history=history), {})
        self.assertEqual(self.pending(items, [{**new, 'received_on': '2026-10-21'}]), {})

    def test_late_publication_and_clarification_cannot_claim_an_earlier_wait(self):
        items = [question('paper', introduced='2026-10-01', published_on='2026-10-20')]
        note = {'family': 'paper', 'date': '2026-10-01', 'kind': 'user_reported_wrong'}
        self.assertEqual(self.pending(items, [note])['paper']['since'], '2026-10-20')
        self.assertEqual(self.pending(items, [note], day=date(2026, 10, 19)), {})
        items = [question('paper')]
        note['clarified_on'] = '2026-10-20'
        row = {'family': 'paper', 'date': '2026-10-19', 'ok': True, 'ms': 1000}
        self.assertEqual(self.pending(items, [note], [row])['paper']['latest'], '2026-10-20')

    def test_recent_and_oldest_observations_share_the_existing_budget_with_scored_errors(self):
        items, stats, history = fixture()
        notes = []
        for family, stamp, kind in [('oldest-paper', '2026-10-02', 'user_reported_confusion'),
                                    ('middle-paper', '2026-10-10', 'user_reported_wrong'),
                                    ('recent-paper', '2026-10-19', 'correct_but_uncertain')]:
            items.append(question(family))
            notes.append({'family': family, 'date': stamp, 'kind': kind})
        paper_stats = review.make_stats(items, [], notes, self.day)
        for note in notes:
            stats[note['family']] = paper_stats[note['family']]
        queue = review.pending_observation_reviews(items, stats, notes, [], history, self.day)
        before = copy.deepcopy((stats, notes, history))
        selected = review.choose(items, stats, history, self.day, initial_reviews=queue)
        families = {q['family'] for q in selected}
        self.assertEqual(len(selected), 8)
        self.assertEqual(len(families), 8)
        self.assertTrue({'oldest-paper', 'recent-paper'} <= families)
        self.assertGreaterEqual(sum(f.startswith('urgent-') for f in families), 2)
        self.assertIn('with', families)
        self.assertEqual((stats, notes, history), before)

    def test_heading_and_ordering_mechanisms_share_one_daily_slot(self):
        items, stats, history = fixture()
        families = ('heading-core-function', 'heading-global-allocation', 'paragraph-order-discourse')
        queue = {}
        for f in families:
            items.append(question(f))
            stats[f] = {**stats['urgent-0'], 'reported_confusion': True, 'observation_priority': 3}
            queue[f] = {'since': '2026-10-01', 'latest': '2026-10-19', 'priority': 3}
        for seed in range(12):
            selected = review.choose(items, stats, history, self.day, seed=str(seed), initial_reviews=queue)
            self.assertEqual(len(selected), 8)
            self.assertEqual(sum(q['family'] in families for q in selected), 1)

    def test_a_stream_of_new_feedback_cannot_starve_the_old_first_review_backlog(self):
        items, stats, history = fixture()
        notes = [{'family': 'waiting-' + str(i), 'date': '2026-10-02',
                  'kind': 'user_reported_confusion'} for i in range(6)]
        items.extend(question(n['family']) for n in notes)
        waiting = {n['family'] for n in notes}
        for offset in range(6):
            day = self.day + timedelta(days=offset)
            new = {'family': 'new-' + str(offset), 'date': day.isoformat(), 'kind': 'user_reported_wrong'}
            notes.append(new)
            items.append(question(new['family'], introduced=day.isoformat(), published_on=day.isoformat()))
            paper_stats = review.make_stats(items, [], notes, day)
            for n in notes:
                stats[n['family']] = paper_stats[n['family']]
            queue = review.pending_observation_reviews(items, stats, notes, [], history, day)
            selected = review.choose(items, stats, history, day, initial_reviews=queue)
            families = {q['family'] for q in selected}
            self.assertTrue(any(f.startswith('new-') for f in families))
            waiting.difference_update(families)
            history[day.isoformat()] = [q['id'] for q in selected]
        self.assertEqual(waiting, set())

    def test_real_backlog_gets_daily_opportunities_without_inventing_future_answers(self):
        # Freeze the Nov 7 evidence; later legitimate uploads must not change
        # this counterexample or require hypothetical future answers to pass.
        cutoff = '2026-11-07'
        items = [q for q in review.bank(ROOT) if review.available(q, cutoff)]
        rows = [r for r in review.load(ROOT / 'data/result-evidence.json')['rows']
                if r['origin'] <= 41 and r['date'] <= cutoff]
        notes = [n for n in review.load(ROOT / 'data/learning-notes.json')
                 if max(n['date'], n.get('received_on', n['date']), n.get('clarified_on', n['date'])) <= cutoff]
        history = {d: ids for d, ids in review.load(ROOT / 'data/daily-history.json').items() if d <= cutoff}
        start = date.fromisoformat(cutoff) + timedelta(days=1)
        initial = review.make_stats(items, rows, notes, start)
        queue = review.pending_observation_reviews(items, initial, notes, rows, history, start)
        targets = set(queue)
        self.assertTrue({'modal-stage', 'policy-enforcement-roles', 'relation-collocation',
                         'heading-core-function', 'heading-global-allocation'} <= targets)
        before = copy.deepcopy((rows, notes))
        for offset in range(14):
            day = start + timedelta(days=offset)
            stats = review.make_stats(items, rows, notes, day)
            queue = review.pending_observation_reviews(items, stats, notes, rows, history, day)
            selected = review.choose(items, stats, history, day,
                                     variant_shown=review.variant_history(ROOT, day, history),
                                     initial_reviews=queue)
            families = {q['family'] for q in selected}
            self.assertEqual(len(selected), 8)
            self.assertEqual(len(families), 8)
            self.assertLessEqual(sum(f.startswith(('paragraph-order-', 'heading-')) for f in families), 1)
            targets.difference_update(families)
            history[day.isoformat()] = [q['id'] for q in selected]
            for f in initial:
                for key in ('errors', 'streak', 'last', 'observed_days', 'slow_or_uncertain'):
                    self.assertEqual(stats[f][key], initial[f][key])
        self.assertEqual(targets, set(), 'strong observations must not remain behind old score totals forever')
        self.assertEqual((rows, notes), before)


if __name__ == '__main__':
    unittest.main()
