import time
from datetime import UTC, datetime
from uuid import uuid4


def random_str():
    """Return a random string."""
    return "cli-test-" + str(uuid4())


def random_bool():
    """Return a random bool."""
    return datetime.now(tz=UTC).microsecond % 2 == 0


def wait_until(predicate, timeout_message, timeout=50.0, interval=1.0):
    """Poll ``predicate`` until it is truthy, checking before the first sleep.

    Live tests wait for asynchronous work (package sync, deletion) on the
    service. Polling every second instead of sleeping a fixed five seconds
    before each check returns as soon as the work is done, and the overall
    limit stays the same: ``timeout`` seconds, then ``TimeoutError``.
    """
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(timeout_message)
        time.sleep(interval)
