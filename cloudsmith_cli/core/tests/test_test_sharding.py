"""Tests for the CI test sharding hook in ``cloudsmith_cli/conftest.py``."""

import os
import pathlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

from cloudsmith_cli import conftest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def fake_items(count):
    return [
        SimpleNamespace(nodeid=f"tests/test_{n:03d}.py::test") for n in range(count)
    ]


@pytest.mark.parametrize("total", [0, 1, 3, 7, 32])
@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_every_test_is_in_exactly_one_shard(total, count):
    items = fake_items(total)
    seen = []
    for index in range(count):
        seen += [item.nodeid for item in conftest.shard_of(items, index, count)]
    assert sorted(seen) == sorted(item.nodeid for item in items)


def test_shards_do_not_depend_on_collection_order():
    items = fake_items(10)
    forward = {i.nodeid for i in conftest.shard_of(items, 1, 3)}
    backward = {i.nodeid for i in conftest.shard_of(list(reversed(items)), 1, 3)}
    assert forward == backward


def test_neighbouring_tests_go_to_different_shards():
    items = fake_items(6)
    first_three = [
        next(i for i in range(3) if item in conftest.shard_of(items, i, 3))
        for item in items[:3]
    ]
    assert sorted(first_three) == [0, 1, 2]


def test_no_settings_means_no_sharding():
    assert conftest.read_shard_settings({}) is None


def test_settings_are_read():
    env = {conftest.SHARD_INDEX_ENV: "2", conftest.SHARD_COUNT_ENV: "4"}
    assert conftest.read_shard_settings(env) == (2, 4)


@pytest.mark.parametrize(
    "env",
    [
        {conftest.SHARD_INDEX_ENV: "0"},
        {conftest.SHARD_COUNT_ENV: "2"},
        {conftest.SHARD_INDEX_ENV: "x", conftest.SHARD_COUNT_ENV: "2"},
        {conftest.SHARD_INDEX_ENV: "2", conftest.SHARD_COUNT_ENV: "2"},
        {conftest.SHARD_INDEX_ENV: "-1", conftest.SHARD_COUNT_ENV: "2"},
        {conftest.SHARD_INDEX_ENV: "0", conftest.SHARD_COUNT_ENV: "0"},
    ],
)
def test_bad_settings_fail_loudly_instead_of_running_everything(env):
    with pytest.raises(pytest.UsageError):
        conftest.read_shard_settings(env)


def collect(index=None, count=None):
    """Collect the tests of one real test file in a child pytest."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_SHARD")}
    if index is not None:
        env[conftest.SHARD_INDEX_ENV] = str(index)
        env[conftest.SHARD_COUNT_ENV] = str(count)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "cloudsmith_cli/cli/tests/test_org_option.py",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {line for line in result.stdout.splitlines() if "::" in line}


def test_the_hook_partitions_a_real_collection():
    everything = collect()
    assert len(everything) > 3
    shards = [collect(index, 3) for index in range(3)]
    assert set().union(*shards) == everything
    assert sum(len(shard) for shard in shards) == len(everything)
