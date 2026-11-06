"""Fail-closed acceptance checks for the public v4 reconstruction wrapper."""
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'real-agent-eval/v4/reanalyze.py'
spec = importlib.util.spec_from_file_location('v4_reconstruction_test', SCRIPT)
v4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4)


class V4ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'run'
        self.out.mkdir()
        self.reference = v4.HERE / 'results/conf'

    def copy_outputs(self, amendment=True):
        names = v4.JSON_OUTPUTS + v4.BYTE_OUTPUTS
        if amendment:
            names += ('amendment5_v4.json', 's10_per_item_v4.csv')
        for name in names:
            shutil.copyfile(self.reference / name, self.out / name)

    def mutate_json(self, change):
        path = self.out / 'evaluation_v4.json'
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_empty_and_missing_required_output_fail(self):
        self.assertTrue(v4.compare(self.out))
        self.copy_outputs()
        (self.out / 'paired_decisions_v4.csv').unlink()
        self.assertIn('paired_decisions_v4.csv: required output missing', v4.compare(self.out))

    def test_identical_outputs_pass(self):
        self.copy_outputs()
        self.assertEqual(v4.compare(self.out), [])

    def test_amendment_skip_is_explicit(self):
        self.copy_outputs(amendment=False)
        self.assertEqual(v4.compare(self.out, include_amendment=False), [])
        self.assertTrue(v4.compare(self.out, include_amendment=True))

    def test_exact_runtime_values_can_differ(self):
        self.copy_outputs()
        self.mutate_json(lambda data: data['provenance'].update(binary='different-path', binary_sha256='different-hash'))
        path = self.out / 'amendment5_v4.json'
        data = json.loads(path.read_text())
        data['S10']['M3_time_s']['median'] += 1
        path.write_text(json.dumps(data))
        self.assertEqual(v4.compare(self.out), [])

    def test_scientific_fields_and_missing_runtime_keys_fail(self):
        self.copy_outputs()
        self.mutate_json(lambda data: data.update(wall_accuracy=0.0))
        self.assertTrue(any('wall_accuracy' in d for d in v4.compare(self.out)))
        self.copy_outputs()
        self.mutate_json(lambda data: data['provenance'].pop('binary_sha256'))
        self.assertTrue(any('binary_sha256' in d for d in v4.compare(self.out)))
        self.copy_outputs()
        path = self.out / 'amendment5_v4.json'
        data = json.loads(path.read_text())
        data['H4'] = {'changed_statistic': True}
        path.write_text(json.dumps(data))
        self.assertTrue(any('/H4/' in d for d in v4.compare(self.out)))

    def test_fresh_output_boundary(self):
        artifact = self.root / 'artifact'
        artifact.mkdir()
        with patch.object(v4, 'ARTIFACT', artifact):
            for out in (artifact, artifact / 'real-agent-eval/v5/results/new', artifact / 'bench-output'):
                with self.subTest(out=out), self.assertRaises(ValueError):
                    v4.prepare_output(out)
            new = v4.prepare_output(artifact / 'bench-output/new')
            self.assertTrue(new.is_dir())
            with self.assertRaises(FileExistsError):
                v4.prepare_output(new)
            self.assertTrue(v4.prepare_output(self.root / 'outside').is_dir())

    def test_receipt_failure_and_uncompared_status(self):
        binary = self.root / 'binary'
        binary.write_bytes(b'not-executed')
        for flag, expected in (('--compare', 'failed'), (None, 'completed_not_compared')):
            out = self.root / expected
            args = ['--out', str(out), '--bin', str(binary), '--skip-amendment5']
            if flag:
                args.append(flag)
            with patch.object(v4, 'verify_freeze', return_value=[]), patch.object(v4, 'check_redaction_table'), \
                 patch.object(v4, 'load_evaluator', return_value=SimpleNamespace(main=lambda: 0)), \
                 contextlib.redirect_stdout(io.StringIO()):
                status = v4.main(args)
            receipt = json.loads((out / 'reconstruction.json').read_text())
            self.assertEqual(receipt['status'], expected)
            self.assertEqual(status, 1 if flag else 0)
            self.assertEqual(receipt['binary_sha256'], v4.sha256_file(binary))
            self.assertIn('historical_binary_sha256', receipt)
            self.assertIn('published_binary_sha256', receipt)
            self.assertFalse(receipt['amendment5_included'])


if __name__ == '__main__':
    unittest.main()
