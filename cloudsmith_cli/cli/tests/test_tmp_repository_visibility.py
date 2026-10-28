"""Tests for the visibility check the ``tmp_repository`` fixture waits on."""

import pytest

from ...core.api.exceptions import ApiException
from . import conftest as cli_conftest


def fake_list(outcome):
    def list_packages(owner, repo, **kwargs):
        assert (owner, repo) == ("acme", "new-repo")
        if isinstance(outcome, Exception):
            raise outcome
        return [], None

    return list_packages


def test_a_readable_repository_is_visible(monkeypatch):
    monkeypatch.setattr(cli_conftest, "list_packages", fake_list(None))
    assert cli_conftest._repository_is_visible("acme", "new-repo")


def test_a_404_means_not_visible_yet(monkeypatch):
    monkeypatch.setattr(
        cli_conftest, "list_packages", fake_list(ApiException(status=404))
    )
    assert not cli_conftest._repository_is_visible("acme", "new-repo")


@pytest.mark.parametrize("status", [401, 403, 500])
def test_any_other_error_is_raised_not_waited_on(monkeypatch, status):
    monkeypatch.setattr(
        cli_conftest, "list_packages", fake_list(ApiException(status=status))
    )
    with pytest.raises(ApiException):
        cli_conftest._repository_is_visible("acme", "new-repo")
