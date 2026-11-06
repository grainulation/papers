"""Integrity checks for the portable reconstruction preflight (stdlib unittest)."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("portable", Path(__file__).with_name("portable.py"))
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "FROZEN_REDACTIONS.md").write_text("")
        for version in (4, 5, 6):
            folder = self.root / f"real-agent-eval/v{version}"
            folder.mkdir(parents=True)
            (folder / "input.txt").write_text("original")
            name = "input.txt" if version == 4 else f"real-agent-eval/v{version}/input.txt"
            freeze = {"status": "FROZEN", "sha256": {name: hashlib.sha256(b"original").hexdigest()}}
            if version == 4:
                (folder / "frozen-bin").mkdir()
                (folder / "frozen-bin/bran-v4-eval").write_bytes(b"binary")
                freeze["binary"] = {"sha256": hashlib.sha256(b"binary").hexdigest()}
            (folder / "FREEZE.json").write_text(json.dumps(freeze))

    def test_unchanged_files_pass(self):
        self.assertEqual(portable.verify_freezes(self.root), {"v4": 1, "v5": 1, "v6": 1})

    def test_undocumented_mutation_fails(self):
        (self.root / "real-agent-eval/v6/input.txt").write_text("changed")
        with self.assertRaisesRegex(ValueError, "frozen hash mismatch"):
            portable.verify_freezes(self.root)

    def test_redaction_requires_both_original_and_published_hash(self):
        name = "real-agent-eval/v5/input.txt"
        (self.root / name).write_text("published")
        old = hashlib.sha256(b"original").hexdigest()
        new = hashlib.sha256(b"published").hexdigest()
        table = self.root / "FROZEN_REDACTIONS.md"
        table.write_text(f"| `{name}` | `{'0' * 64}` | `{new}` |\n")
        with self.assertRaises(ValueError):
            portable.verify_freezes(self.root)
        table.write_text(f"| `{name}` | `{old}` | `{new}` |\n")
        portable.verify_freezes(self.root)


class StatisticsTests(unittest.TestCase):
    def test_changed_statistic_fails(self):
        with self.assertRaisesRegex(ValueError, "statistics differ"):
            portable.compare_statistics({"H1a": {"b": 91}}, {"H1a": {"b": 90}})

    def test_missing_statistic_fails(self):
        with self.assertRaisesRegex(ValueError, "statistics keys differ"):
            portable.compare_statistics({"H1a": {"b": 91}}, {})

    def test_roundoff_allowed_but_effect_change_rejected(self):
        portable.compare_statistics({"p": 0.014328896302250805}, {"p": 0.014328896302250814})
        with self.assertRaises(ValueError):
            portable.compare_statistics({"p": 0.02}, {"p": 0.03})

    def test_tiny_p_value_cannot_be_zeroed(self):
        with self.assertRaises(ValueError):
            portable.compare_statistics({"p": 3.5e-16}, {"p": 0.0})

    def test_boolean_cannot_replace_count(self):
        with self.assertRaises(ValueError):
            portable.compare_statistics({"n": 1}, {"n": True})

    def test_missing_result_files_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                portable.compare_results(portable.ROOT / "real-agent-eval/v5", Path(directory))


if __name__ == "__main__":
    unittest.main()
