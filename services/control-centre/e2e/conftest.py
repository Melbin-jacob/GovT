"""End-to-end demo tests against a running stack (``make up`` + ``make demo-review``).

Run with ``make demo-ui`` (or ``CONTROL_CENTRE_URL=http://127.0.0.1:8004 uv run pytest
services/control-centre/e2e``). Skipped when ``CONTROL_CENTRE_URL`` is not set, so the
regular ``make test`` never needs a browser. Writes screenshots, axe results and timings
to ``E2E_OUTPUT`` (default ``e2e-output/``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from e2e_support import AXE_RESULTS, OUT, TIMINGS, Recorder
from playwright.sync_api import Browser, sync_playwright

BASE = os.environ.get("CONTROL_CENTRE_URL", "").rstrip("/")


@pytest.fixture(scope="session")
def base_url() -> str:
    if not BASE:
        pytest.skip("CONTROL_CENTRE_URL not set: start the stack and run `make demo-ui`")
    return BASE


@pytest.fixture(scope="session")
def browser(base_url: str) -> Iterator[Browser]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def rec(browser: Browser, base_url: str) -> Iterator[Recorder]:
    context = browser.new_context(
        viewport={"width": 1280, "height": 900}, device_scale_factor=2, base_url=base_url
    )
    page = context.new_page()
    page.set_default_timeout(15_000)
    recorder = Recorder(page, base_url)
    yield recorder
    context.close()
    allowed = {urlparse(base_url).netloc}
    assert recorder.hosts <= allowed, f"the page contacted other hosts: {recorder.hosts}"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not BASE or not (AXE_RESULTS or TIMINGS):
        return
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "axe-summary.json").write_text(json.dumps(AXE_RESULTS, indent=1), "utf-8")
    (OUT / "timing.json").write_text(json.dumps(TIMINGS, indent=1), "utf-8")
    lines = [
        "| Screen | Path | Violations | Passed rules | Needs review | Not applicable |",
        "|---|---|---|---|---|---|",
    ]
    for name, r in sorted(AXE_RESULTS.items()):
        lines.append(
            f"| {name} | `{r['url']}` | {r['violations']} | {r['passes']} | "
            f"{r['incomplete']} | {r['inapplicable']} |"
        )
    lines += ["", "| Run | Seconds |", "|---|---|"]
    lines += [f"| {k} | {v:.1f} |" for k, v in TIMINGS.items()]
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", "utf-8")
