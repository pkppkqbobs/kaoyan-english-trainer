"""Explicit grammar targets, immutable legacy repairs, and scoped score exclusions."""
import copy
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_review as review
from run_daily import apply_exclusions
from test_daily_review import sample

QID = 'cloze-whatever-documents-registrar-p'
TARGET = 'whatever documents the applicant submits before Friday'


def marked_question(kind='phrase'):
    q = sample('fixture-marked', 'nested')
    q['q'] = 'The clerk accepts whatever papers arrive. What role does the underlined ' + kind + ' play?'
    q['prompt_marks'] = [{'type': 'underline', 'text': 'whatever papers arrive', 'occurrence': 0}]
    return q


class PromptMarkTests(unittest.TestCase):
    def test_word_phrase_and_clause_references_need_real_targets(self):
        for kind in ('word', 'phrase', 'clause'):
            q = marked_question(kind)
            with self.subTest(kind=kind):
                ranges = review.prompt_mark_ranges(q)
                self.assertEqual([q['q'][start:end] for start, end in ranges], ['whatever papers arrive'])
                del q['prompt_marks']
                with self.assertRaisesRegex(AssertionError, 'Missing underline target'):
                    review.prompt_mark_ranges(q)

    def test_new_source_bank_cannot_publish_an_unmarked_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            questions = [sample('family-' + str(i), 'family-' + str(i)) for i in range(8)]
            questions[0] = marked_question()
            del questions[0]['prompt_marks']
            review.save(root / 'data/base-bank.json', questions)
            with self.assertRaisesRegex(AssertionError, 'Missing underline target'):
                review.bank(root)

    def test_repeated_words_need_an_explicit_occurrence_even_with_unicode(self):
        q = marked_question('word')
        q['q'] = '😀 time and time. What does the underlined word mean?'
        q['prompt_marks'] = [{'type': 'underline', 'text': 'time'}]
        with self.assertRaisesRegex(AssertionError, 'Ambiguous prompt mark'):
            review.prompt_mark_ranges(q)
        q['prompt_marks'][0]['occurrence'] = 1
        self.assertEqual(review.prompt_mark_ranges(q), [(q['q'].rindex('time'), q['q'].rindex('time') + 4)])

    def test_missing_overlapping_and_invalid_marks_fail_validation(self):
        cases = [None, [{'type': 'bold', 'text': 'papers'}],
                 [{'type': 'underline', 'text': ''}],
                 [{'type': 'underline', 'text': 'not present'}],
                 [{'type': 'underline', 'text': 'papers', 'occurrence': True}],
                 [{'type': 'underline', 'text': 'papers', 'occurrence': 9}],
                 [{'type': 'underline', 'text': 'whatever papers'}, {'type': 'underline', 'text': 'papers arrive'}]]
        for marks in cases:
            with self.subTest(marks=marks):
                q = marked_question(); q['prompt_marks'] = marks
                with self.assertRaises(AssertionError):
                    review.prompt_mark_ranges(q)

    def test_source_is_fixed_but_original_daily_and_article_remain_unmarked(self):
        fixed = next(q for q in review.bank(ROOT) if q['id'] == QID)
        self.assertEqual([fixed['q'][s:e] for s, e in review.prompt_mark_ranges(fixed)], [TARGET])
        for name in ('data/days/2026-11-08.json', 'data/article-reviews/2026-11-02-2016-text1.json'):
            path = ROOT / name
            original_bytes = path.read_bytes()
            q = next(q for q in review.load(path)['questions'] if q['id'] == QID)
            self.assertNotIn('prompt_marks', q)
            review.validate(q)  # Compatibility validation never rewrites a frozen publication.
            self.assertEqual(q['a'], 0)
            self.assertEqual(path.read_bytes(), original_bytes)
        metadata = review.load(ROOT / 'data/question-presentations.json')['questions'][QID]
        self.assertEqual(metadata['prompt'], fixed['q'])
        self.assertEqual(metadata['prompt_marks'], fixed['prompt_marks'])

    def test_public_quality_notice_must_have_a_corresponding_server_exclusion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            metadata = review.load(ROOT / 'data/question-presentations.json')
            review.save(root / 'data/question-presentations.json', metadata)
            with self.assertRaisesRegex(AssertionError, 'lacks a quality exclusion'):
                review.validate_presentations(root)
            review.save(root / 'data/quality-exclusions.json', review.load(ROOT / 'data/quality-exclusions.json'))
            review.validate_presentations(root)

    def test_invalid_original_answers_neither_add_errors_nor_mastery_and_raw_rows_survive(self):
        rows = [
            {'origin': 900, 'date': '2026-11-09', 'source_date': '2026-11-08', 'qid': QID,
             'family': 'nested', 'ok': False, 'ms': 180000, 'uncertain': True},
            {'origin': 901, 'date': '2026-11-09', 'source_date': '2026-11-02', 'qid': QID,
             'family': 'nested', 'ok': True, 'ms': 1000, 'uncertain': False},
            {'origin': 902, 'date': '2026-11-09', 'source_date': '2026-11-09', 'qid': QID,
             'family': 'nested', 'ok': True, 'ms': 1000, 'uncertain': False},
        ]
        original = copy.deepcopy(rows)
        accepted, excluded = apply_exclusions(rows, review.load(ROOT / 'data/quality-exclusions.json'))
        self.assertEqual(rows, original)
        self.assertEqual([r['origin'] for r in accepted], [902])
        self.assertEqual([r['origin'] for r in excluded], [900, 901])
        self.assertFalse(excluded[0]['ok']); self.assertTrue(excluded[1]['ok'])
        stats = review.make_stats([sample('fresh-nested', 'nested')], accepted, [], date(2026, 11, 9))['nested']
        self.assertEqual((stats['errors'], stats['streak'], stats['observed_days'], stats['slow_or_uncertain']), (0, 1, 1, False))


if __name__ == '__main__':
    unittest.main()
