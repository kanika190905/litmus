"""Capture screenshots of the running demo (``litmus serve``) with headless Edge/Chrome.

Each screenshot is a deep link into the real UI, which runs a real search before the
capture (see the ?sample=... parameters handled in web/index.html).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots")
BASE = os.environ.get("LITMUS_URL", "http://127.0.0.1:8000/")

SHOTS = {
    "demo_results.png": ("?sample=q6018&store=apps-demo&version=v1&compare=1&open=1", (1600, 1150)),
    "demo_versions.png": ("?sample=q5287&store=apps-demo&version=all&open=0&k=6", (1600, 1000)),
    "demo_v2_regression.png": ("?sample=q5287&store=apps-demo&version=v2&open=1&k=5", (1600, 1000)),
    "demo_history.png": ("?sample=q5287&store=apps-demo&version=all&open=0&k=6&history=d5287", (1600, 1000)),
}


def browser() -> str:
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            return p
    for name in ("chromium", "google-chrome", "microsoft-edge"):
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("no Chromium-based browser found")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    exe = browser()
    for name, (query, (w, h)) in SHOTS.items():
        out = os.path.join(OUT, name)
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--window-size=%d,%d" % (w, h), "--virtual-time-budget=120000",
                        "--screenshot=%s" % out, BASE + query], check=False, timeout=240,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(name, "ok" if os.path.exists(out) else "FAILED")


if __name__ == "__main__":
    main()
