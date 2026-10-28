"""Tests for .github/scripts/pytest_ratchet.py."""

import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "pytest_ratchet.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file(), reason="not running from a source checkout"
)


@pytest.fixture(scope="module")
def ratchet():
    spec = importlib.util.spec_from_file_location("pytest_ratchet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def junit(tmp_path, cases):
    """Write a JUnit file; ``cases`` maps test name to None, 'failure' or 'error'."""
    body = "".join(
        f'<testcase classname="pkg.test_mod" name="{name}">'
        + (f"<{kind}>boom</{kind}>" if kind else "")
        + "</testcase>"
        for name, kind in cases.items()
    )
    path = tmp_path / "junit.xml"
    path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
    return path


def known(tmp_path, *names):
    path = tmp_path / "known.txt"
    path.write_text(
        "# comment\n" + "".join(f"pkg.test_mod::{n}\n" for n in names) + "\n"
    )
    return path


def run(ratchet, junit_path, known_path):
    return ratchet.main(["ratchet", str(junit_path), str(known_path)])


def test_known_failures_pass(ratchet, tmp_path):
    results = junit(tmp_path, {"a": "failure", "b": None})
    assert run(ratchet, results, known(tmp_path, "a")) == 0


def test_a_hash_inside_a_test_id_is_not_a_comment(ratchet, tmp_path):
    results = junit(tmp_path, {"a[#]": "failure"})
    assert run(ratchet, results, known(tmp_path, "a[#]")) == 0


def test_a_new_failure_fails(ratchet, tmp_path, capsys):
    results = junit(tmp_path, {"a": "failure", "b": "error"})
    assert run(ratchet, results, known(tmp_path, "a")) == 1
    assert "pkg.test_mod::b" in capsys.readouterr().out


def test_a_fixed_test_is_reported_but_passes(ratchet, tmp_path, capsys):
    results = junit(tmp_path, {"a": None})
    assert run(ratchet, results, known(tmp_path, "a")) == 0
    assert "now pass" in capsys.readouterr().out


def test_a_missing_or_empty_report_fails(ratchet, tmp_path):
    assert run(ratchet, tmp_path / "missing.xml", known(tmp_path)) == 1
    assert run(ratchet, junit(tmp_path, {}), known(tmp_path)) == 1
