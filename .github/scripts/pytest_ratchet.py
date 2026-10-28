# Copyright 2026 Cloudsmith Ltd
"""Fail a pytest run only on failures that are not already known.

    python .github/scripts/pytest_ratchet.py reports/junit.xml known-failures.txt

Used where a platform does not pass the whole suite yet (Windows). Every test
still runs and every known failure is still reported; what the check adds is
that a test which passes today cannot start failing unnoticed. Exit status:

* 1 if any test failed or errored that is not listed in the known file, or if
  the JUnit file is missing or empty (a crashed run must not look clean);
* 0 otherwise. Known failures that now pass are reported so they can be
  removed from the list, which only ever shrinks.

The known file has one ``classname::name`` per line; a line that starts with
``#`` is a comment.
"""

from __future__ import annotations

import pathlib
import sys
import xml.etree.ElementTree as ET


def failed_tests(junit: pathlib.Path) -> tuple[set[str], int]:
    """Return the ids of failed/errored tests and the number of tests seen."""
    seen = 0
    failed = set()
    for case in ET.parse(junit).getroot().iter("testcase"):
        seen += 1
        if any(child.tag in ("failure", "error") for child in case):
            failed.add(f"{case.get('classname')}::{case.get('name')}")
    return failed, seen


def known_failures(path: pathlib.Path) -> set[str]:
    # Whole-line comments only: "#" can be part of a test id (`[#]`).
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    junit, known_file = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    if not junit.is_file():
        print(f"ERROR: {junit} does not exist: pytest did not complete")
        return 1
    failed, seen = failed_tests(junit)
    if seen == 0:
        print(f"ERROR: {junit} holds no test results")
        return 1
    known = known_failures(known_file)

    new = sorted(failed - known)
    fixed = sorted(known - failed)
    print(f"{seen} tests, {len(failed)} failed, {len(failed & known)} of them known")
    if fixed:
        print(
            f"\n{len(fixed)} known failure(s) now pass; remove them from {known_file}:"
        )
        for test in fixed:
            print(f"  {test}")
    if new:
        print(f"\nERROR: {len(new)} failure(s) that are not in {known_file}:")
        for test in new:
            print(f"  {test}")
            print(f"::error title=New test failure::{test}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
