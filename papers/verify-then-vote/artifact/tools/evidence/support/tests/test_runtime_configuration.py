"""Public runtime names take precedence without breaking archived launch settings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[4]
SETTINGS = (
    ('tools/corpus/build.py', 'CACHE', 'CORPUS_CACHE', str(ROOT / 'corpus-cache')),
    ('tools/evidence/support/check.py', 'DEFAULT_CLAUDE', 'CLAUDE_BIN', 'claude'),
    ('tools/evidence/support/local_check.py', 'OLLAMA_LOG', 'OLLAMA_LOG', 'ollama.log'),
)


class RuntimeConfigurationTests(unittest.TestCase):
    def read_setting(self, source, setting, suffix, values):
        env = os.environ.copy()
        for prefix in ('OVERTURN_', 'BRAN_'):
            env.pop(prefix + suffix, None)
        env.update(values)
        command = (
            'import json, runpy, sys; '
            'module = runpy.run_path(sys.argv[1]); '
            'print(json.dumps(str(module[sys.argv[2]])))'
        )
        run = subprocess.run(
            [sys.executable, '-c', command, str(ROOT / source), setting],
            env=env, capture_output=True, text=True, check=True,
        )
        return json.loads(run.stdout)

    def test_public_names_and_legacy_fallback(self):
        for source, setting, suffix, default in SETTINGS:
            modern, legacy = 'OVERTURN_' + suffix, 'BRAN_' + suffix
            cases = (
                ({}, default),
                ({modern: 'public-setting'}, 'public-setting'),
                ({legacy: 'archived-setting'}, 'archived-setting'),
                ({modern: 'public-setting', legacy: 'archived-setting'}, 'public-setting'),
            )
            for values, expected in cases:
                with self.subTest(setting=setting, configured=values):
                    self.assertEqual(self.read_setting(source, setting, suffix, values), expected)
