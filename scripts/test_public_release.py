import unittest
import tempfile
import subprocess
import contextlib
import io
from pathlib import Path
from check_public_release import inspect, main, redaction_issues
import hashlib


class PublicReleaseTests(unittest.TestCase):
    def test_text_and_binary_paths_are_rejected(self):
        local = b'/' + b'Users/' + b'person/project/data.json'
        self.assertTrue(inspect(Path('result.json'), local))
        self.assertTrue(inspect(Path('binary'), b'\0' + local + b'\0'))

    def test_local_artifact_rejected_without_path_leak(self):
        self.assertTrue(inspect(Path('.claude/settings.local.json'), b'{}'))
        self.assertTrue(inspect(Path('artifact/target/program'), b'ELF'))

    def test_portable_paths_and_research_logs_allowed(self):
        for name, data in [('run.log', b'<artifact>/data.json'),
                           ('README.md', b'python3 tools/reproduce.py'),
                           ('run.json', b'http://localhost:11434')]:
            self.assertEqual(inspect(Path(name), data), [])

    def test_symlink_checks_in_fresh_repository(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            subprocess.run(['git', 'init', '-q', d], check=True)
            (root / 'data.txt').write_text('public data')
            (root / 'good').symlink_to('data.txt')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(main(['--root', d]))
            (root / 'bad').symlink_to('missing.txt')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(main(['--root', d]))
            (root / 'bad').unlink()
            (root / '.claude').mkdir()
            (root / '.claude/settings.local.json').symlink_to('../data.txt')
            subprocess.run(['git', 'add', '-f', '.claude/settings.local.json'], cwd=root, check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(main(['--root', d]))

    def test_published_redaction_hash_is_checked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            artifact = root / 'papers/example/artifact'
            artifact.mkdir(parents=True)
            (artifact / 'data.json').write_text('{}')
            digest = hashlib.sha256(b'{}').hexdigest()
            (artifact / 'FROZEN_REDACTIONS.md').write_text(
                f'| `data.json` | `{ "0" * 64 }` | `{digest}` | metadata only |\n')
            self.assertEqual(redaction_issues(root), [])
            (artifact / 'data.json').write_text('{"changed": true}')
            self.assertEqual(len(redaction_issues(root)), 1)


if __name__ == '__main__':
    unittest.main()
