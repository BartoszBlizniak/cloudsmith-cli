import os

import cloudsmith_api
import pytest

from cloudsmith_cli.core import keyring as core_keyring
from cloudsmith_cli.core import session, telemetry

#: A syntactically valid DSN that is never contacted: tests that report use
#: an in-memory transport.
FAKE_DSN = "https://publickey@o0.ingest.sentry.invalid/0"


@pytest.fixture(autouse=True)
def no_real_error_reports(monkeypatch):
    """Never send a real error report from the test suite.

    Tests that exercise reporting opt back in with ``sentry_events``.
    """
    monkeypatch.setenv(telemetry.NO_TELEMETRY_ENV, "1")
    monkeypatch.setenv(telemetry.DSN_ENV, "")
    monkeypatch.setattr(telemetry, "_transport", None)


@pytest.fixture(autouse=True)
def default_keyring_settings():
    """Start each test with the default keyring settings."""
    core_keyring.configure(core_keyring.KeyringSettings())


@pytest.fixture()
def telemetry_config_dir(monkeypatch, tmp_path_factory):
    """An empty config search path, isolated from the developer's config.ini.

    Reporting reads ``telemetry`` from config.ini, so without this a local
    ``telemetry = false`` (or a broken file) would change test outcomes.
    Write a ``config.ini`` into the returned directory to set the key.
    """
    from cloudsmith_cli.cli import config

    path = tmp_path_factory.mktemp("telemetry-config")
    # Basenames only: --config-file paths from earlier tests are inserted into
    # these class-level lists and would otherwise still be read.
    for reader, name in (
        (config.ConfigReader, "config.ini"),
        (config.CredentialsReader, "credentials.ini"),
    ):
        monkeypatch.setattr(reader, "config_files", [name])
        monkeypatch.setattr(reader, "config_searchpath", [str(path)])
    monkeypatch.delenv(telemetry.PROFILE_ENV, raising=False)
    return path


@pytest.fixture()
def sentry_events(monkeypatch, telemetry_config_dir):  # pylint: disable=unused-argument
    """Enable reporting into an in-memory transport; yield the sent events."""
    from sentry_sdk.transport import Transport

    events = []

    class CaptureTransport(Transport):
        def capture_envelope(self, envelope):
            events.extend(
                item.payload.json for item in envelope.items if item.type == "event"
            )

    for name in telemetry.OPT_OUT_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(telemetry.DSN_ENV, FAKE_DSN)
    monkeypatch.setattr(telemetry, "_transport", CaptureTransport())
    return events


@pytest.fixture(autouse=True)
def restore_api_configuration_default():
    """Undo the process-wide SDK configuration a test leaves behind.

    ``initialise_api`` ends in ``Configuration.set_default()``, so a test that
    sets a proxy, host or credential would otherwise hand it to every test that
    runs after it. A fresh ``Configuration`` is a copy of the current default,
    which makes it the snapshot to put back afterwards.
    """
    default = cloudsmith_api.Configuration()
    yield
    cloudsmith_api.Configuration.set_default(default)


@pytest.fixture(autouse=True)
def restore_default_proxy():
    """Clear the process-wide proxy that ``initialise_session`` sets."""
    yield
    session.set_default_proxy(None)


#: CI splits the live integration tests across parallel jobs. Each job sets
#: both variables; a run that sets neither (every local run) is not sharded.
SHARD_INDEX_ENV = "PYTEST_SHARD_INDEX"
SHARD_COUNT_ENV = "PYTEST_SHARD_COUNT"


def shard_of(items, index, count):
    """Return the items that belong to shard ``index`` of ``count`` (0-based).

    Items are dealt out round-robin in node-id order, so the result depends
    only on the set of tests, never on collection order or plugins. Every
    test lands in exactly one shard, including tests added later, which is
    what makes this safer than listing files per job. Neighbouring node ids
    (the parameters of one test, the tests of one file) go to different
    shards, which spreads the slow package tests rather than stacking them.
    """
    ordered = sorted(items, key=lambda item: item.nodeid)
    return [item for position, item in enumerate(ordered) if position % count == index]


def read_shard_settings(environ):
    """Return ``(index, count)`` from the environment, or ``None`` if unset."""
    raw_index = environ.get(SHARD_INDEX_ENV)
    raw_count = environ.get(SHARD_COUNT_ENV)
    if raw_index is None and raw_count is None:
        return None
    if raw_index is None or raw_count is None:
        raise pytest.UsageError(
            f"set both {SHARD_INDEX_ENV} and {SHARD_COUNT_ENV}, or neither"
        )
    try:
        index, count = int(raw_index), int(raw_count)
    except ValueError as exc:
        raise pytest.UsageError(f"shard settings must be integers: {exc}") from exc
    if count < 1 or not 0 <= index < count:
        raise pytest.UsageError(
            f"{SHARD_INDEX_ENV}={index} is outside 0..{count - 1} "
            f"({SHARD_COUNT_ENV}={count})"
        )
    return index, count


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """Keep only this job's share of the tests (after ``-m`` has deselected)."""
    settings = read_shard_settings(os.environ)
    if settings is None:
        return
    mine = set(shard_of(items, *settings))
    kept = [item for item in items if item in mine]
    dropped = [item for item in items if item not in mine]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept
