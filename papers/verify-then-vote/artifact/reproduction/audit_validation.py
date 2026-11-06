#!/usr/bin/env python3
"""Audit frozen validation channels and prepare blank review forms; no model calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = 'f2a14bd8988371bd231ca6ff137be13e'


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n' for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    # Never overwrite completed human judgments or an existing blank packet.
    args.out.mkdir(parents=True, exist_ok=False)
    val = ROOT / 'tools/evidence/support/validation'
    inputs = [val / 'results' / f'fresh2_{source}-{CHECKER}.jsonl' for source in ('fever', 'scifact')]
    rows = [row for path in inputs for row in read_rows(path)]
    channels = {}
    for label in ('supports', 'refutes'):
        population = [row for row in rows if row['gold'] != label]
        errors = [row for row in population if row['status'] == 'ok' and row['label'] == label]
        channels[label] = {'errors': len(errors), 'denominator': len(population),
                           'rate': len(errors) / len(population), 'error_ids': sorted(row['id'] for row in errors)}
    assert (channels['supports']['errors'], channels['supports']['denominator']) == (18, 350)
    assert (channels['refutes']['errors'], channels['refutes']['denominator']) == (22, 350)
    v5 = ROOT / 'real-agent-eval/v5'
    harm_path = v5 / 'controls/harm_reading.jsonl'
    item_path = v5 / 'benchmark/items_confirmatory.jsonl'
    check_path = v5 / 'results/conf/checks.jsonl'
    harms = read_rows(harm_path)
    items = {row['id']: row for row in read_rows(item_path)}
    checks = {(row['passage_key'], row['proposition_text']): row for row in read_rows(check_path)}
    assert len(harms) == 82 and len({row['item_id'] for row in harms}) == 56
    first, second = [], []
    for idx, row in enumerate(sorted(harms, key=lambda x: (x['item_id'], x['passage_key'], x['proposition'])), 1):
        check = checks[row['passage_key'], row['proposition']]
        item = items[row['item_id']]
        rid = f'pair-{idx:03d}'
        first.append({'review_id': rid, 'item_id': row['item_id'], 'question': item['question'],
                      'candidate_answer': row['value'], 'proposition': row['proposition'],
                      'passage_key': row['passage_key'], 'check_key': check['check_key'],
                      'passage_spans': check['spans'], 'passage_relation_to_proposition': None,
                      'entity_match': None, 'source_fact_assessment': None,
                      'rationale': None, 'reviewer_id': None, 'reviewed_at': None})
        second.append({'review_id': rid, 'item_id': row['item_id'], 'dataset_source': item['source'],
                       'dataset_gold': item['gold'], 'gold_compatibility_assessment': None,
                       'independent_source_references': [], 'rationale': None,
                       'reviewer_id': None, 'reviewed_at': None, 'adjudication': None})
    write_rows(args.out / 'review_first_pass.jsonl', first)
    write_rows(args.out / 'review_gold_second_pass.jsonl', second)
    inputs += [harm_path, item_path, check_path]
    report = {'format': 'verify-then-vote-validation-audit/1', 'validation_pairs': len(rows),
              'channels': channels, 'review_pairs': len(first), 'review_items': len({r['item_id'] for r in first}),
              'human_review_completed': False,
              'interpretation': 'Raw supports excludes false-refutes errors that verify REFUTED answers. Rates are validation-channel statistics, not calibrated deployment forecasts.',
              'inputs': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}}
    (args.out / 'validation_channels.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'channels': {k: [v['errors'], v['denominator']] for k, v in channels.items()},
                      'review_pairs': len(first), 'review_items': report['review_items'], 'human_review_completed': False}))


if __name__ == '__main__':
    main()
