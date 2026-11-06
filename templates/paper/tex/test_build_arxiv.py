import gzip
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from build_arxiv import build


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "sections").mkdir()
        (self.root / "main.tex").write_text("manuscript")
        (self.root / "sections/one.tex").write_text("section")
        (self.root / "arxiv-files.txt").write_text("main.tex\nsections/one.tex\n")

    def test_dirty_extras_are_excluded_and_metadata_clean(self):
        for name in ("sections/private-notes.tex", "sections/._one.tex", ".DS_Store"):
            (self.root / name).write_text("private workstation data")
        os.chmod(self.root / "main.tex", 0o777)
        os.utime(self.root / "main.tex", (1700000000, 1700000000))
        try:
            os.setxattr(self.root / "main.tex", "com.apple.provenance", b"private metadata")
        except (AttributeError, OSError):
            pass
        build(self.root)
        with tarfile.open(self.root / "arxiv.tar.gz") as archive:
            self.assertEqual(archive.getnames(), ["main.tex", "sections/one.tex"])
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                self.assertEqual((member.uid, member.gid, member.mtime, member.mode), (0, 0, 0, 0o644))
                self.assertEqual((member.uname, member.gname, member.pax_headers), ("", "", {}))
        raw = (self.root / "arxiv.tar.gz").read_bytes()
        self.assertEqual(raw[3], 0)  # no original filename/comment/extra fields
        self.assertEqual(raw[4:8], b"\0" * 4)
        self.assertNotIn(b"com.apple.provenance", gzip.decompress(raw))

    def test_rebuild_is_byte_identical_after_source_metadata_changes(self):
        build(self.root)
        original = (self.root / "arxiv.tar.gz").read_bytes()
        os.utime(self.root / "main.tex", (1, 1))
        os.chmod(self.root / "main.tex", 0o600)
        build(self.root)
        self.assertEqual(original, (self.root / "arxiv.tar.gz").read_bytes())

    def test_missing_source_fails_without_replacing_archive(self):
        build(self.root)
        original = (self.root / "arxiv.tar.gz").read_bytes()
        (self.root / "main.tex").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            build(self.root)
        self.assertEqual(original, (self.root / "arxiv.tar.gz").read_bytes())

    def test_symlink_source_or_parent_is_rejected(self):
        (self.root / "main.tex").unlink()
        (self.root / "main.tex").symlink_to(self.root / "sections/one.tex")
        with self.assertRaisesRegex(ValueError, "symlink"):
            build(self.root)
        (self.root / "arxiv-files.txt").write_text("alias/one.tex\n")
        (self.root / "alias").symlink_to(self.root / "sections", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            build(self.root)

    def test_unsafe_and_duplicate_manifest_entries_are_rejected(self):
        for content in ("../main.tex", "/main.tex", "./main.tex", "sections/._one.tex", "main.tex\nmain.tex"):
            with self.subTest(content=content):
                (self.root / "arxiv-files.txt").write_text(content)
                with self.assertRaises(ValueError):
                    build(self.root)


if __name__ == "__main__":
    unittest.main()
