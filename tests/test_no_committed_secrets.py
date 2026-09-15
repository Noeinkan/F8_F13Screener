"""Guard against committing credentials.

A live TELEGRAM_BOT_TOKEN sat in this repo's public history from 2026-05-31 to
2026-09-15, because config_secret.py was committed once and .gitignore never
listed it. The file's own header said it must never be committed; nothing
checked. This does.

The scan covers the tracked working tree, not the whole history: history is
immutable and already leaked, so failing on it forever would only teach people
to skip the test. What matters is that no *new* credential gets committed.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Split so this file is not itself a match: "<digits>:<35 token chars>".
TELEGRAM_TOKEN_RE = re.compile(r'[0-9]{8,10}' + ':' + r'[A-Za-z0-9_-]{35}')

SECRET_FILENAMES = ('config_secret.py',)

# Files that legitimately show the shape of a secret without holding one.
ALLOWED_PATHS = frozenset({
    'tests/test_no_committed_secrets.py',
    'config_secret.template.py',
})


def _git(*args: str) -> str:
    return subprocess.run(
        ('git', '-C', str(REPO_ROOT)) + args,
        check=True, capture_output=True, text=True,
    ).stdout


def _tracked_files() -> list[str]:
    return [line for line in _git('ls-files', '-z').split('\0') if line]


requires_git = pytest.mark.skipif(
    shutil.which('git') is None or not (REPO_ROOT / '.git').exists(),
    reason='not a git checkout',
)


@requires_git
def test_secret_files_are_not_tracked():
    tracked = set(_tracked_files())
    committed = sorted(name for name in SECRET_FILENAMES if name in tracked)
    assert not committed, (
        f'{committed} is tracked by git. Run `git rm --cached <file>`, confirm '
        'it is listed in .gitignore, and rotate every credential it held.'
    )


@requires_git
def test_secret_files_are_gitignored():
    for name in SECRET_FILENAMES:
        result = subprocess.run(
            ('git', '-C', str(REPO_ROOT), 'check-ignore', '-q', name),
            capture_output=True,
        )
        assert result.returncode == 0, f'{name} is not covered by .gitignore'


@requires_git
def test_no_telegram_token_in_tracked_files():
    offenders = []
    for rel in _tracked_files():
        if rel in ALLOWED_PATHS:
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        if TELEGRAM_TOKEN_RE.search(text):
            offenders.append(rel)
    assert not offenders, (
        f'Telegram bot token found in tracked files: {offenders}. '
        'Revoke the token in BotFather before doing anything else.'
    )
