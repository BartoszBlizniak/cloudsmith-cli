# Copyright 2026 Cloudsmith Ltd
"""Build the wheel and exercise it in clean virtualenvs, as a customer gets it.

Tests that run against ``uv sync --locked`` cannot see a dependency that is
declared in ``pyproject.toml`` but missing from the wheel, or one that only the
lock file or a dev group happens to provide. This builds the wheel, checks its
contents, installs it into fresh virtualenvs holding nothing else, and runs
``smoke_installed.py`` there:

* base install, versions pinned to ``uv.lock`` (what a lock bump changes);
* ``[all]`` install (optional extras), versions pinned to ``uv.lock``, which
  also checks that every import in the source is of a declared dependency.

Usage (from the repository root, with ``uv`` on the PATH):

    python .github/scripts/clean_install.py --python 3.14.10
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"


def run(*argv: str, cwd: pathlib.Path = ROOT) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, cwd=cwd, check=True)


def venv_python(venv: pathlib.Path) -> pathlib.Path:
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    return venv / bin_dir / exe


def smoke(
    python: str,
    workdir: pathlib.Path,
    label: str,
    wheel: pathlib.Path,
    constraints: pathlib.Path,
    extra: str,
) -> None:
    print(f"\n=== clean install: {label} ===", flush=True)
    venv = workdir / label
    run("uv", "venv", "--quiet", "--python", python, str(venv))
    py = venv_python(venv)
    run(
        "uv", "pip", "install", "--quiet", "--python", str(py),
        "--constraint", str(constraints), f"{wheel}{extra}",
    )  # fmt: skip
    run("uv", "pip", "check", "--python", str(py))
    # -I: the checkout must not be importable; run from a neutral directory.
    # Where every extra is installed, also check the source only imports what
    # the package declares.
    checks = ["--declared-imports"] if extra else []
    run(
        str(py), "-I", str(SCRIPTS / "smoke_installed.py"),
        "--pyproject", str(ROOT / "pyproject.toml"), *checks,
        cwd=workdir,
    )  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--python", required=True, help="interpreter for the clean venvs, e.g. 3.14.10"
    )
    parser.add_argument(
        "--skip-extras",
        action="store_true",
        help="skip the [all] install (slow where process start-up is slow)",
    )
    args = parser.parse_args()

    dist = ROOT / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    run("uv", "build", "--out-dir", str(dist))
    run(sys.executable, str(SCRIPTS / "check_wheel.py"))
    (wheel,) = dist.glob("*.whl")

    with tempfile.TemporaryDirectory(prefix="clean-install-") as tmp:
        workdir = pathlib.Path(tmp)
        constraints = workdir / "constraints.txt"
        run(
            "uv", "export", "--frozen", "--no-dev", "--no-emit-project",
            "--no-hashes", "--all-extras", "--quiet", "--output-file", str(constraints),
        )  # fmt: skip
        smoke(args.python, workdir, "base", wheel, constraints, "")
        if not args.skip_extras:
            smoke(args.python, workdir, "extras", wheel, constraints, "[all]")
    print("\nclean-install smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
