"""Real history and counterexamples for the one-slot overdue review reserve."""
import contextlib
import copy
from datetime import date, timedelta
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_review as review
import article_review
import partb_review
from run_daily import run


def question(family, introduced='2026-10-01', published_on='2026-10-01'):
    return {'id': 'fixture-' + family, 'family': family, 'introduced': introduced,
            'published_on': published_on, 'target': family, 'budget': 45,
            'q': 'A complete independent fixture question for ' + family + '.',
            'o': ['one', 'two', 'three', 'four'], 'a': 0,
            'exp': {key: 'Fixture explanation' for key in review.EXP_KEYS}}


def fixture():
    # Numerous ongoing high-priority errors must keep their ordinary urgent slots,
    # but must not consume the independent reserve as well.
    items = [question('urgent-' + str(i)) for i in range(10)]
    stats = {q['family']: {'due': '2026-10-02', 'last': '2026-10-01',
             'streak': 0, 'errors': 4, 'slow_or_uncertain': True,
             'reported_confusion': False, 'observation_priority': 0} for q in items}
    history = {'2026-10-19': [q['id'] for q in items]}
    for family, introduced in [('with', '2026-10-01'), ('recent-a', '2026-10-19'), ('recent-b', '2026-10-19')]:
        items.append(question(family, introduced, introduced))
        stats[family] = {**stats['urgent-0'], 'due': '2026-10-20', 'last': None,
                         'errors': 0, 'slow_or_uncertain': False}
    return items, stats, history


class ProgressAuditTests(unittest.TestCase):
    def test_real_old_error_and_slow_target_receive_review_without_fabricating_future_answers(self):
        items = review.bank(ROOT)
        rows = review.load(ROOT / 'data/result-evidence.json')['rows']
        notes = review.load(ROOT / 'data/learning-notes.json')
        before = copy.deepcopy(rows)
        history = review.load(ROOT / 'data/daily-history.json')
        start = date.fromisoformat(review.load(ROOT / 'data/review-state.json')['as_of']) + timedelta(days=1)
        shown = {family: [] for family in ('viewpoint-fact', 'summary-location')}
        initial = review.make_stats(items, rows, notes, start)
        for offset in range(21):
            day = start + timedelta(days=offset)
            stats = review.make_stats(items, rows, notes, day)
            selected = review.choose(items, stats, history, day,
                                    variant_shown=review.variant_history(ROOT, day, history))
            self.assertEqual(len(selected), 8)
            self.assertEqual(len({q['family'] for q in selected}), 8)
            self.assertLessEqual(sum(q['family'].startswith('paragraph-order-') for q in selected), 1)
            history[day.isoformat()] = [q['id'] for q in selected]
            for q in selected:
                if q['family'] in shown:
                    shown[q['family']].append(offset)
            for family in shown:
                for key in ('streak', 'errors', 'last', 'observed_days', 'slow_or_uncertain'):
                    self.assertEqual(stats[family][key], initial[family][key])
        self.assertEqual(rows, before)
        for family, offsets in shown.items():
            with self.subTest(family=family):
                self.assertTrue(offsets, 'known old weakness cannot be starved for three weeks')
                self.assertLess(offsets[0], 7, 'the existing old weakness needs a near-term opportunity')

    def test_one_reserve_uses_waiting_time_while_four_urgent_slots_keep_their_priority(self):
        items, stats, history = fixture()
        old = question('neglected')
        items.append(old)
        stats['neglected'] = {**stats['urgent-0'], 'errors': 1, 'slow_or_uncertain': False}
        history['2026-10-03'] = [old['id']]
        selected = review.choose(items, stats, history, date(2026, 10, 20))
        families = {q['family'] for q in selected}
        self.assertIn('neglected', families)
        self.assertGreaterEqual(sum(f.startswith('urgent-') for f in families), 4)

    def test_recent_article_opportunity_prevents_a_false_long_wait_in_the_reserve(self):
        items, stats, history = fixture()
        for family, stamp in [('article-recent', '2026-10-01'), ('really-neglected', '2026-10-02')]:
            q = question(family)
            items.append(q)
            stats[family] = {**stats['urgent-0'], 'errors': 1, 'slow_or_uncertain': False}
            history.setdefault(stamp, []).append(q['id'])
        all_modules = copy.deepcopy(history)
        all_modules['2026-10-20'] = ['fixture-article-recent']
        selected = review.choose(items, stats, history, date(2026, 10, 20), count=5,
                                 include_today=True, variant_shown=all_modules)
        families = {q['family'] for q in selected}
        self.assertIn('really-neglected', families)
        self.assertNotIn('article-recent', families)

    def test_unanswered_confusion_can_age_but_a_newly_published_variant_cannot_claim_old_waiting_time(self):
        items, stats, history = fixture()
        cold = question('old-confusion')
        fresh = question('just-published', published_on='2026-10-20')
        items.extend([cold, fresh])
        # make_stats intentionally gives never-answered observations today's due
        # date. The reserve must still notice an old untested target.
        for family in [cold['family'], fresh['family']]:
            stats[family] = {**stats['urgent-0'], 'due': '2026-10-20', 'last': None,
                             'errors': 0, 'slow_or_uncertain': False,
                             'reported_confusion': True, 'observation_priority': 3}
        before = copy.deepcopy(stats)
        selected = review.choose(items, stats, history, date(2026, 10, 20), count=5)
        families = {q['family'] for q in selected}
        self.assertIn('old-confusion', families)
        self.assertNotIn('just-published', families)
        self.assertEqual(stats, before)

    def test_translation_only_observation_does_not_displace_a_confirmed_error_in_the_reserve(self):
        items, stats, history = fixture()
        for family in ['translation', 'confirmed-error']:
            q = question(family)
            items.append(q)
            stats[family] = {**stats['urgent-0'], 'errors': 1, 'slow_or_uncertain': False}
        stats['translation'].update(errors=0, reported_confusion=True, observation_priority=1)
        history['2026-10-01'] = ['fixture-translation']
        history['2026-10-02'] = ['fixture-confirmed-error']
        selected = review.choose(items, stats, history, date(2026, 10, 20), count=5)
        families = {q['family'] for q in selected}
        self.assertIn('confirmed-error', families)
        self.assertNotIn('translation', families)

    def test_not_yet_due_stable_family_cannot_use_the_neglected_weakness_reserve(self):
        items, stats, history = fixture()
        for family in ['not-due', 'due-neglected']:
            q = question(family)
            items.append(q)
            stats[family] = {**stats['urgent-0'], 'errors': 1, 'slow_or_uncertain': False}
        stats['not-due'].update(due='2026-10-30', streak=3)
        history['2026-10-01'] = ['fixture-not-due']
        history['2026-10-02'] = ['fixture-due-neglected']
        selected = review.choose(items, stats, history, date(2026, 10, 20))
        families = {q['family'] for q in selected}
        self.assertIn('due-neglected', families)
        self.assertNotIn('not-due', families)

    def test_latest_data_and_all_locked_rounds_remain_identical_after_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('data', 'web', 'archive'):
                shutil.copytree(ROOT / name, root / name)
            for page in ROOT.glob('*.html'):
                shutil.copy(page, root / page.name)
            # New article sessions may legitimately advance the latest alias.
            # The already-published daily, evidence, and archived rounds must
            # remain byte-identical while that first new alias is generated.
            paths = [*root.glob('*.html'), *(root / 'data').rglob('*.json')]
            latest_aliases = {
                root / 'article-review.html',
                root / 'article-reviews.html',
                root / 'data/article-review.json',
            }
            immutable_before = {p: p.read_bytes() for p in paths if p not in latest_aliases}
            with contextlib.redirect_stdout(io.StringIO()):
                article_review.build(root)
                partb_review.build(root)
            self.assertTrue(all(p.read_bytes() == content for p, content in immutable_before.items()))

            # After first-time generation, two further builds must be idempotent
            # including the newly published article and history index.
            paths = [*root.glob('*.html'), *(root / 'data').rglob('*.json')]
            before = {p: p.read_bytes() for p in paths}
            day = date.fromisoformat(review.load(root / 'data/daily.json')['date'])
            for _ in range(2):
                with contextlib.redirect_stdout(io.StringIO()):
                    run(root, day, False, 'pkppkqbobs/kaoyan-english-trainer')
                    article_review.build(root)
                    partb_review.build(root)
                self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))


if __name__ == '__main__':
    unittest.main()
