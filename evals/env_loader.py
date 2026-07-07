"""Tiny `.env` loader for eval scripts.

`python-dotenv` is deliberately not a project dependency (PLAN.md §4 keeps
the dependency list minimal); this module parses simple `KEY=VALUE` lines
from a `.env` file into `os.environ`, without overriding variables already
set in the real environment (so CI/CD secrets always win over a local file).
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Populate `os.environ` from a simple `.env` file, if present.

    Lines are `KEY=VALUE`; blank lines and lines starting with `#` are
    skipped. Values are not shell-expanded or quote-processed beyond
    stripping a single layer of surrounding quotes. Existing environment
    variables are never overwritten.
    """
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
