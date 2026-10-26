# Copyright 2026 Cloudsmith Ltd
"""Send one usage event with a plain POST.

The session is built on the main thread: no user headers, no client
certificate, no retries, the CLI's proxy and CA settings only. The thread
only POSTs; the caller records failures.
"""

import json
import threading
import time

from . import settings

REQUEST_TIMEOUT_SECONDS = 2.0
#: Below this much budget a POST rarely finishes, and a timeout would start
#: the 24 h backoff, so nothing is sent.
MIN_SEND_SECONDS = 0.25
USER_AGENT = "cloudsmith-cli-telemetry"
_CAPTURE_PATH = "/i/v0/e/"


def _post(session, url, body, timeout):
    # A followed 307/308 would re-POST the event and key to another host.
    response = session.post(
        url,
        data=body,
        timeout=timeout,
        headers={"Content-Type": "application/json"},
        allow_redirects=False,
    )
    return 200 <= response.status_code < 300


def _no_auth(request):
    return request


def _session():
    from ..session import create_requests_session, get_default_proxy

    session = create_requests_session(
        retries=0,
        ssl_verify=True,
        proxy=get_default_proxy(),
        user_agent=USER_AGENT,
    )
    session.cert = None  # never present the user's API client certificate
    # Any session auth stops requests adding ~/.netrc credentials; a no-op
    # keeps trust_env (proxy and CA bundle env vars) working.
    session.auth = _no_auth
    return session


def send(payload):
    """POST ``payload`` within the shared wait budget.

    Returns None without any session, thread or request when less than
    ``MIN_SEND_SECONDS`` of the budget is left. Otherwise returns True only if the POST finished with a
    2xx within the budget, else False.
    """
    from ..telemetry_common import WaitBudget

    budget = WaitBudget.shared()
    if budget.remaining() < MIN_SEND_SECONDS:
        return None

    body = json.dumps({**payload, "api_key": settings.project_key()})
    url = settings.host() + _CAPTURE_PATH
    session = _session()  # imports requests on the main thread
    result = {"ok": False}

    def target():
        try:
            result["ok"] = bool(_post(session, url, body, REQUEST_TIMEOUT_SECONDS))
        except Exception:  # pylint: disable=broad-exception-caught
            result["ok"] = False

    thread = threading.Thread(target=target, name="cloudsmith-usage", daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(budget.remaining())
    budget.spend(time.monotonic() - started)
    return (not thread.is_alive()) and result["ok"]


def log(payload):
    """Print the event to stderr instead of sending it (log mode)."""
    import click

    click.echo(
        "[telemetry] would send (log mode, nothing sent):\n"
        + json.dumps(payload, indent=2, sort_keys=True),
        err=True,
    )
