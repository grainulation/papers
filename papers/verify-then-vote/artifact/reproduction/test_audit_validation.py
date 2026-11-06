"""Human review results must never be overwritten by packet regeneration."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ReviewPreservationTests(unittest.TestCase):
    def test_existing_review_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            self.check_existing_review_directory(Path(temp))

    def check_existing_review_directory(self, tmp_path):
        script = Path(__file__).with_name('audit_validation.py')
        output = tmp_path / 'completed-review'
        output.mkdir()
        review = output / 'review_first_pass.jsonl'
        saved = b'{"review_id":"pair-001","reviewer_id":"human-reviewer","rationale":"completed review"}\n'
        review.write_bytes(saved)
        sentinel = output / 'sentinel'
        sentinel.write_bytes(b'keep this too')
        run = subprocess.run([sys.executable, str(script), '--out', str(output)], capture_output=True)
        assert run.returncode != 0
        assert b'FileExistsError' in run.stderr
        assert review.read_bytes() == saved
        assert sentinel.read_bytes() == b'keep this too'
        assert sorted(p.name for p in output.iterdir()) == ['review_first_pass.jsonl', 'sentinel']
