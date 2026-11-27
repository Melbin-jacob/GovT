"""Shared test helpers for the assessment engine."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"
# Every table, truncated before each test (a test checks the list is complete).
TABLES: tuple[str, ...] = ()
