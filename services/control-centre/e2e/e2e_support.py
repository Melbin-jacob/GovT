"""Helpers for the end-to-end demo tests (screenshots, axe scans, timings)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

OUT = Path(os.environ.get("E2E_OUTPUT", "e2e-output"))
AXE_RESULTS: dict[str, dict[str, Any]] = {}
TIMINGS: dict[str, float] = {}


class Recorder:
    """Screenshots, axe scans and the hosts the browser contacted, per test."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url
        self.hosts: set[str] = set()
        self.overhead = 0.0  # seconds spent on screenshots and scans, not in the demo
        self.axe = Axe()
        page.on("request", lambda r: self.hosts.add(urlparse(r.url).netloc))

    def capture(self, name: str) -> None:
        """Full-page screenshot plus an axe scan (all rules); any violation fails."""
        start = time.perf_counter()
        (OUT / "screens").mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=OUT / "screens" / f"{name}.png", full_page=True)
        result = self.axe.run(self.page).response
        (OUT / "axe").mkdir(parents=True, exist_ok=True)
        (OUT / "axe" / f"{name}.json").write_text(json.dumps(result, indent=1), "utf-8")
        violations = result["violations"]
        AXE_RESULTS[name] = {
            "url": self.page.url.removeprefix(self.base_url),
            "violations": len(violations),
            "passes": len(result["passes"]),
            "incomplete": len(result["incomplete"]),
            "inapplicable": len(result["inapplicable"]),
            "rules_violated": sorted(v["id"] for v in violations),
        }
        self.overhead += time.perf_counter() - start
        assert not violations, f"{name}: axe violations {AXE_RESULTS[name]['rules_violated']}"


def hub_token(audience: str, *who: str) -> str:
    """Development keys only: a token for direct API checks (scripts/lib/hub-token.sh:
    GOVHUB_KEYS_DIR locally, else the Compose control-centre container)."""
    import subprocess

    root = Path(__file__).resolve().parents[3]
    command = f". scripts/lib/hub-token.sh; hub_token {audience} {' '.join(who)}"
    out = subprocess.run(  # noqa: S603 - fixed command, development keys only
        ["/bin/bash", "-c", command], cwd=root, check=True, capture_output=True,
                         text=True)  # fmt: skip
    return out.stdout.strip().splitlines()[-1]
