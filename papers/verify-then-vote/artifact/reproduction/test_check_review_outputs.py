"""Published reviewer results must not drift behind passing helper tests."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from check_review_outputs import PACKET_FILES, PUBLISHED, check_outputs


class ReviewOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.matched = self.root / 'matched'
        self.matched.mkdir()
        self.receipt = self.matched / 'results.json'
        shutil.copyfile(PUBLISHED / 'matched_gate_results.json', self.receipt)
        self.audit = self.root / 'audit'
        self.audit.mkdir()
        for name in PACKET_FILES:
            shutil.copyfile(PUBLISHED / 'calibration_audit' / name, self.audit / name)

    def test_only_native_binary_identity_can_differ(self):
        data = json.loads(self.receipt.read_text())
        data['binary_sha256'] = '0' * 64
        self.receipt.write_text(json.dumps(data))
        check_outputs(self.matched, self.audit)
        data['rust_python_mirror_checks'] -= 1
        self.receipt.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'outside binary_sha256'):
            check_outputs(self.matched, self.audit)

    def test_each_packet_file_is_byte_exact(self):
        for name in PACKET_FILES:
            with self.subTest(name=name):
                path = self.audit / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                with self.assertRaisesRegex(ValueError, name):
                    check_outputs(self.matched, self.audit)
                path.write_bytes(original)

    def test_missing_receipt_identity_is_rejected(self):
        data = json.loads(self.receipt.read_text())
        del data['binary_sha256']
        self.receipt.write_text(json.dumps(data))
        with self.assertRaises(KeyError):
            check_outputs(self.matched, self.audit)
