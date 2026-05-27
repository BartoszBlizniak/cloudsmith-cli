"""CLI/Commands - Get an API token."""

import click
import cloudsmith_api
import semver

from ...core.api.rates import get_rate_limits
from ...core.api.status import get_status
from ...core.api.version import get_version as get_api_version_info
from .. import command, decorators, utils
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


@main.group(cls=command.AliasGroup)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@click.pass_context
def check(ctx, opts):  # pylint: disable=unused-argument
    """Check rate limits and service status."""


@check.command(aliases=["limits"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def rates(ctx, opts):
    """Check current API rate limits."""
    use_stderr = utils.should_use_stderr(opts)
    click.echo("Retrieving rate limits ... ", nl=False, err=use_stderr)

    context_msg = "Failed to retrieve status!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            resources_limits = get_rate_limits()

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, resources_limits):
        return

    headers = ["Resource", "Throttled", "Remaining", "Interval (Seconds)", "Reset"]

    rows = []
    for resource, limits in resources_limits.items():
        rows.append(
            [
                click.style(resource, fg="cyan"),
                click.style(
                    "Yes" if limits.throttled else "No",
                    fg="red" if limits.throttled else "green",
                ),
                "%(remaining)s/%(limit)s"
                % {
                    "remaining": click.style(str(limits.remaining), fg="yellow"),
                    "limit": click.style(str(limits.limit), fg="yellow"),
                },
                click.style(str(limits.interval), fg="blue"),
                click.style(str(limits.reset), fg="magenta"),
            ]
        )

    if resources_limits:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    num_results = len(resources_limits)
    list_suffix = "resource%s" % ("s" if num_results != 1 else "")
    utils.pretty_print_list_info(num_results=num_results, suffix=list_suffix)


@check.command(hidden=True, name="keyring-selftest")
@click.pass_context
def keyring_selftest(ctx):
    """Frozen-binary selftest: prove keyring backend resolves and round-trips.

    Hidden — used by CI smoke tests on PyInstaller/PEX scie binaries. The
    CLI's real keyring usage only stores SSO tokens (browser flow, not
    scriptable in CI), so a synthetic set/get/delete round-trip is the
    only non-interactive way to prove the chosen backend actually works
    on each OS (Keychain on macOS, Credential Manager on Windows,
    Secret Service via secretstorage on Linux glibc, file backend or
    graceful failure on Linux musl).
    """
    import keyring as _keyring  # local import: keep CLI startup cheap

    try:
        backend = _keyring.get_keyring()
    except Exception as exc:  # pylint: disable=broad-except
        click.secho(
            f"FAIL: keyring backend resolution: {type(exc).__name__}: {exc}",
            fg="red",
            err=True,
        )
        ctx.exit(2)

    backend_name = type(backend).__module__ + "." + type(backend).__name__
    click.echo(f"backend: {backend_name}")

    service = "cloudsmith-cli-selftest"
    username = "selftest-user"
    sentinel = "selftest-value-pleasant-pirate-quokka"

    try:
        _keyring.set_password(service, username, sentinel)
    except Exception as exc:  # pylint: disable=broad-except
        click.secho(
            f"FAIL: keyring.set_password raised {type(exc).__name__}: {exc}",
            fg="red",
            err=True,
        )
        ctx.exit(3)

    try:
        got = _keyring.get_password(service, username)
    except Exception as exc:  # pylint: disable=broad-except
        click.secho(
            f"FAIL: keyring.get_password raised {type(exc).__name__}: {exc}",
            fg="red",
            err=True,
        )
        ctx.exit(4)

    if got != sentinel:
        click.secho(
            f"FAIL: keyring round-trip mismatch: got {got!r}, want {sentinel!r}",
            fg="red",
            err=True,
        )
        # best-effort cleanup
        try:
            _keyring.delete_password(service, username)
        except Exception:  # pylint: disable=broad-except
            pass
        ctx.exit(5)

    try:
        _keyring.delete_password(service, username)
    except Exception as exc:  # pylint: disable=broad-except
        click.secho(
            f"FAIL: keyring.delete_password raised {type(exc).__name__}: {exc}",
            fg="red",
            err=True,
        )
        ctx.exit(6)

    try:
        after = _keyring.get_password(service, username)
    except Exception:  # pylint: disable=broad-except
        after = None
    if after is not None:
        click.secho(
            f"FAIL: keyring entry not deleted: still returns {after!r}",
            fg="red",
            err=True,
        )
        ctx.exit(7)

    click.secho(f"OK: keyring round-trip succeeded via {backend_name}", fg="green")


@check.command(hidden=True, name="cryptography-selftest")
@click.pass_context
def cryptography_selftest(ctx):
    """Frozen-binary selftest: prove cryptography native module loads and round-trips.

    Hidden — used by CI smoke tests on PyInstaller/PEX scie binaries to confirm
    `cryptography` (pulled transitively via keyring → secretstorage on Linux)
    is collected and its Rust/C extensions load on every supported target.
    Will become a real call site once OIDC / credential-chain work (PRs #275,
    #276) lands.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        click.secho(f"FAIL: cryptography import error: {exc}", fg="red", err=True)
        ctx.exit(2)

    sentinel = b"cloudsmith-cli cryptography selftest"
    try:
        key = Fernet.generate_key()
        token = Fernet(key).encrypt(sentinel)
        decrypted = Fernet(key).decrypt(token)
    except Exception as exc:  # pylint: disable=broad-except
        click.secho(
            f"FAIL: Fernet round-trip raised {type(exc).__name__}: {exc}",
            fg="red",
            err=True,
        )
        ctx.exit(3)

    if decrypted != sentinel:
        click.secho(
            f"FAIL: Fernet round-trip mismatch: got {decrypted!r}, want {sentinel!r}",
            fg="red",
            err=True,
        )
        ctx.exit(4)

    click.secho("OK: cryptography Fernet round-trip succeeded", fg="green")


@check.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def service(ctx, opts):
    """Check the status of the Cloudsmith service."""
    use_stderr = utils.should_use_stderr(opts)
    click.echo("Retrieving service status ... ", nl=False, err=use_stderr)

    context_msg = "Failed to retrieve status!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            status, version = get_status(with_version=True)

    click.secho("OK", fg="green", err=use_stderr)

    config = cloudsmith_api.Configuration()

    data = {
        "endpoint": config.host,
        "status": status,
        "version": version,
    }

    if utils.maybe_print_as_json(opts, data):
        return

    click.echo()
    click.echo(f"The service endpoint is: {click.style(config.host, bold=True)}")
    click.echo(f"The service status is:   {click.style(status, bold=True)}")
    click.echo(
        f"The service version is:  {click.style(version, bold=True)} ",
        nl=False,
    )

    api_version = get_api_version_info()

    if semver.Version.parse(version).compare(api_version) > 0:
        click.secho("(maybe out-of-date)", fg="yellow")

        click.echo()
        click.secho(
            f"The API library used by this CLI tool is built against service version: {click.style(api_version, bold=True)}",
            fg="yellow",
        )
    else:
        click.secho("(up-to-date)", fg="green")

        click.echo()
        click.secho(
            "The API library used by this CLI tool seems to be up-to-date.", fg="green"
        )
