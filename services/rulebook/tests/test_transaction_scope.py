"""Writes are committed before the response is sent (no race with the next request)."""

from __future__ import annotations

import typing

import pytest


@pytest.mark.parametrize("module", ["rulebook.deps", "review_desk.deps"])
def test_transactions_commit_before_the_response(module: str) -> None:
    import importlib

    deps = importlib.import_module(module)
    (dependency,) = [m for m in typing.get_args(deps.Tx)[1:] if hasattr(m, "dependency")]
    assert dependency.dependency is deps.transaction
    assert dependency.scope == "function"
