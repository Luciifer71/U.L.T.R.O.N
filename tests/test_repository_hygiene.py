"""Keep private local inputs ignored without hiding shareable templates or tests."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('git') is None, reason='Git required for ignore-rule checks')
def test_ignore_rules_keep_private_inputs_local_and_source_visible(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    shutil.copyfile(root / '.gitignore', tmp_path / '.gitignore')
    private = ['.env', '.env.local', '.env.production', '.env.backup',
               'nested/.env.local', 'custom.env', 'custom.env.backup',
               'credentials-work.json', 'token-work.json', 'client_secret_demo.json',
               'private.pem', 'local.sqlite3', 'ultron_memory.db-wal',
               'knowledge_base/notes.txt', 'runtime/support/report.zip',
               '.pytest_cache/cache', '.coverage', 'htmlcov/index.html']
    public = ['.env.example', 'tests/test_example.py', 'tests/fixtures/example.json',
              'requirements-test.txt', 'pytest.ini', 'tools/mesh_pub.py']
    for path in private + public:
        result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', path], cwd=tmp_path)
        assert result.returncode == (0 if path in private else 1), path
