"""Reproducible length-cue inventory; never imported by grading or scheduling.

Ties are split uniformly. These are hypothetical guessing strategies applied
to source questions, not the learner's accuracy or confirmed exposure.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import daily_review as review
import question_bank_audit as inventory

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def stable_definition(question):
    # Explanations and choices may be edited; identity, key, context and dates
    # must stay unchanged. Home diagnostics use the legacy why/trap fields.
    return {k: v for k, v in question.items() if k not in {'o', 'exp', 'why', 'trap'}}


def metrics(options, answer):
    lengths = list(map(len, options))
    maximum, minimum = max(lengths), min(lengths)
    other = [length for i, length in enumerate(lengths) if i != answer]
    return {
        'lengths': lengths,
        'spread': maximum - minimum,
        'correct_uniquely_longest': lengths[answer] == maximum and lengths.count(maximum) == 1,
        'correct_uniquely_shortest': lengths[answer] == minimum and lengths.count(minimum) == 1,
        'longest_guess_credit': 1 / lengths.count(maximum) if lengths[answer] == maximum else 0,
        'shortest_guess_credit': 1 / lengths.count(minimum) if lengths[answer] == minimum else 0,
        'length_cue_flag': lengths[answer] > max(other) and (
            lengths[answer] - max(other) >= 10 or lengths[answer] > 1.4 * sum(other) / 3),
    }


def summarize(items):
    count = len(items)
    return {
        'question_count': count,
        'correct_uniquely_longest': sum(q['correct_uniquely_longest'] for q in items),
        'correct_uniquely_shortest': sum(q['correct_uniquely_shortest'] for q in items),
        'longest_guess_pct': round(100 * sum(q['longest_guess_credit'] for q in items) / count, 2) if count else None,
        'shortest_guess_pct': round(100 * sum(q['shortest_guess_credit'] for q in items) / count, 2) if count else None,
        'length_cue_flags': sum(q['length_cue_flag'] for q in items),
        'max_spread': max((q['spread'] for q in items), default=0),
    }


def scan(root=ROOT):
    groups, questions = {}, {}
    for key, entry in inventory.catalogue(root).items():
        # Full paragraph ordering has no four-option answer length. Historical
        # archive-only banks are represented by their immutable published rounds.
        if entry['pool'].startswith('archive') or entry['pool'] == 'partb_full':
            continue
        q = entry['question']
        options, answer = (q['options'], q['answer']) if 'options' in q else (q['o'], q['a'])
        row = metrics(options, answer)
        row.update({'pool': entry['pool'], 'family': entry['family'], 'source': entry['source']})
        questions[key] = row
        groups.setdefault(entry['pool'], []).append(row)
    return {'pools': {key: summarize(value) for key, value in sorted(groups.items())},
            'questions': questions}


def report(root=ROOT):
    revisions = review.load(root / 'data/option-length-revisions.json')
    return {
        'schema_version': 2,
        'audited_on': revisions['reviewed_on'],
        'baseline_commit': revisions['baseline_commit'],
        'definitions': {
            'length': 'Unicode character count, matching the existing round quality check.',
            'guessing': 'Always choose an extreme length; choose uniformly among tied extremes. Random baseline is 25%. These are not user scores.',
            'flag': 'Correct option alone is longest and exceeds the next longest by >=10 characters, or is >1.4 times the other three mean lengths. A flag requires semantic review.',
            'scope': 'daily_article and home_legacy are editable candidates; legacy_fixed is a dated standalone snapshot, preserved.',
            'publication': 'Existing daily/article/passage snapshots retain their original options and keys. Source edits apply to future rounds.',
        },
        'before': revisions['before'],
        'after': scan(root),
        'revised_question_count': len(revisions['questions']),
        'policy': 'Review meaningful distractors and matching explanations; check longest AND shortest cues. Do not pad options, exclude answers by length, or treat a revision as a new context or attempt.',
        'audit_is_not_scoring_evidence': True,
    }


def build(root=ROOT):
    result = report(root)
    review.save(root / 'data/option-length-audit.json', result)
    return result


if __name__ == '__main__':
    result = build()
    print(json.dumps({'revised_questions': result['revised_question_count'],
                      'pools': result['after']['pools']}, ensure_ascii=False))
