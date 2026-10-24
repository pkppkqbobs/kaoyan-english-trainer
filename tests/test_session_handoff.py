"""The handoff indexes accepted evidence; it never becomes scoring evidence."""
import copy
import contextlib
from datetime import date
import json
import io
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_review as review
import build_session_handoff as handoff


def fixture(root):
    families = ['author-stance', 'inference-boundary', 'conditions', 'paragraph-order-anaphora',
                'nested', 'familiar-word-polysemy', 'process-stage-role', 'tone']
    items = [{'id': f'fixture-{i}', 'family': f, 'target': f, 'introduced': None, 'budget': 35,
              'q': 'An independent complete fixture sentence about ' + f,
              'o': ['one', 'two', 'three', 'four'], 'a': 1,
              'exp': {k: 'Fixture explanation' for k in review.EXP_KEYS}} for i, f in enumerate(families)]
    notes = [
        {'family': 'author-stance', 'date': '2026-10-24', 'kind': 'user_reported_wrong',
         'source_exam': '2014-english1', 'source_part': 'Reading Text 4', 'source_question': 36,
         'reported_pick': 'B', 'expected': 'A', 'final_choice_letter_confirmed': True,
         'note': '抓住局部表扬，漏读转折后的总体批评。'},
        {'family': 'inference-boundary', 'date': '2026-10-24', 'kind': 'user_reported_confusion',
         'source_exam': '2014-english1', 'source_part': 'Reading Text 4', 'source_question': 38,
         'candidate_choices': ['A', 'C'], 'expected': 'C', 'final_choice_letter_confirmed': False,
         'note': '仅知在两项之间犹豫，最终选项未确认。'},
        {'family': 'inference-boundary', 'date': '2026-10-22', 'kind': 'user_reported_confusion',
         'source_exam': '2014-english1', 'source_part': 'Reading Text 2', 'source_question': 27,
         'final_choice_letter_confirmed': False, 'note': '误读学位与学科，最终选项未确认。'},
        {'family': 'familiar-word-polysemy', 'date': '2026-10-24', 'kind': 'translation_difficulty',
         'source_exam': '2014-english1', 'source_part': 'Reading Text 4', 'mark_type': 'box',
         'source_spans': ['presupposes', 'interpretation'], 'note': '两处画框，仅是翻译困难。'},
        {'family': 'inference-boundary', 'date': '2026-10-23', 'kind': 'correct_but_uncertain',
         'source_exam': '2014-english1', 'source_part': 'Reading Text 3', 'source_question': 33,
         'reported_pick': 'B', 'expected': 'B', 'first_considered': 'A',
         'final_choice_letter_confirmed': True, 'note': '从A改B答对，但仍不确定。'},
    ]
    rows = [{'date': '2026-10-24', 'source_date': '2026-10-24', 'family': q['family'],
             'qid': q['id'], 'ok': True, 'ms': 1000, 'uncertain': False,
             'origin': 27, 'round_id': 'accepted-round-27'} for q in items]
    review.save(root / 'data/base-bank.json', items)
    review.save(root / 'data/learning-notes.json', notes)
    review.save(root / 'data/result-evidence.json', {'rows': rows, 'issues': [27]})
    payload = {'date': '2026-10-24', 'repo': handoff.REPO, 'questions': items, 'retry': {}, 'issues_used': [27]}
    review.save(root / 'data/daily.json', payload)
    review.save(root / 'data/days/2026-10-24.json', payload)
    review.save(root / 'data/source-checks/2014-english1.json', {
        'exam': '2014-english1', 'answers': {'36': 'A', '38': 'C', '27': 'C', '33': 'B'}})
    refresh_state(root)


def refresh_state(root):
    evidence = review.load(root / 'data/result-evidence.json')
    notes = review.load(root / 'data/learning-notes.json')
    review.save(root / 'data/review-state.json', {'as_of': '2026-10-24', 'issues': evidence['issues'],
        'families': review.make_stats(review.bank(root), evidence['rows'], notes, date(2026, 10, 24))})


class SessionHandoffTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        fixture(self.root)

    def test_repeated_build_is_byte_identical_and_does_not_touch_sources(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        one = handoff.build(self.root)
        files = [self.root / 'SESSION_HANDOFF.md', self.root / 'data/session-handoff.json']
        generated = [(p.read_bytes(), p.stat().st_mtime_ns) for p in files]
        self.assertEqual(one, handoff.build(self.root))
        self.assertEqual([(p.read_bytes(), p.stat().st_mtime_ns) for p in files], generated)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_latest_notes_without_article_session_and_unknown_final_choices(self):
        report = handoff.make_report(self.root)
        stage = report['recent_paper'][0]
        self.assertEqual((stage['exam'], stage['part']), ('2014-english1', 'Text 4'))
        self.assertEqual(stage['article_session_files'], [])
        q36 = next(i for i in stage['items'] if i['question'] == 36)
        self.assertEqual((q36['kind'], q36['final_choice']), ('user_reported_wrong', 'B'))
        q38 = next(i for i in stage['items'] if i['question'] == 38)
        self.assertIsNone(q38['final_choice'])
        self.assertEqual(q38['candidate_choices'], ['A', 'C'])
        self.assertEqual(stage['boxed_spans'], ['interpretation', 'presupposes'])
        self.assertEqual({p['question'] for p in report['pending']}, {27, 38})

    def test_paper_wrong_uncertain_and_translation_do_not_change_web_counters(self):
        state = (self.root / 'data/review-state.json').read_bytes()
        evidence = (self.root / 'data/result-evidence.json').read_bytes()
        report = handoff.build(self.root)
        self.assertEqual(report['web']['latest_daily']['correct'], 8)
        self.assertIn('Q33 答对但犹豫', handoff.markdown(report))
        self.assertEqual(review.load(self.root / 'data/review-state.json')['families']['author-stance']['errors'], 0)
        self.assertEqual((self.root / 'data/review-state.json').read_bytes(), state)
        self.assertEqual((self.root / 'data/result-evidence.json').read_bytes(), evidence)
        self.assertTrue(report['handoff_is_not_scoring_evidence'])

    def test_duplicate_rows_and_duplicate_issues_cannot_double_count_a_round(self):
        path = self.root / 'data/result-evidence.json'
        evidence = review.load(path)
        evidence['rows'] += copy.deepcopy(evidence['rows'])
        evidence['rows'] += [{**r, 'origin': 28} for r in evidence['rows'][:8]]
        evidence['issues'].append(28)
        review.save(path, evidence)
        refresh_state(self.root)
        latest = handoff.make_report(self.root)['web']['latest_daily']
        self.assertEqual((latest['issue'], latest['correct'], latest['total']), (27, 8, 8))
        self.assertEqual(len(review.load(path)['rows']), 24, 'generation must not rewrite source rows')

    def test_incomplete_round_cannot_be_reported_as_success(self):
        path = self.root / 'data/result-evidence.json'
        evidence = review.load(path); evidence['rows'].pop(); review.save(path, evidence)
        report = handoff.make_report(self.root)
        self.assertIsNone(report['web']['latest_daily'])
        self.assertEqual(report['web']['current_daily_status'], 'unverified')
        self.assertNotIn('8/8', handoff.markdown(report))

    def test_unaccepted_issue_and_ambiguous_module_cannot_become_verified(self):
        path = self.root / 'data/result-evidence.json'
        evidence = review.load(path)
        evidence['rows'] = [{**r, 'origin': 28} for r in evidence['rows']]
        review.save(path, evidence)
        self.assertIsNone(handoff.make_report(self.root)['web']['latest_daily'])
        fixture(self.root)
        review.save(self.root / 'data/article-reviews/ambiguous.json', review.load(self.root / 'data/daily.json'))
        self.assertIsNone(handoff.make_report(self.root)['web']['latest_daily'])

    def test_excluded_answer_is_not_reintroduced_for_a_full_score(self):
        review.save(self.root / 'data/quality-exclusions.json', [
            {'family': 'author-stance', 'origin': 27, 'reason': 'fixture ambiguity'}])
        report = handoff.make_report(self.root)
        self.assertIsNone(report['web']['latest_daily'])
        self.assertEqual(report['web']['review_state_status'], 'unverified')

    def test_late_submission_of_old_sheet_keeps_current_daily_completion(self):
        payload = review.load(self.root / 'data/daily.json')
        review.save(self.root / 'data/days/2026-10-23.json', {**payload, 'date': '2026-10-23'})
        path = self.root / 'data/result-evidence.json'; evidence = review.load(path)
        evidence['rows'] += [{**r, 'source_date': '2026-10-23', 'origin': 28, 'round_id': 'later-old-sheet'}
                             for r in evidence['rows'][:8]]
        evidence['issues'].append(28); review.save(path, evidence); refresh_state(self.root)
        report = handoff.make_report(self.root)
        self.assertEqual(report['web']['latest_daily']['issue'], 28)
        self.assertEqual(report['web']['latest_daily']['date'], '2026-10-23')
        self.assertEqual(report['web']['current_daily_issue'], 27)
        self.assertEqual(report['web']['current_daily_status'], 'verified')

    def test_rejected_issue_reports_retained_previous_grade_honestly(self):
        review.save(self.root / 'data/rejected-results.json', {'issues': [
            {'issue': 27, 'reason': 'incomplete edited report', 'retained_previous': True}]})
        report = handoff.make_report(self.root)
        self.assertEqual(report['web']['latest_daily']['status'], 'retained_previous')
        self.assertEqual(report['web']['current_daily_status'], 'unverified')
        self.assertIn('当前Issue未验证', handoff.markdown(report))

    def test_later_confirmation_resolves_unknown_without_rewriting_notes(self):
        path = self.root / 'data/learning-notes.json'; notes = review.load(path)
        notes.append({**notes[1], 'date': '2026-10-25', 'kind': 'correct_but_uncertain',
                      'reported_pick': 'C', 'final_choice_letter_confirmed': True})
        review.save(path, notes)
        before = path.read_bytes()
        report = handoff.build(self.root)
        self.assertNotIn(38, {p.get('question') for p in report['pending']})
        self.assertEqual(path.read_bytes(), before)
        q38 = next(i for i in report['recent_paper'][0]['items'] if i['question'] == 38)
        self.assertEqual(q38['final_choice'], 'C')

    def test_same_day_conflicting_final_choices_stay_unknown(self):
        path = self.root / 'data/learning-notes.json'; notes = review.load(path)
        notes.extend([{**notes[1], 'reported_pick': choice, 'final_choice_letter_confirmed': True}
                      for choice in ('A', 'C')])
        review.save(path, notes)
        report = handoff.make_report(self.root)
        item = next(i for i in report['recent_paper'][0]['items'] if i['question'] == 38)
        self.assertTrue(item['choice_conflict'])
        self.assertIsNone(item['final_choice'])
        self.assertTrue(any(p.get('question') == 38 and '冲突' in p['status'] for p in report['pending']))

    def test_dated_appended_clarification_is_separate_from_original_reason(self):
        path = self.root / 'data/learning-notes.json'; notes = review.load(path)
        notes[0]['note'] += ' 后续词义追问（2026-10-25）：后来询问regrettably，不倒推首次原因。'
        notes[1]['note'] += ' 后续明确补充（2026-10-24）：先询问词义。 后续明确补充（2026-10-25）：用户把exclusive译成广泛，最终选项仍未确认。'
        review.save(path, notes)
        report = handoff.make_report(self.root)
        stage = report['recent_paper'][0]
        self.assertEqual(stage['date'], '2026-10-25')
        q36 = next(i for i in stage['items'] if i['question'] == 36)
        q38 = next(i for i in stage['items'] if i['question'] == 38)
        self.assertEqual(q36['summary'], '抓住局部表扬，漏读转折后的总体批评。')
        self.assertIn('regrettably', q36['followup']['summary'])
        self.assertIn('exclusive', handoff.markdown(report))
        self.assertEqual(q38['followup']['date'], '2026-10-25')
        self.assertIsNone(q38['final_choice'])
        self.assertEqual(review.load(self.root / 'data/review-state.json')['families']['author-stance']['errors'], 0)

    def test_nested_unknown_choice_retains_original_note_locator(self):
        path = self.root / 'data/learning-notes.json'; notes = review.load(path)
        parent = {'family': 'familiar-word-polysemy', 'date': '2026-10-24', 'kind': 'user_reported_confusion',
                  'source_exam': '2014-english1', 'source_part': 'Section I', 'note': '词义误读，最终字母未知。',
                  'user_confirmed_reasoning': [{'question': 14, 'final_choice_letter_confirmed': False}]}
        notes.append(parent); review.save(path, notes)
        report = handoff.make_report(self.root)
        item = next(p for p in report['pending'] if p.get('question') == 14)
        self.assertEqual(item['source']['note_fingerprint'], handoff.fingerprint(parent)[:16])

    def test_priority_order_changes_with_evidence_not_taxonomy_order(self):
        initial = handoff.make_report(self.root)
        self.assertEqual(initial['priorities'][0]['mechanism'], 'stance')
        path = self.root / 'data/learning-notes.json'; notes = review.load(path)
        notes.append({'family': 'conditions', 'date': '2026-10-25', 'kind': 'user_reported_wrong',
                      'source_exam': '2014-english1', 'source_part': 'Text 1', 'source_question': 21,
                      'reported_pick': 'A', 'expected': 'B', 'note': '新确认的条件与施事误读。'})
        review.save(path, notes)
        self.assertEqual(handoff.make_report(self.root)['priorities'][0]['mechanism'], 'roles')

    def test_reordered_notes_keep_summary_order_and_duplicates_do_not_add_observations(self):
        first = handoff.make_report(self.root)
        path = self.root / 'data/learning-notes.json'; notes = review.load(path)
        review.save(path, list(reversed(notes)) + [notes[0]])
        second = handoff.make_report(self.root)
        for key in ('recent_paper', 'priorities', 'pending'):
            self.assertEqual(first[key], second[key])

    def test_missing_state_and_missing_source_check_remain_explicitly_unverified(self):
        (self.root / 'data/review-state.json').unlink()
        (self.root / 'data/source-checks/2014-english1.json').unlink()
        report = handoff.make_report(self.root)
        self.assertEqual(report['web']['review_state_status'], 'unverified')
        self.assertEqual(report['web']['current_daily_status'], 'unverified')
        self.assertTrue(any('缺 source-check' in warning for warning in report['warnings']))
        self.assertTrue(all(m['web_errors'] is None for p in report['priorities'] for m in p['families']))

    def test_source_conflict_is_not_silently_presented_as_a_checked_error(self):
        path = self.root / 'data/source-checks/2014-english1.json'
        value = review.load(path); value['answers']['36'] = 'C'; review.save(path, value)
        report = handoff.make_report(self.root)
        item = next(i for i in report['recent_paper'][0]['items'] if i['question'] == 36)
        self.assertEqual(item['reference_status'], 'conflict')
        self.assertIn('记录待核对', handoff.markdown(report))

    def test_malformed_input_preserves_both_previous_outputs(self):
        handoff.build(self.root)
        files = [self.root / 'SESSION_HANDOFF.md', self.root / 'data/session-handoff.json']
        before = [p.read_bytes() for p in files]
        (self.root / 'data/learning-notes.json').write_text('{broken')
        with self.assertRaises(ValueError):
            handoff.build(self.root)
        self.assertEqual([p.read_bytes() for p in files], before)

    def test_second_output_write_failure_rolls_back_first(self):
        handoff.build(self.root)
        files = [self.root / 'SESSION_HANDOFF.md', self.root / 'data/session-handoff.json']
        before = [p.read_bytes() for p in files]
        path = self.root / 'data/learning-notes.json'; notes = review.load(path)
        notes[0]['note'] += '新澄清'; review.save(path, notes)
        replace = os.replace
        def fail_markdown(source, target):
            if Path(target).name == 'SESSION_HANDOFF.md':
                raise OSError('fixture output failure')
            return replace(source, target)
        with mock.patch.object(handoff.os, 'replace', side_effect=fail_markdown), self.assertRaises(OSError):
            handoff.build(self.root)
        self.assertEqual([p.read_bytes() for p in files], before)

    def test_only_short_training_fields_are_exported_and_secrets_are_redacted(self):
        path = self.root / 'data/learning-notes.json'; notes = review.load(path)
        notes[0].update(raw_chat='DO NOT COPY WHOLE CHAT', user_reported_reasoning=
                        '训练说明 github_pat_private_fixture 350000200001010011 learner@example.com')
        review.save(path, notes)
        result = handoff.make_report(self.root)
        text = json.dumps(result, ensure_ascii=False) + handoff.markdown(result)
        for secret in ('DO NOT COPY WHOLE CHAT', 'github_pat_private_fixture', '350000200001010011', 'learner@example.com'):
            self.assertNotIn(secret, text)

    def test_workflow_uses_existing_sync_and_commit_without_output_trigger_loop(self):
        workflow = (ROOT / '.github/workflows/daily-review.yml').read_text()
        self.assertLess(workflow.index('scripts/run_daily.py --sync'), workflow.index('scripts/build_session_handoff.py'))
        self.assertLess(workflow.index('scripts/partb_review.py'), workflow.index('scripts/build_session_handoff.py'))
        self.assertLess(workflow.index('scripts/build_session_handoff.py'), workflow.index('git add --'))
        self.assertIn('git add -- today.html data archive SESSION_HANDOFF.md', workflow)
        triggers = workflow.split('  issues:', 1)[0]
        self.assertIn("'data/learning-notes.json'", triggers)
        self.assertNotIn('SESSION_HANDOFF.md', triggers)
        self.assertNotIn('data/session-handoff.json', triggers)

    def test_full_generation_after_a_new_note_keeps_locked_quizzes_and_grades(self):
        import article_review
        import partb_review
        from run_daily import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('data', 'web', 'archive'):
                shutil.copytree(ROOT / name, root / name)
            for p in ROOT.glob('*.html'):
                shutil.copy(p, root / p.name)
            handoff.build(root)
            notes_path = root / 'data/learning-notes.json'
            notes = review.load(notes_path)
            # A synthetic observation exists only in this temporary regression.
            notes.append({'family': 'author-stance', 'date': review.load(root / 'data/daily.json')['date'],
                          'kind': 'user_reported_confusion', 'source_exam': '2014-english1',
                          'source_part': 'Reading Text 4', 'source_question': 37,
                          'final_choice_letter_confirmed': False, 'note': 'fixture-only clarification without a new article session'})
            review.save(notes_path, notes)
            protected = [*root.glob('*.html'), *(root / 'data').rglob('*.json')]
            before = {p: p.read_bytes() for p in protected if p.name not in ('session-handoff.json', 'review-state.json')}
            old_errors = {f: s['errors'] for f, s in review.load(root / 'data/review-state.json')['families'].items()}
            day = date.fromisoformat(review.load(root / 'data/daily.json')['date'])
            with contextlib.redirect_stdout(io.StringIO()):
                run(root, day, False, handoff.REPO)
                article_review.build(root)
                partb_review.build(root)
                report = handoff.build(root)
            self.assertEqual({p: p.read_bytes() for p in before}, before)
            self.assertEqual({f: s['errors'] for f, s in review.load(root / 'data/review-state.json')['families'].items()}, old_errors)
            self.assertTrue(any(p.get('question') == 37 for p in report['pending']))

    def test_actual_issue_27_recent_2014_notes_and_small_chinese_document(self):
        report = handoff.make_report(ROOT)
        # Freeze the known genuine round; future legitimate days must not make
        # this regression insist that #27 is still the latest result.
        evidence = review.load(ROOT / 'data/result-evidence.json')
        rows = [r for r in evidence['rows'] if r['origin'] == 27]
        rounds, _ = handoff.web_results(handoff.Inputs(ROOT), {'issues': [27], 'rows': rows})
        self.assertEqual((rounds['daily']['issue'], rounds['daily']['correct']), (27, 8))
        self.assertEqual(len(report['recent_paper']), 5)
        document = handoff.markdown(report)
        self.assertGreaterEqual(len(re.findall('[\u4e00-\u9fff]', document)), 1000)
        self.assertLessEqual(len(re.findall('[\u4e00-\u9fff]', document)), 2000)


if __name__ == '__main__':
    unittest.main()
