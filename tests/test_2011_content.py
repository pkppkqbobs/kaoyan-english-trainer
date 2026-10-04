"""Regression checks for audited source answers and non-scored learning observations."""
import copy
import json
from datetime import date
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import article_review
import daily_review as review
from run_daily import run


class Exam2011ContentTests(unittest.TestCase):
    def setUp(self):
        self.check = review.load(ROOT / 'data/source-checks/2011-english1.json')
        self.notes = review.load(ROOT / 'data/learning-notes.json')
        self.items = review.bank(ROOT)

    def test_verified_answers_and_fixed_part_b_positions(self):
        expected = 'CBDBABDCACDCBAACDADBBDACF'
        self.assertEqual(''.join(self.check['answers'][str(i)] for i in range(21, 46)), expected)
        order = self.check['part_b_order']
        self.assertEqual(order, ['G', 'B', 'D', 'E', 'A', 'C', 'F'])
        self.assertEqual([order[i] for i in [1, 2, 4, 5, 6]], list(expected[-5:]))
        self.assertGreaterEqual(len({s['url'] for s in self.check['sources']}), 2)

    def test_reported_wrong_requires_a_real_different_pick(self):
        known = {22: 'D', 26: 'D', 27: 'A', 30: 'D', 38: 'B', 40: 'A'}
        wrong = [n for n in self.notes if n.get('source_exam') == '2011-english1'
                 and n['kind'] == 'user_reported_wrong' and n.get('source_question')]
        self.assertEqual({n['source_question'] for n in wrong}, set(known))
        for n in wrong:
            self.assertEqual(n['reported_pick'], known[n['source_question']])
            self.assertNotEqual(n['reported_pick'], self.check['answers'][str(n['source_question'])])
        q38 = next(n for n in wrong if n['source_question'] == 38)
        self.assertEqual(q38['first_considered'], 'A')
        self.assertNotIn('first_pick', q38)  # considering an answer is not a submitted attempt

    def test_q29_wrong_diagnosis_is_withdrawn_without_erasing_real_transfer_errors(self):
        self.assertFalse(any(n['family'] == 'viewpoint-fact' for n in self.notes))
        self.assertFalse(any(n.get('source_question') == 29 and n['kind'] == 'user_reported_wrong'
                             for n in self.notes))
        correction = next(c for c in self.check['withdrawn_diagnoses'] if c['question'] == 29)
        self.assertIsNone(correction['reported_pick'])
        evidence = review.load(ROOT / 'data/result-evidence.json')['rows']
        stats = review.make_stats(self.items, evidence, self.notes, date(2026, 10, 4))['viewpoint-fact']
        actual_errors = sum(r.get('errors', int(not r['ok'])) for r in evidence
                            if r['family'] == 'viewpoint-fact' and r['date'] <= '2026-10-04')
        self.assertGreater(actual_errors, 0)
        self.assertEqual(stats['errors'], actual_errors)
        self.assertFalse(stats['reported_confusion'])
        for q in self.items:
            if q['family'] == 'viewpoint-fact':
                self.assertEqual(q['source_diagnosis']['status'], 'withdrawn')
                self.assertEqual(q['a'], 1)
                self.assertIn('完整文章', q['exp']['meaning'])

    def test_uncertain_and_boxed_text3_notes_never_become_errors(self):
        notes = [n for n in self.notes if n.get('session_id') == '2026-10-03-2011-text3']
        self.assertEqual({n['source_question'] for n in notes if n['kind'] == 'correct_but_uncertain'}, {33, 35})
        self.assertFalse(any(n['kind'] == 'user_reported_wrong' for n in notes))
        self.assertTrue(all(n['kind'] in ['correct_but_uncertain', 'translation_difficulty'] for n in notes))
        stats = review.make_stats(self.items, [], notes, date(2026, 10, 4))
        for n in notes:
            self.assertEqual(stats[n['family']]['errors'], 0)
            self.assertEqual(stats[n['family']]['observed_days'], 0)
            self.assertEqual(stats[n['family']]['streak'], 0)
            self.assertIsNone(stats[n['family']]['last'])

    def test_q38_criticism_transfer_preserves_evidence_scope(self):
        q = next(q for q in self.items if q['id'] == 'social-message-criticism-membership-c')
        self.assertIn('disapproving social judgments', q['o'][q['a']])
        self.assertNotEqual(q['o'][q['a']], 'Non-volunteers are generally less happy than volunteers.')
        for q in self.items:
            if q['family'] == 'social-message-inference':
                self.assertEqual(q['source_question'], 38)
                self.assertNotIn('≠ 直接批评', q['skill'])
                self.assertNotIn('≠ 被直接批评', q['skill'])
                self.assertRegex(q['exp']['meaning'], r'批评|criticism')

    def test_part_b_strength_is_not_promoted_to_universal_uniqueness(self):
        notes = [n for n in self.notes if n.get('session_id') == '2026-10-04-2011-partb']
        self.assertEqual(sum(n['kind'] == 'translation_difficulty' for n in notes), 2)
        anaphora = next(n for n in notes if n['family'] == 'paragraph-order-anaphora'
                        and n['kind'] == 'user_reported_wrong')
        self.assertIn('单独出现不构成唯一', anaphora['note'])
        for q in self.items:
            if q['family'].startswith('paragraph-order-'):
                self.assertNotIn('必须找到前面唯一', q['exp']['meaning'])
                self.assertNotIn('非常硬', q['exp']['structure'])

    def test_source_transfer_explanations_are_shuffle_independent(self):
        for path in (ROOT / 'data/questions').glob('*.json'):
            for q in review.load(path):
                if q.get('source_exam') == '2011-english1' or 'passage-review' in path.name:
                    with self.subTest(qid=q['id']):
                        self.assertIsNone(re.search(r'第[一二三四1234]项|前三项|\b[ABCD]\s*[.、：]|[ABCD]选项', q['exp']['rest']))

    def test_legacy_passage_notice_keeps_the_existing_round_and_storage_key(self):
        page = (ROOT / 'passage-drill-2026-09-30.html').read_text()
        self.assertIn('第29题正确答案为A', page)
        data = json.JSONDecoder().raw_decode(page.split('window.REVIEW_DATA=', 1)[1])[0]
        self.assertEqual(data['storagePrefix'], 'kaoyan.passage.v1.')
        self.assertEqual(data['storageId'], '2026-09-30-executive-moves')
        self.assertEqual([q['id'] for q in data['questions']], [
            'directness-engineer-a', 'career-chef-a', 'recruitment-poach-a', 'cling-policy-a',
            'viewpoint-renting-a', 'title-preprint-a', 'lined-up-flat-a', 'absolute-cafes-a'])
        variants = [q for q in self.items if q['family'] == 'lined-up']
        self.assertTrue(all('不是过去完成时' in q['exp']['structure'] or '不是过去完成时助动词' in q['exp']['structure']
                            for q in variants))
        self.assertFalse(any('resigned from her apartment lease' in q['q'] for q in variants))

    def test_correction_notices_preserve_archives_scores_and_locked_daily(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'data', root / 'data')
            shutil.copytree(ROOT / 'web', root / 'web')
            shutil.copy(ROOT / 'today.html', root / 'today.html')
            protected = [root / 'today.html', root / 'data/daily.json', root / 'data/days/2026-10-04.json',
                         root / 'data/result-evidence.json', root / 'data/excluded-evidence.json']
            protected += list((root / 'data/article-reviews').glob('*.json'))
            before = {p: p.read_bytes() for p in protected}
            expected_scoring = review.make_stats(self.items, review.load(root / 'data/result-evidence.json')['rows'],
                                                 self.notes, date(2026, 10, 4))
            run(root, date(2026, 10, 4), False, 'pkppkqbobs/kaoyan-english-trainer')
            latest = article_review.build(root)
            audited_partb = review.load(root / 'data/article-reviews/2026-10-04-2011-partb-r2.json')
            self.assertEqual(audited_partb['storageId'], '2026-10-04-2011-partb-r2')
            self.assertEqual(len(audited_partb['article_session']['current_families']), 2)
            self.assertEqual(len(audited_partb['article_session']['historical_families']), 6)
            for path, contents in before.items():
                self.assertEqual(path.read_bytes(), contents, str(path))
            old = review.load(root / 'data/article-reviews/2026-10-03-2011-text4.json')
            old_page = (root / 'article-review-2026-10-03-2011-text4.html').read_text()
            self.assertIn('第38题正确答案为A', old_page)
            self.assertIn('不能证明唯一相邻', (root / 'article-review-2026-10-04-2011-partb-r2.html').read_text())
            embedded = old_page.split('window.REVIEW_DATA=', 1)[1].split(';</script>', 1)[0]
            self.assertEqual(json.loads(embedded), old)
            self.assertEqual(review.load(root / 'data/review-state.json')['families'], expected_scoring)
            once = {p: p.read_bytes() for p in root.glob('article-review*.html')}
            article_review.build(root)
            self.assertEqual({p: p.read_bytes() for p in once}, once)

    def test_correction_notice_escapes_markup_without_changing_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'web').mkdir()
            (root / 'web/review.js').write_text('// fixture')
            review.save(root / 'data/source-checks/fixture.json', {
                'article_notices': [{'families': ['test'], 'text': '<script>untrusted()</script>'}]})
            payload = {'questions': [{'family': 'test'}], 'storageId': 'old-round'}
            before = copy.deepcopy(payload)
            page = article_review.render_page(root, payload)
            self.assertIn('&lt;script&gt;', page)
            self.assertNotIn('<script>untrusted()', page)
            self.assertEqual(payload, before)


if __name__ == '__main__':
    unittest.main()
