"""Minimal semantic versions (MAJOR.MINOR.PATCH) for catalog versions."""

from __future__ import annotations

import re
from typing import NamedTuple

_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class SemVer(NamedTuple):
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> SemVer:
        match = _SEMVER_RE.match(value)
        if not match:
            raise ValueError(f"{value!r} is not a semantic version (MAJOR.MINOR.PATCH)")
        return cls(*(int(g) for g in match.groups()))

    def next_minor(self) -> SemVer:
        return SemVer(self.major, self.minor + 1, 0)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"
