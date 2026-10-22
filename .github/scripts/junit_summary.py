# Copyright 2026 Cloudsmith Ltd
"""Print a Markdown summary of a pytest JUnit XML report for $GITHUB_STEP_SUMMARY.

Lists passed/failed/skipped counts, every skip reason, and the names of failed
tests. Failure text is left out on purpose: live API output can end up in it,
and the job log already has the details. Always exits 0 so the summary never
changes the job result.

Usage: python junit_summary.py <report.xml> <title>
"""

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

path, title = sys.argv[1], sys.argv[2]
print(f"### {title}\n")

try:
    root = ET.parse(path).getroot()
except (OSError, ET.ParseError) as exc:
    print(f"No test report at `{path}` ({exc.__class__.__name__}).")
    raise SystemExit(0)

counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
failed = []
skip_reasons = defaultdict(list)
for case in root.iter("testcase"):
    name = f"{case.get('classname')}.{case.get('name')}"
    if case.find("failure") is not None:
        counts["failed"] += 1
        failed.append(name)
    elif case.find("error") is not None:
        counts["errors"] += 1
        failed.append(name)
    elif (skipped := case.find("skipped")) is not None:
        counts["skipped"] += 1
        skip_reasons[skipped.get("message") or "no reason given"].append(name)
    else:
        counts["passed"] += 1

print("| " + " | ".join(counts) + " |")
print("|" + "---|" * len(counts))
print("| " + " | ".join(str(n) for n in counts.values()) + " |")

if failed:
    print("\n**Failed or errored:**\n")
    for name in failed:
        print(f"- `{name}`")

if skip_reasons:
    print("\n**Skipped:**\n")
    for reason, names in sorted(skip_reasons.items()):
        print(f"- {reason} ({len(names)})")
        for name in names:
            print(f"  - `{name}`")
