"""Fail a PyInstaller build when its warning file contains an unknown entry."""

from __future__ import annotations

import argparse
from pathlib import Path


def _load_allowlist(path: Path) -> set[str]:
    modules = set()
    for line in path.read_text().splitlines():
        module = line.strip()
        if module and not module.startswith("#"):
            modules.add(module)
    return modules


def _module_name(line: str) -> str | None:
    prefix = "missing module named "
    if not line.startswith(prefix):
        return None
    module = line.removeprefix(prefix).split(" - imported by ", 1)[0]
    return module.strip("'")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("warning_file", type=Path)
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=Path(__file__).with_name("warnings-allowlist.txt"),
    )
    args = parser.parse_args()

    warning_lines = args.warning_file.read_text().splitlines()
    missing_modules = {
        module for line in warning_lines if (module := _module_name(line))
    }
    allowed = _load_allowlist(args.allowlist)
    unexpected = sorted(missing_modules - allowed)

    if unexpected:
        print("Unexpected PyInstaller missing-module warnings:")
        for module in unexpected:
            print(f"  {module}")
        return 1

    print(f"PyInstaller warnings accepted: {len(missing_modules)} allowlisted modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
