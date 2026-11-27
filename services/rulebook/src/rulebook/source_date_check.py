"""CI guard: a commit that changes the golden set must also advance SOURCE_DATE.

For every commit in ``base..head`` that modifies a guarded file (the golden-set CSV or its
groups file), the ``SOURCE_DATE`` in the settings file must be later than in the commit's
parent. Otherwise the catalogs would change while ``last-modified`` stayed the same.

Commits made before the settings file existed (in both the commit and its parent) are
skipped: there was no SOURCE_DATE to bump yet.
"""

from __future__ import annotations

import subprocess
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

GOLDEN_DIR = "data/golden"


@dataclass(frozen=True)
class GoldenSet:
    name: str

    @property
    def guarded(self) -> tuple[str, ...]:
        return (f"{GOLDEN_DIR}/{self.name}.csv", f"{GOLDEN_DIR}/{self.name}.groups.csv")

    @property
    def settings(self) -> str:
        return f"{GOLDEN_DIR}/{self.name}.settings.toml"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _source_date(repo: Path, rev: str, path: str) -> datetime | None:
    """SOURCE_DATE in ``path`` at ``rev``; None if the file does not exist there."""
    try:
        text = _git(repo, "show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None
    return datetime.fromisoformat(str(tomllib.loads(text)["SOURCE_DATE"]))


def _parent(repo: Path, commit: str) -> str | None:
    parents = _git(repo, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    return parents[0] if parents else None


def check(repo: Path, base: str | None, head: str, golden: GoldenSet) -> list[str]:
    """Return one problem per offending commit in ``base..head`` (oldest first)."""
    rev_range = f"{base}..{head}" if base else head
    commits = _git(repo, "rev-list", "--reverse", rev_range).split()
    problems: list[str] = []
    for commit in commits:
        listing = _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", commit)
        changed = set(listing.splitlines())
        touched = sorted(changed.intersection(golden.guarded))
        if not touched:
            continue
        parent = _parent(repo, commit)
        before = _source_date(repo, parent, golden.settings) if parent else None
        after = _source_date(repo, commit, golden.settings)
        if after is None and before is None:
            continue  # predates SOURCE_DATE
        if after is None:
            problems.append(f"{commit[:12]}: {golden.settings} was deleted")
        elif before is not None and after <= before:
            subject = _git(repo, "log", "-1", "--format=%s", commit).strip()
            problems.append(
                f"{commit[:12]} ({subject}): changes {', '.join(touched)} but SOURCE_DATE "
                f"in {golden.settings} was not advanced (still {before.isoformat()})"
            )
    return problems


def main(repo: Path, base: str | None, head: str, names: Sequence[str]) -> int:
    problems = [p for name in names for p in check(repo, base, head, GoldenSet(name))]
    for problem in problems:
        print(problem)
    if not problems:
        print(f"SOURCE_DATE check passed for {base or '(root)'}..{head}")
    return 1 if problems else 0
