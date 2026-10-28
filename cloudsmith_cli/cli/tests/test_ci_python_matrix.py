"""Keep the CI Python matrix in step with what the package claims to support."""

import pathlib
import re
import tomllib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"
TEST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"

pytestmark = pytest.mark.skipif(
    not PYPROJECT.is_file() or not TEST_WORKFLOW.is_file(),
    reason="not running from a source checkout",
)


def minor(version):
    return tuple(int(part) for part in version.split(".")[:2])


def classifier_minors(project):
    prefix = "Programming Language :: Python :: "
    return {
        minor(c.removeprefix(prefix))
        for c in project["classifiers"]
        if c.startswith(prefix) and re.fullmatch(r"\d+\.\d+", c.removeprefix(prefix))
    }


def workflow_matrix_minors():
    """Minor versions of every ``python-version: [...]`` matrix in test.yml."""
    found = set()
    for line in TEST_WORKFLOW.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*python-version:\s*\[(.*)\]", line)
        if match:
            found |= {minor(v.strip(" '\"")) for v in match.group(1).split(",")}
    return found


def test_every_classified_python_is_tested_on_every_pr():
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert classifier_minors(project) == workflow_matrix_minors()


def test_requires_python_floor_is_the_oldest_tested_python():
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    floor = re.fullmatch(r">=\s*(\d+\.\d+)(\.\d+)?", project["requires-python"])
    assert floor, "requires-python must be a single >= floor"
    assert minor(floor.group(1)) == min(workflow_matrix_minors())
