"""Production entry point: preserve raw reports while excluding invalid items from scoring."""
import argparse
import os
from datetime import date, datetime
import daily_review as review


def apply_exclusions(rows, rules):
    for rule in rules:
        if 'origin' not in rule and not {'date', 'qid'}.issubset(rule):
            raise ValueError('Quality exclusion must identify an Issue or a dated question')
    accepted, excluded = [], []
    for row in rows:
        rule = next((r for r in rules if r['family'] == row['family'] and
                     all(row.get(key) == (int(r[key]) if key == 'origin' else r[key])
                         for key in ('origin', 'date', 'qid') if key in r)), None)
        if rule:
            excluded.append({**row, 'exclusion_reason': rule['reason']})
        else:
            accepted.append(row)
    return accepted, excluded


def run(root, day, sync, repo):
    original_evidence = review.evidence
    def checked_evidence(issues, owner):
        rows, issue_ids = original_evidence(issues, owner)
        rules = review.load(root / 'data/quality-exclusions.json', [])
        accepted, excluded = apply_exclusions(rows, rules)
        review.save(root / 'data/excluded-evidence.json', excluded)
        return accepted, issue_ids
    review.evidence = checked_evidence
    try:
        return review.build(root, day, sync, repo)
    finally:
        review.evidence = original_evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sync', action='store_true')
    parser.add_argument('--date', default=datetime.now(review.TZ).date().isoformat())
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', 'pkppkqbobs/kaoyan-english-trainer'))
    args = parser.parse_args()
    run(review.ROOT, date.fromisoformat(args.date), args.sync, args.repo)
