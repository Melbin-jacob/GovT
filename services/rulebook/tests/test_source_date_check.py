"""The SOURCE_DATE CI guard, exercised on a throwaway git repository."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rulebook.cli import main

CSV = "data/golden/demo.csv"
GROUPS = "data/golden/demo.groups.csv"
SETTINGS = "data/golden/demo.settings.toml"


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (root / "data" / "golden").mkdir(parents=True)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, message: str, **files: str) -> str:
        for path, content in files.items():
            target = self.root / {"csv": CSV, "groups": GROUPS, "settings": SETTINGS}[path]
            target.write_text(content, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def check(self, base: str | None = None) -> int:
        args = ["check-source-date", "--repo", str(self.root)]
        return main([*args, "--base", base] if base else args)


def _date(day: int) -> str:
    return f'SOURCE_DATE = "2026-11-{day:02d}T00:00:00Z"\n'


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    r = Repo(tmp_path)
    r.commit("csv before SOURCE_DATE existed", csv="a\n")  # allowed: nothing to bump yet
    r.commit("introduce settings", settings=_date(1), csv="a\nb\n")
    return r


def test_history_without_violations_passes(repo: Repo) -> None:
    repo.commit("bump", csv="a\nb\nc\n", settings=_date(2))
    repo.commit("unrelated", groups="g\n", settings=_date(3))
    assert repo.check() == 0


def test_csv_change_without_bump_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    bad = repo.commit("edit csv only", csv="a\nchanged\n")
    assert repo.check() == 1
    out = capsys.readouterr().out
    assert bad[:12] in out
    assert "was not advanced" in out


def test_groups_change_without_bump_fails(repo: Repo) -> None:
    repo.commit("edit groups only", groups="g2\n")
    assert repo.check() == 1


def test_moving_source_date_backwards_fails(repo: Repo) -> None:
    repo.commit("bump", settings=_date(9))
    repo.commit("csv change with an older date", csv="x\n", settings=_date(2))
    assert repo.check() == 1


def test_only_commits_after_base_are_checked(repo: Repo) -> None:
    repo.commit("edit csv only", csv="a\nchanged\n")
    base = repo.commit("bump on its own", settings=_date(5))
    repo.commit("good change", csv="z\n", settings=_date(6))
    assert repo.check() == 1  # whole history still contains the bad commit
    assert repo.check(base) == 0


def test_settings_change_alone_is_fine(repo: Repo) -> None:
    repo.commit("bump only", settings=_date(9))
    assert repo.check() == 0
