"""Run the installed-package smoke script from the unit suite.

``.github/scripts/smoke_installed.py`` is what CI runs against the built wheel
in a clean virtualenv. Running it here, against the development install, gives
every contributor, and the Linux and macOS unit jobs, the same import,
``--help`` and entry-point checks, and keeps the script itself from rotting.
"""

import os
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "smoke_installed.py"

pytestmark = [
    pytest.mark.skipif(
        not SCRIPT.is_file() or not (REPO_ROOT / "pyproject.toml").is_file(),
        reason="not running from a source checkout",
    ),
    # Process start-up is slow on Windows runners, and CI runs the same script
    # there in the "Clean-install smoke test on Windows" job.
    pytest.mark.skipif(
        sys.platform == "win32" and bool(os.environ.get("CI")),
        reason="covered by the clean-install job on Windows CI",
    ),
]


def test_installed_package_smoke():
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            "--allow-source",
            "--pyproject",
            str(REPO_ROOT / "pyproject.toml"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
        env={**os.environ, "CLOUDSMITH_NO_TELEMETRY": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
