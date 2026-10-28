# Copyright 2026 Cloudsmith Ltd
"""Smoke-test an installed cloudsmith-cli, normally the wheel in a clean venv.

Run it with the interpreter of the environment under test and ``-I`` so the
checkout is not importable by accident:

    python -I .github/scripts/smoke_installed.py --pyproject pyproject.toml

It catches the release-breaking classes that a test run against the locked
development environment cannot:

* a dependency declared in ``pyproject.toml`` but missing from the wheel
  metadata (``--pyproject``);
* package data (``VERSION``, ``config.ini``, ``credentials.ini``, templates)
  missing from the install;
* any module under ``cloudsmith_cli`` failing to import (lazy command modules
  and optional extras included);
* ``--help`` of the root command, or of any command or subcommand, failing or
  printing a traceback;
* the console scripts and ``python -m cloudsmith_cli`` failing to start;
* an API failure (here: connection refused) surfacing as a raw traceback
  instead of a controlled error and a non-zero exit code.

Exit status is 0 when every check passes. Every failure is listed.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.metadata
import importlib.resources
import os
import pathlib
import pkgutil
import re
import shutil
import subprocess
import sys
import sysconfig
import tomllib

DIST = "cloudsmith-cli"
PACKAGE = "cloudsmith_cli"
DATA_FILES = (
    "data/VERSION",
    "data/config.ini",
    "data/credentials.ini",
    "templates/auth_error.html",
    "templates/auth_success.html",
    "templates/auth_two_factor.html",
)

# Distributions the source imports without declaring them, each guaranteed by a
# declared distribution. botocore always ships with boto3. httpx2 is imported
# directly by core/mcp/server.py and arrives only through mcp: it should be
# declared in pyproject.toml, and this entry can then be removed.
IMPORTED_VIA = {"botocore": "boto3", "httpx2": "mcp"}

failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)
    print(f"FAIL: {message}")


def normalise_requirement(requirement: str) -> tuple[str, frozenset[str]]:
    """Reduce a requirement to (name[extras], specifiers) for comparison."""
    requirement = requirement.split(";", 1)[0].strip()
    match = re.match(
        r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)", requirement
    )
    if not match:
        return requirement, frozenset()
    name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
    extras = ",".join(
        sorted(e.strip() for e in (match.group(2) or "")[1:-1].split(","))
    )
    specs = frozenset(
        s.strip().replace(" ", "") for s in match.group(3).split(",") if s.strip()
    )
    return f"{name}[{extras}]" if extras else name, specs


def check_metadata(pyproject: pathlib.Path | None) -> None:
    requires = importlib.metadata.requires(DIST) or []
    declared_in_wheel = {
        normalise_requirement(r) for r in requires if "extra ==" not in r
    }
    if not declared_in_wheel:
        fail("installed metadata declares no dependencies at all")
    if pyproject is None:
        return
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    expected = {normalise_requirement(r) for r in project["dependencies"]}
    for name, specs in sorted(expected - declared_in_wheel, key=str):
        fail(
            f"pyproject dependency {name} {sorted(specs)} missing from installed metadata"
        )
    for name, specs in sorted(declared_in_wheel - expected, key=str):
        fail(
            f"installed metadata has {name} {sorted(specs)} that pyproject does not declare"
        )
    extras_in_wheel = set(
        importlib.metadata.metadata(DIST).get_all("Provides-Extra") or []
    )
    extras_expected = set(project.get("optional-dependencies", {}))
    if extras_in_wheel != extras_expected:
        fail(
            f"extras differ: installed {sorted(extras_in_wheel)} vs pyproject {sorted(extras_expected)}"
        )
    for extra, items in project.get("optional-dependencies", {}).items():
        wheel_items = {
            normalise_requirement(r.split(";", 1)[0])
            for r in requires
            if re.search(rf"extra\s*==\s*['\"]{re.escape(extra)}['\"]", r)
        }
        if {normalise_requirement(i) for i in items} != wheel_items:
            fail(
                f"extra [{extra}] requirements differ between pyproject and installed metadata"
            )
    scripts = {
        e.name
        for e in importlib.metadata.entry_points(group="console_scripts")
        if e.dist and e.dist.name == DIST
    }
    if scripts != set(project["scripts"]):
        fail(
            f"console scripts differ: installed {sorted(scripts)} vs pyproject {sorted(project['scripts'])}"
        )


def check_install_location(allow_source: bool) -> None:
    location = pathlib.Path(importlib.import_module(PACKAGE).__file__).resolve()
    if not allow_source and "site-packages" not in location.parts:
        fail(
            f"{PACKAGE} imported from {location}, not from site-packages: not testing the wheel"
        )


def check_declared_imports() -> None:
    """Every import in the package must come from the stdlib or a declared dependency.

    Importing the modules only runs module-level imports, so an import inside
    a function (or behind a guard) of something that is only in the lock file
    or a dev group would pass everything else and fail for a customer at run
    time. This reads the source instead. Run it where the extras are
    installed, so that every declared distribution can be mapped to modules.
    """
    declared = {
        normalise_requirement(r)[0].split("[")[0]
        for r in importlib.metadata.requires(DIST) or []
    }
    owners = importlib.metadata.packages_distributions()
    package_dir = pathlib.Path(importlib.import_module(PACKAGE).__file__).parent
    checked = 0
    for path in sorted(package_dir.rglob("*.py")):
        relative = path.relative_to(package_dir)
        if "tests" in relative.parts or path.name == "conftest.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        type_checking_lines = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and (
                (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING")
                or (
                    isinstance(node.test, ast.Attribute)
                    and node.test.attr == "TYPE_CHECKING"
                )
            ):
                for child in node.body:
                    type_checking_lines.update(
                        range(child.lineno, (child.end_lineno or child.lineno) + 1)
                    )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            if node.lineno in type_checking_lines:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top in sys.stdlib_module_names or top == PACKAGE:
                    continue
                dists = {re.sub(r"[-_.]+", "-", d).lower() for d in owners.get(top, [])}
                via = {IMPORTED_VIA[d] for d in dists if d in IMPORTED_VIA}
                if not dists & declared and not via & declared:
                    fail(
                        f"{relative}:{node.lineno} imports {module!r}, provided by "
                        f"{sorted(dists) or 'no installed distribution'}, which cloudsmith-cli does not declare"
                    )
        checked += 1
    print(f"checked declared imports in {checked} source files")


def release(version: str) -> tuple[str, ...]:
    """Compare versions without trailing zero parts: 8.2 equals 8.2.0."""
    parts = version.split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return tuple(parts)


def check_floors(pyproject: pathlib.Path) -> None:
    """Fail if a ``>=`` floor was not the version that got installed.

    Guards the lowest-direct run: if the resolver quietly picked newer
    versions, the run proves nothing about the floors.
    """
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    requirements = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        requirements += extra
    for requirement in requirements:
        name, specs = normalise_requirement(requirement)
        if "[" in name:
            # The resolver may pick a newer release to satisfy the extra's own
            # requirements (boto3[crt]), so the floor is not informative.
            continue
        floor = next((s[2:] for s in specs if s.startswith(">=")), None) or next(
            (s[2:] for s in specs if s.startswith("==")), None
        )
        if floor is None:
            continue
        installed = importlib.metadata.version(name.split("[")[0])
        if release(installed) != release(floor):
            fail(f"{name}: expected the floor {floor}, installed {installed}")


def check_package_data() -> None:
    root = importlib.resources.files(PACKAGE)
    for relative in DATA_FILES:
        resource = root.joinpath(relative)
        if not resource.is_file() or not resource.read_bytes().strip():
            fail(f"package data missing or empty: {relative}")
    version = root.joinpath("data/VERSION").read_text(encoding="utf-8").strip()
    installed = importlib.metadata.version(DIST)
    if version != installed:
        fail(
            f"data/VERSION {version!r} differs from installed metadata version {installed!r}"
        )


def check_imports() -> None:
    package = importlib.import_module(PACKAGE)
    names = [PACKAGE]
    for info in pkgutil.walk_packages(
        package.__path__,
        prefix=PACKAGE + ".",
        onerror=lambda n: fail(f"cannot walk {n}"),
    ):
        if ".tests" in info.name or info.name.endswith("conftest"):
            continue
        names.append(info.name)
    for name in names:
        try:
            importlib.import_module(name)
        except BaseException as exc:
            fail(f"import {name}: {type(exc).__name__}: {exc}")
    print(f"imported {len(names)} modules")


def walk_commands(group, ctx, path):
    yield path
    for name in group.list_commands(ctx):
        label = " ".join(path + [name])
        try:
            command = group.get_command(ctx, name)
        except BaseException as exc:  # a lazy command module that fails to import
            fail(f"command {label} cannot be loaded: {type(exc).__name__}: {exc}")
            continue
        if command is None:
            fail(f"command {label} listed but does not resolve")
            continue
        if hasattr(command, "list_commands"):
            sub_ctx = command.make_context(name, [], parent=ctx, resilient_parsing=True)
            yield from walk_commands(command, sub_ctx, path + [name])
        else:
            yield path + [name]


def check_help_everywhere() -> None:
    from click.testing import CliRunner  # pylint: disable=import-outside-toplevel

    from cloudsmith_cli.cli.commands.main import (
        main,  # pylint: disable=import-outside-toplevel
    )

    ctx = main.make_context("cloudsmith", [], resilient_parsing=True)
    paths = list(walk_commands(main, ctx, []))
    runner = CliRunner()
    for path in paths:
        result = runner.invoke(
            main, [*path, "--help"], catch_exceptions=True, prog_name="cloudsmith"
        )
        label = " ".join(["cloudsmith", *path, "--help"])
        if result.exit_code != 0 or result.exception is not None:
            fail(f"{label} exited {result.exit_code} ({result.exception!r})")
        elif "Traceback" in result.output or "Usage:" not in result.output:
            fail(f"{label} printed no usage or a traceback")
    print(f"checked --help for {len(paths)} commands")


def script_path(name: str) -> str | None:
    """Find a console script next to the running interpreter."""
    scripts = sysconfig.get_path("scripts")
    return shutil.which(name, path=scripts)


def run(argv, expect_zero, label, needle=None, extra_env=None):
    env = dict(os.environ, CLOUDSMITH_NO_TELEMETRY="1", PYTHONIOENCODING="utf-8")
    env.update(extra_env or {})
    for key in ("CLOUDSMITH_API_KEY", "CLOUDSMITH_API_HOST"):
        env.pop(key, None)
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
        encoding="utf-8",
    )
    output = proc.stdout + proc.stderr
    if "Traceback (most recent call last)" in output:
        fail(f"{label}: raw traceback\n{output}")
    elif expect_zero and proc.returncode != 0:
        fail(f"{label}: exit {proc.returncode}\n{output}")
    elif not expect_zero and proc.returncode == 0:
        fail(f"{label}: expected a non-zero exit, got 0\n{output}")
    elif needle and needle not in output:
        fail(f"{label}: {needle!r} not in output\n{output}")
    return proc


def check_entry_points() -> None:
    py = sys.executable
    run(
        [py, "-m", PACKAGE, "--help"], True, "python -m cloudsmith_cli --help", "Usage:"
    )
    run([py, "-m", PACKAGE, "--version"], True, "python -m cloudsmith_cli --version")
    cloudsmith = script_path("cloudsmith")
    if cloudsmith is None:
        fail("console script 'cloudsmith' not found next to the interpreter")
    else:
        run([cloudsmith, "--help"], True, "cloudsmith --help", "Usage:")
        run([cloudsmith, "--version"], True, "cloudsmith --version")
        # An API failure must be a controlled error, never a traceback.
        run(
            [
                cloudsmith,
                "whoami",
                "--api-host",
                "http://127.0.0.1:9",
                "--api-key",
                "smoke-test-key",
                "--config-file",
                os.devnull,
                "--credentials-file",
                os.devnull,
                "--error-retry-max",
                "0",
            ],
            False,
            "cloudsmith whoami against a closed port",
        )
        # Wrong usage is exit code 2 from click, not a traceback.
        proc = run([cloudsmith, "no-such-command"], False, "cloudsmith no-such-command")
        if proc.returncode != 2:
            fail(f"cloudsmith no-such-command exited {proc.returncode}, expected 2")
    terraform = script_path("terraform-credentials-cloudsmith")
    if terraform is None:
        fail("console script 'terraform-credentials-cloudsmith' not found")
    else:
        run(
            [terraform, "--help"],
            True,
            "terraform-credentials-cloudsmith --help",
            "Usage:",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--pyproject",
        type=pathlib.Path,
        help="compare installed metadata with this pyproject.toml",
    )
    parser.add_argument(
        "--declared-imports",
        action="store_true",
        help="also check that every import in the source is of a declared dependency (needs all extras installed)",
    )
    parser.add_argument(
        "--expect-floors",
        action="store_true",
        help="also check that every >= floor in --pyproject is the installed version (lowest-direct runs)",
    )
    parser.add_argument(
        "--allow-source",
        action="store_true",
        help="accept an editable or source install (used by the unit suite)",
    )
    args = parser.parse_args()

    check_install_location(args.allow_source)
    check_metadata(args.pyproject)
    check_package_data()
    check_imports()
    check_help_everywhere()
    check_entry_points()
    if args.declared_imports:
        check_declared_imports()
    if args.expect_floors:
        if args.pyproject is None:
            parser.error("--expect-floors needs --pyproject")
        check_floors(args.pyproject)

    if failures:
        print(f"\n{len(failures)} smoke check(s) failed:")
        for message in failures:
            print(f" - {message.splitlines()[0]}")
        return 1
    print("installed package smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
