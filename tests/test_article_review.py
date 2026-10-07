import json
from datetime import date, timedelta
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_review as review
import article_review
from run_daily import run


def q(qid, family, introduced=None):
    return {'id': qid, 'family': family, 'introduced': introduced, 'target': family,
            'skill': family, 'q': 'A complete transfer question about ' + qid + '.',
            'o': ['one', 'two', 'three', 'four'], 'a': 1, 'budget': 35,
            'exp': {key: 'Explanation for ' + key for key in review.EXP_KEYS}}


def fixture(root, current=4, history=10):
    (root / 'data/article-sessions').mkdir(parents=True)
    (root / 'data/questions').mkdir(parents=True)
    (root / 'web').mkdir()
    focus = [f'current-{i}' for i in range(current)]
    old = [f'history-{i}' for i in range(history)]
    items = [q(f'{f}-{v}', f, '2026-10-03' if f in focus else None)
             for f in focus + old for v in ('one', 'two')]
    review.save(root / 'data/base-bank.json', items)
    review.save(root / 'data/result-evidence.json', {'rows': [], 'issues': []})
    review.save(root / 'data/learning-notes.json', [
        {'family': f, 'date': '2026-10-03', 'kind': 'translation_difficulty'} for f in focus])
    review.save(root / 'data/daily-history.json', {})
    review.save(root / 'data/daily.json', {'date': '2026-10-03', 'questions': []})
    (root / 'web/review.js').write_text('// fixture')
    (root / 'today.html').write_text('locked daily page')
    (root / 'index.html').write_text('home fixture')
    return focus, old


def session(root, sid, focus, created='2026-10-03T10:00:00+08:00', day='2026-10-03', filename=None, revision=1):
    obj = {'id': sid, 'date': day, 'source': sid, 'created_at': created,
           'focus_families': focus, 'max_current': 4, 'revision': revision}
    path = root / 'data/article-sessions' / (filename or sid + '.json')
    review.save(path, obj)
    return path


class ArticleReviewTests(unittest.TestCase):
    def test_no_session_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(article_review.build(Path(directory)))

    def test_latest_uses_timezone_aware_created_at_not_filename_or_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root)
            session(root, 'z-earlier', focus, '2026-10-03T15:00:00+08:00', filename='z.json')
            session(root, 'a-later', focus, '2026-10-03T07:05:00Z', filename='a.json')
            self.assertEqual(article_review.latest_session(root)['id'], 'a-later')
            payload = article_review.build(root)
            self.assertEqual(payload['storageId'], 'a-later')
            self.assertTrue((root / 'data/article-reviews/z-earlier.json').exists())
            self.assertTrue((root / 'article-review-z-earlier.html').exists())

    def test_legacy_session_without_timestamp_keeps_storage_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root)
            path = session(root, 'legacy-session', focus)
            obj = review.load(path); del obj['created_at']; review.save(path, obj)
            self.assertEqual(article_review.build(root)['storageId'], 'legacy-session')

    def test_invalid_timestamp_and_duplicate_id_fail_before_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root)
            session(root, 'valid-session', focus)
            article_review.build(root)
            page = (root / 'article-review.html').read_bytes()
            path = session(root, 'new-session', focus, '2026-10-03T15:00:00')
            with self.assertRaises(ValueError): article_review.build(root)
            self.assertEqual((root / 'article-review.html').read_bytes(), page)
            path.unlink()
            session(root, 'valid-session', focus, filename='duplicate.json')
            with self.assertRaises(ValueError): article_review.build(root)
            self.assertEqual((root / 'article-review.html').read_bytes(), page)

    def test_two_plus_six_and_four_plus_four_without_duplicate_families(self):
        for count in (2, 4):
            with self.subTest(current=count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); focus, _ = fixture(root, count)
                session(root, 'mixed-session', focus + focus)
                before = (root / 'today.html').read_bytes()
                daily = (root / 'data/daily.json').read_bytes()
                payload = article_review.build(root)
                self.assertEqual(set(payload['article_session']['current_families']), set(focus))
                self.assertEqual(len(payload['article_session']['historical_families']), 8-count)
                self.assertEqual(len({q['family'] for q in payload['questions']}), 8)
                self.assertEqual((root / 'today.html').read_bytes(), before)
                self.assertEqual((root / 'data/daily.json').read_bytes(), daily)

    def test_focus_prioritizes_wrong_then_uncertain_and_rotates_translations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root, 6)
            kinds = ['translation_difficulty', 'translation_difficulty', 'translation_difficulty',
                     'correct_but_uncertain', 'user_reported_wrong', 'user_reported_wrong']
            notes = [{'family': f, 'date': '2026-10-03', 'kind': k} for f, k in zip(focus, kinds)]
            notes[0]['review_importance'] = 'low'
            review.save(root / 'data/learning-notes.json', notes)
            session(root, 'prioritized-session', focus)
            first = article_review.build(root)
            selected = set(first['article_session']['current_families'])
            self.assertTrue(set(focus[3:]).issubset(selected))
            self.assertNotIn(focus[0], selected)
            self.assertTrue(set(first['article_session']['historical_families']).isdisjoint(focus))
            session(root, 'prioritized-session', list(reversed(focus)), revision=2)
            second = article_review.build(root)
            self.assertTrue(set(focus[1:3]).issubset(selected | set(second['article_session']['current_families'])))
            self.assertNotEqual(first['storageId'], second['storageId'])

    def test_text3_text4_and_revision_preserve_archives_and_daily(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root)
            session(root, 'text3-session', focus)
            first = article_review.build(root)
            archive = root / 'data/article-reviews/text3-session.json'
            first_bytes = archive.read_bytes()
            session(root, 'text4-session', focus[:2], '2026-10-03T11:00:00+08:00')
            second = article_review.build(root)
            self.assertEqual(second['storageId'], 'text4-session')
            self.assertEqual(archive.read_bytes(), first_bytes)
            self.assertEqual(review.load(root / 'data/article-reviews/text3-session.json'), first)
            self.assertEqual((root / 'today.html').read_text(), 'locked daily page')
            self.assertIn('article-review-text3-session.html', (root / 'article-reviews.html').read_text())
            self.assertIn('text3-session', (root / 'article-review-text3-session.html').read_text())
            second_bytes = (root / 'data/article-reviews/text4-session.json').read_bytes()
            session(root, 'text4-session', focus, '2026-10-03T11:00:00+08:00', revision=2)
            third = article_review.build(root)
            self.assertEqual(third['storageId'], 'text4-session-r2')
            self.assertEqual((root / 'data/article-reviews/text4-session.json').read_bytes(), second_bytes)

    def test_rebuild_with_new_results_does_not_change_published_round_or_commit_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root)
            session(root, 'locked-session', focus)
            payload = article_review.build(root)
            before = {p.name: p.read_bytes() for p in root.glob('article-review*.html')}
            archive = (root / 'data/article-reviews/locked-session.json').read_bytes()
            review.save(root / 'data/result-evidence.json', {'rows': [
                {'family': focus[0], 'date': '2026-10-03', 'ok': False, 'ms': 1000}], 'issues': [7]})
            self.assertEqual(article_review.build(root), payload)
            self.assertEqual((root / 'data/article-reviews/locked-session.json').read_bytes(), archive)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.glob('article-review*.html')})

    def test_historical_selection_uses_filtered_pool_and_shared_overdue_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, old = fixture(root, 6)
            review.save(root / 'data/result-evidence.json', {'rows': [
                {'family': old[0], 'date': '2026-09-28', 'ok': False, 'ms': 60000}], 'issues': [1]})
            session(root, 'history-session', focus)
            with mock.patch.object(review, 'choose', wraps=review.choose) as choose:
                payload = article_review.build(root)
            self.assertIn(old[0], payload['article_session']['historical_families'])
            pool = choose.call_args.args[0]
            self.assertTrue({q['family'] for q in pool}.isdisjoint(focus))
            self.assertEqual(choose.call_args.kwargs['count'], 4)
            self.assertTrue(choose.call_args.kwargs['include_today'])

    def test_history_variants_rotate_across_days_and_stable_target_is_not_forced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, old = fixture(root)
            rows = [{'family': old[0], 'date': '2026-09-28', 'ok': False, 'ms': 60000}]
            rows += [{'family': old[1], 'date': f'2026-10-0{i}', 'ok': True, 'ms': 1000} for i in (1, 2)]
            review.save(root / 'data/result-evidence.json', {'rows': rows, 'issues': [1]})
            selected = []
            for offset in range(2):
                day = date(2026, 10, 3) + timedelta(days=offset)
                session(root, f'history-day-{offset}', focus, day.isoformat()+'T10:00:00+08:00', day.isoformat())
                payload = article_review.build(root)
                self.assertNotIn(old[1], payload['article_session']['historical_families'])
                selected.append(next(q['id'] for q in payload['questions'] if q['family'] == old[0]))
            self.assertNotEqual(*selected)

    def test_observations_are_not_scored_attempts_and_wrong_retains_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root)
            notes = [{'family': focus[i], 'date': '2026-10-03', 'kind': kind}
                     for i, kind in enumerate(['user_reported_wrong', 'correct_but_uncertain', 'translation_difficulty'])]
            stats = review.make_stats(review.bank(root), [], notes, date(2026, 10, 3))
            for f in focus[:3]:
                self.assertEqual(stats[f]['errors'], 0)
                self.assertEqual(stats[f]['observed_days'], 0)
                self.assertEqual(stats[f]['streak'], 0)
                self.assertIsNone(stats[f]['last'])
            self.assertGreater(stats[focus[0]]['observation_priority'], stats[focus[1]]['observation_priority'])
            self.assertGreater(stats[focus[1]]['observation_priority'], stats[focus[2]]['observation_priority'])
            self.assertTrue(stats[focus[0]]['reported_confusion'])

    def test_complete_article_chain_keeps_daily_locked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); focus, _ = fixture(root)
            review.save(root / 'data/daily.json', {'date': '2026-10-02', 'questions': []})
            run(root, date(2026, 10, 3), False, 'pkppkqbobs/kaoyan-english-trainer')
            before = (root / 'today.html').read_bytes()
            questions = review.load(root / 'data/daily.json')['questions']
            self.assertEqual(len(questions), 8)
            session(root, 'new-session', focus)
            article_review.build(root)
            run(root, date(2026, 10, 3), False, 'pkppkqbobs/kaoyan-english-trainer')
            article_review.build(root)
            self.assertEqual((root / 'today.html').read_bytes(), before)
            self.assertEqual(review.load(root / 'data/daily.json')['questions'], questions)

    def test_real_frontend_article_issue_round_trip_dedup_and_same_day_streak(self):
        with tempfile.TemporaryDirectory() as directory:
            report_file = Path(directory) / 'report.txt'
            env = {**os.environ, 'ARTICLE_TEST_REPORT_PATH': str(report_file)}
            subprocess.run(['node', 'tests/ui.mjs'], cwd=ROOT, env=env, check=True, capture_output=True)
            body = report_file.read_text()
            report = json.loads(body.split('<!-- review-json:v3\n', 1)[1].split('\n-->', 1)[0])
            issue = {'number': 90, 'created_at': report['date'] + 'T12:00:00Z',
                     'user': {'login': 'pkppkqbobs'}, 'title': '[TRAINING_RESULT] 文章复盘 ' + report['date'], 'body': body}
            rows, ids = review.evidence([issue, {**issue, 'number': 91}], 'pkppkqbobs')
            self.assertEqual(ids, [90])
            self.assertEqual(len(rows), 8)
            self.assertFalse(rows[0]['ok'])
            self.assertTrue(rows[1]['ok'])
            self.assertTrue(rows[1]['uncertain'])
            self.assertTrue(all('qid' in r for r in rows))
            stable = next(r for r in rows[2:] if r['ok'] and not r['uncertain'])
            daily_answer = {**stable, 'origin': 92}
            as_of = date.fromisoformat(rows[0]['date'])
            stats = review.make_stats(review.bank(ROOT), rows+[daily_answer], [], as_of)
            self.assertEqual(stats[stable['family']]['streak'], 1)
            self.assertEqual(stats[stable['family']]['observed_days'], 1)
            self.assertEqual(stats[rows[0]['family']]['errors'], 1)
            self.assertEqual(stats[rows[0]['family']]['streak'], 0)


if __name__ == '__main__':
    unittest.main()
