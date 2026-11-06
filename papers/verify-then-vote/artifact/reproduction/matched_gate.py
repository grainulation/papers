#!/usr/bin/env python3
"""Post hoc matched gate ablation of sealed first-pool records, without model calls.

Unlike the frozen confirmatory comparison, gate on/off holds every other policy
field constant at each NEI factor. Historical records and preregistrations remain
unchanged. Uses the historical evaluator's input construction, Rust execution,
and independent Python selection mirror. Outputs must be a new directory.
"""
import argparse
import copy
import csv
import json
from pathlib import Path
from types import SimpleNamespace

from portable import ROOT, digest, load, verify_freezes

CONFIGS = ('member/nei0.1', 'member/nei0.1/gated',
           'member/nei0.5', 'member/nei0.5/gated')


def summary(rows, key, baseline):
    return {'n': len(rows), 'correct': sum(r[key] for r in rows),
            'accuracy': sum(r[key] for r in rows) / len(rows),
            'baseline_correct': sum(r[baseline] for r in rows),
            'corrections': sum(not r[baseline] and r[key] for r in rows),
            'losses': sum(r[baseline] and not r[key] for r in rows)}


def assert_matched(off, on):
    on = copy.deepcopy(on)
    assert on['evidence'].pop('overturn_gate') == 'verified'
    assert on == off, 'gate comparison changes a second policy field'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bin', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    binary = args.bin.resolve(strict=True)
    out = args.out.resolve()
    if ROOT in out.parents and (ROOT / 'bench-output') not in out.parents:
        raise ValueError('output inside artifact must be beneath bench-output/')
    out.mkdir(parents=True, exist_ok=False)
    freezes = verify_freezes()
    study = ROOT / 'real-agent-eval/v5'
    records = study / 'results/conf'
    e = load('matched_evaluate_v5', study / 'evaluate_v5.py')
    ctx = e.Ctx(SimpleNamespace(bin=str(binary), strict=True,
                accepted_checker=[e.PREREG_CHECKER]),
                e.load_captures(records / 'captures.jsonl'),
                e.load_checks(records / 'checks.jsonl'), {})
    ctx.rdir = out / 'rust'
    items = e.load_items(study / 'benchmark/items_confirmatory.jsonl')
    with (records / 'eval/paired_decisions_v5.csv').open() as f:
        reference = {r['id']: r for r in csv.DictReader(f)}
    rows = []
    for iid, ref in reference.items():
        rec = e.prepare_item(items[iid], e.jload(records / 'raw' / (iid + '.json')), ctx)
        assert rec['row']['eligible']
        row = {'id': iid, 'set': e.analysis_set(items[iid], strict=True),
               'decisive': rec['row']['decisive']}
        e.python_methods(rec, ctx, e.PREREG_BEST)
        row['MAJ'] = rec['row']['MAJ']
        row['MAJ_obj'] = rec['row']['MAJ_obj']
        runs = {}
        for cfg in CONFIGS:
            runs[cfg] = e.reduce_method(rec, 'BE', cfg, ctx, cfg.replace('/', '_'))
            row[cfg] = runs[cfg]['correct']
            row[cfg + '_obj'] = runs[cfg]['obj']
        for factor in ('0.1', '0.5'):
            off = runs['member/nei' + factor]
            on = runs['member/nei' + factor + '/gated']
            assert_matched(off['inp']['policy'], on['inp']['policy'])
            # The entire remaining input (including labels) is identical.
            off_input, on_input = copy.deepcopy(off['inp']), copy.deepcopy(on['inp'])
            off_input.pop('policy'); on_input.pop('policy')
            assert off_input == on_input
            gate = (on['sel'] or {}).get('gate')
            d = rec['by_id'][gate['default_winner']] if gate else None
            default = (int(d['correct']), d['parsed']) if d else (row['MAJ'], row['MAJ_obj'])
            row['D' + factor], row['D' + factor + '_obj'] = default
        row['D'], row['D_obj'] = row['D0.5'], row['D0.5_obj']
        for new, old in [('MAJ', 'MAJ'), ('D', 'D'),
                         ('member/nei0.1', 'BE'), ('member/nei0.5/gated', 'BE-G')]:
            assert row[new] == int(ref[old]), (iid, new, 'correctness differs from archive')
            assert row[new + '_obj'] == ref[old + '_obj'], (iid, new, 'answer differs from archive')
        rows.append(row)
    with (out / 'decisions.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    results = {}
    for subset in ('P', 'T'):
        selected = [r for r in rows if r['set'] == subset and r['decisive']]
        results[subset] = {cfg: {base: summary(selected, cfg, base) for base in ('MAJ', 'D', 'D0.1', 'D0.5')}
                           for cfg in CONFIGS}
        results[subset]['gate_vs_ungated'] = {
            factor: summary(selected, 'member/nei' + factor + '/gated', 'member/nei' + factor)
            for factor in ('0.1', '0.5')}
    receipt = {'analysis': 'post hoc matched gate ablation; not a new confirmatory test',
               'binary_sha256': digest(binary), 'evaluator_sha256': digest(study / 'evaluate_v5.py'),
               'verified_freeze_entries': freezes, 'archived_items_matched': len(rows),
               'rust_python_mirror_checks': ctx.counts['mirror_checked'],
               'same_inputs_and_non_gate_policy_fields': True,
               'results': results}
    (out / 'results.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
