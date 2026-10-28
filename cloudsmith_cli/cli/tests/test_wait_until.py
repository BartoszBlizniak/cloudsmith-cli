import pytest

from . import utils


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(utils.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(utils.time, "sleep", fake.sleep)
    return fake


def test_returns_without_sleeping_when_already_true(clock):
    utils.wait_until(lambda: True, "never")
    assert clock.sleeps == []


def test_polls_until_the_predicate_turns_true(clock):
    calls = iter([False, False, True])
    utils.wait_until(lambda: next(calls), "never", interval=1.0)
    assert clock.sleeps == [1.0, 1.0]


def test_raises_after_the_timeout(clock):
    with pytest.raises(TimeoutError, match="gave up"):
        utils.wait_until(lambda: False, "gave up", timeout=5.0, interval=1.0)
    assert sum(clock.sleeps) == 5.0
