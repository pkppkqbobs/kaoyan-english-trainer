"""Production entry point: preserve raw reports while excluding invalid items from scoring."""
import argparse
import os
from datetime import date, datetime
import daily_review as review


def apply_exclusions(rows, rules):
    excluded_by_key = {(int(r['origin']), r['family']): r for r in rules}
    accepted, excluded = [], []
    for row in rows:
        rule = excluded_by_key.get((row.get('origin'), row['family']))
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
