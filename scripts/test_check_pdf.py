"""Exercise the release check's match, stale-content and fail-closed paths."""

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check_pdf


class PdfConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.published = Path(self.temp.name) / "paper.pdf"
        self.built = Path(self.temp.name) / "main.pdf"
        # Converter behavior is mocked; these fixtures exercise existence checks.
        self.published.write_bytes(b"%PDF-fixture")
        self.built.write_bytes(b"%PDF-fixture")

    def run_check(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return check_pdf.main([str(self.published), str(self.built)])

    @staticmethod
    def extracted(text):
        return subprocess.CompletedProcess([], 0, stdout=text, stderr="")

    def test_whitespace_only_difference_matches(self):
        with patch("check_pdf.subprocess.run", side_effect=[
            self.extracted("Corrected 79 errors.\n\nLosses: 10\f"),
            self.extracted("Corrected 79\terrors. Losses: 10\n"),
        ]) as converter:
            self.assertEqual(self.run_check(), 0)
        self.assertEqual(converter.call_count, 2)
        self.assertEqual(converter.call_args.args[0][:3], ["pdftotext", "-enc", "UTF-8"])

    def test_substantive_differences_rejected(self):
        for changed in ("Losses: 12", "Losses: -10", "losses: 10", "Losses 10"):
            with self.subTest(changed=changed), patch("check_pdf.subprocess.run", side_effect=[
                self.extracted("Losses: 10"), self.extracted(changed),
            ]):
                self.assertEqual(self.run_check(), 1)

    def test_missing_pdf_rejected_before_converter(self):
        self.published.unlink()
        with patch("check_pdf.subprocess.run") as converter:
            self.assertEqual(self.run_check(), 1)
            converter.assert_not_called()

    def test_converter_failures_are_not_matches(self):
        for failure in (
            FileNotFoundError("pdftotext unavailable"),
            subprocess.CalledProcessError(1, "pdftotext", stderr="invalid PDF"),
            subprocess.TimeoutExpired("pdftotext", 60),
        ):
            with self.subTest(failure=failure), patch("check_pdf.subprocess.run", side_effect=failure):
                self.assertEqual(self.run_check(), 1)

    def test_empty_text_rejected_even_if_both_pdfs_empty(self):
        with patch("check_pdf.subprocess.run", return_value=self.extracted("\n\f \t")):
            self.assertEqual(self.run_check(), 1)

    def test_encoded_pdf_text_cannot_hide_workstation_paths(self):
        leaked = '/' + 'Users/' + 'person/project/output.json'
        with patch('check_pdf.subprocess.run', return_value=self.extracted(leaked)):
            self.assertEqual(self.run_check(), 1)


if __name__ == "__main__":
    unittest.main()
