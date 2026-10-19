"""Length cues are maintenance metadata, independent of real learning evidence."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_review as review
import option_length_audit as audit
import question_bank_audit as inventory


class OptionLengthTests(unittest.TestCase):
    def test_extreme_strategy_splits_ties_instead_of_claiming_full_credit(self):
        equal = audit.metrics(['word', 'test', 'case', 'quiz'], 1)
        self.assertEqual(equal['longest_guess_credit'], .25)
        self.assertEqual(equal['shortest_guess_credit'], .25)
        self.assertFalse(equal['correct_uniquely_longest'])
        tied = audit.metrics(['long', 'word', 'a', 'b'], 0)
        self.assertEqual(tied['longest_guess_credit'], .5)
        self.assertEqual(tied['shortest_guess_credit'], 0)

    def test_curated_options_keep_identity_key_context_dates_and_budget(self):
        records = inventory.catalogue(ROOT)
        revisions = review.load(ROOT / 'data/option-length-revisions.json')['questions']
        self.assertEqual(len({r['qid'] for r in revisions}), len(revisions))
        self.assertGreaterEqual(len(revisions), 90)
        for row in revisions:
            with self.subTest(qid=row['qid']):
                q = records[row['qid']]['question']
                self.assertEqual(q['a'], row['answer_index'])
                self.assertEqual(audit.digest(audit.stable_definition(q)), row['stable_definition_sha256'])
                self.assertEqual(audit.digest(q), row['after_sha256'])
                self.assertEqual(list(map(len, q['o'])), row['after_lengths'])
                self.assertLessEqual(max(row['after_lengths']) - min(row['after_lengths']), 20)
                self.assertEqual(len(set(q['o'])), 4)

    def test_candidate_bank_has_no_large_longest_correct_cues(self):
        pools = audit.scan(ROOT)['pools']
        for name in ('daily_article', 'home_legacy'):
            with self.subTest(pool=name):
                self.assertEqual(pools[name]['length_cue_flags'], 0)
                self.assertLessEqual(pools[name]['longest_guess_pct'], 35)
                self.assertLessEqual(pools[name]['shortest_guess_pct'], 35)
                # Some correct options still are longest; no answer-length ban.
                self.assertGreater(pools[name]['correct_uniquely_longest'], 0)
        self.assertGreaterEqual(pools['daily_article']['question_count'], 224)

    def test_report_reproduces_current_data_and_labels_guesses_not_user_scores(self):
        current = audit.report(ROOT)
        self.assertEqual(current, review.load(ROOT / 'data/option-length-audit.json'))
        self.assertTrue(current['audit_is_not_scoring_evidence'])
        self.assertIn('not user scores', current['definitions']['guessing'])
        for pool in ('daily_article', 'home_legacy'):
            self.assertLess(current['after']['pools'][pool]['longest_guess_pct'],
                            current['before'][pool]['longest_guess_pct'])

    def test_audit_generation_is_idempotent_and_cannot_add_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'data', root / 'data')
            shutil.copytree(ROOT / 'archive', root / 'archive')
            for p in ROOT.glob('*.html'):
                shutil.copy(p, root / p.name)
            before = {p: p.read_bytes() for p in [*root.glob('*.html'), *(root / 'data').rglob('*.json')]}
            audit.build(root)
            audit.build(root)
            self.assertEqual({p: p.read_bytes() for p in before}, before)
            day = review.load(root / 'data/review-state.json')['as_of']
            rows = review.load(root / 'data/result-evidence.json')['rows']
            notes = review.load(root / 'data/learning-notes.json')
            from datetime import date
            stats = review.make_stats(review.bank(root), rows, notes, date.fromisoformat(day))
            review.save(root / 'data/option-length-audit.json', {'rows': [{'errors': 100, 'streak': 99}]})
            self.assertEqual(review.make_stats(review.bank(root), rows, notes, date.fromisoformat(day)), stats)

    def test_old_text_report_uses_published_options_after_source_revision(self):
        payload = review.load(ROOT / 'data/days/2026-10-19.json')
        q = next(q for q in payload['questions'] if q['id'] == 'conceivably-ferry')
        active = next(v for v in review.bank(ROOT) if v['id'] == q['id'])
        self.assertNotEqual(active['o'], q['o'])
        choice = q['o'][q['a']]
        row = {'qid': q['id'], 'family': q['family'], 'pick': q['a'], 'expected': q['a'],
               'pickText': choice, 'expectedText': choice, 'ok': False,
               'ms': 1000, 'uncertain': False, 'answeredOn': '2026-10-19'}
        obj = {'version': 3, 'roundId': 'old-wording-regression', 'date': '2026-10-19',
               'module': 'daily', 'storageId': '2026-10-19', 'answers': [row]}
        issue = {'number': 999, 'created_at': '2026-10-19T12:00:00Z',
                 'body': '<!-- review-json:v3\n' + json.dumps(obj) + '\n-->'}
        parsed = review.parse_issue(issue, ROOT)[1]
        self.assertTrue(parsed[0]['ok'], 'recompute against original snapshot, not client ok or live bank')
        forged = copy.deepcopy(obj)
        forged['answers'][0].update(pickText=active['o'][active['a']], expectedText=active['o'][active['a']])
        with self.assertRaises(ValueError):
            review.parse_issue({**issue, 'body': '<!-- review-json:v3\n' + json.dumps(forged) + '\n-->'}, ROOT)


if __name__ == '__main__':
    unittest.main()
