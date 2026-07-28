"""CLI commands for generating and managing package SBOM metadata."""

from __future__ import annotations

import contextlib
import json

import click
from click.core import ParameterSource

from ...core.api.exceptions import ApiException
from ...core.api.metadata import (
    create_metadata,
    delete_metadata,
    get_metadata,
    list_metadata,
    validate_metadata,
)
from ...core.api.packages import PackageResolutionError, get_package, package_sha256
from ...core.pagination import PageInfo, paginate_results
from ...core.sbom import (
    CLOUDSMITH_SBOM_CONTENT_TYPE,
    SBOM_METADATA_SIZE_LIMIT_HINT,
    SbomError,
    ensure_within_metadata_size,
    generate_sbom as generate_sbom_document,
    normalize_sha256,
    validate_sbom,
)
from ...core.sbom.contracts import (
    DEFAULT_SBOM_FORMAT,
    SBOM_FORMATS,
    SOURCE_TYPE_AUTO,
    SOURCE_TYPES,
    SPDX_JSON,
)
from ...core.sbom.generators import DEFAULT_GENERATOR, GENERATOR_NAMES
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..metadata_common import resolve_metadata_content
from ..utils import maybe_spinner
from .main import main

DEFAULT_IMPORTED_SBOM_SOURCE_IDENTITY = "cli:imported"
TRIVY_GENERATOR = "trivy"

_SBOM_HEADERS = ["Slug", "Format", "Components", "Source identity", "Created"]


class _SbomPageInfo(PageInfo):
    """Report accurate filtered-page counts without changing shared CLI output."""

    def as_dict(self, num_results=None):
        data = super().as_dict(num_results=num_results)
        if num_results is not None and self.is_valid:
            data["page_results_len"] = num_results
        return data


def _echo_action(message, use_stderr):
    """Print an in-progress status message."""
    click.echo(message, nl=False, err=use_stderr)


@contextlib.contextmanager
def _handle_sbom_api_exceptions(ctx, opts, context_msg):
    """Render a standard API error, then exit with the API status.

    Mirrors what ``handle_api_exceptions`` does by default (``ctx.exit(status)``)
    but exits for real: ``AliasGroup.main`` runs Click with
    ``standalone_mode=False``, which turns ``ctx.exit`` into a discarded return
    value, so a failed command would otherwise report success.
    """
    try:
        with handle_api_exceptions(
            ctx,
            opts=opts,
            context_msg=context_msg,
            exit_on_error=False,
            reraise_on_error=True,
        ):
            yield
    except ApiException as exc:
        raise SystemExit(exc.status or 1) from exc


def _write_raw_json(payload: dict, output: str) -> None:
    with click.open_file(output, "w", encoding="utf-8", atomic=output != "-") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _inherit_parent_output_format(ctx, opts) -> None:
    """Keep a parent JSON format unless this command explicitly overrides it."""
    if ctx.get_parameter_source("output_format") is not ParameterSource.DEFAULT:
        return

    parent = ctx.parent
    if parent is not None:
        opts.output = parent.meta.get(
            "sbom_output_format",
            parent.params.get("output_format", opts.output),
        )


def _require_raw_output(ctx, opts) -> None:
    """Reject an explicit --output alongside a JSON output format.

    Only an explicitly-passed --output conflicts: the option defaults to stdout,
    so a defaulted value must not trip the guard.
    """
    if (
        ctx.get_parameter_source("output") is not ParameterSource.DEFAULT
        and opts.output != "pretty"
    ):
        raise click.UsageError(
            "--output cannot be combined with -F/--output-format JSON modes."
        )


def _is_supported_sbom_entry(entry: dict) -> bool:
    """Recognize schema-valid documents attached by the typed SBOM workflow."""
    if entry.get("content_type") != CLOUDSMITH_SBOM_CONTENT_TYPE:
        return False
    content = entry.get("content")
    if not isinstance(content, dict):
        return False
    try:
        validate_sbom(content)
    except SbomError:
        return False
    return True


def _resolve_package_slug(owner: str, repo: str, identifier: str) -> str:
    """Resolve a package to its permanent slug for read operations.

    Reads only need the slug, so they must not require the package to expose a
    digest; only ``add --subject-digest`` verifies one.
    """
    return get_package(owner, repo, identifier)["slug_perm"]


def _optional_package_digest(package: dict) -> str | None:
    """Return the package SHA-256 digest, or None when it exposes none."""
    try:
        return package_sha256(package)
    except PackageResolutionError:
        return None


def _resolve_default_format(ctx, generator: str, sbom_format: str) -> str:
    """Pick a format the selected generator supports when none was requested.

    The default format is not emitted by every generator, so a defaulted format
    follows the generator. An explicitly-passed format is always respected.
    """
    if (
        generator == TRIVY_GENERATOR
        and ctx.get_parameter_source("sbom_format") is ParameterSource.DEFAULT
    ):
        return SPDX_JSON
    return sbom_format


def _sbom_summary(content: dict) -> tuple[str, int]:
    """Return a human format label and component count for an SBOM document."""
    if content.get("bomFormat") == "CycloneDX":
        return f"CycloneDX {content.get('specVersion', '')}".strip(), len(
            content.get("components") or []
        )
    if content.get("spdxVersion"):
        return str(content["spdxVersion"]), len(content.get("packages") or [])
    return "unknown", 0


def _list_sbom_entries(
    package_slug_perm: str,
    *,
    page: int = 1,
    page_size: int = 30,
    page_all: bool = False,
) -> tuple[list[dict], PageInfo | None]:
    """Fetch all metadata, then paginate the filtered SBOM collection.

    The metadata API cannot filter by content type. Narrow to customer metadata
    server-side, then inspect all candidate pages so typed counts and pagination
    remain accurate.
    """
    entries, _ = paginate_results(
        list_metadata,
        page_all=True,
        page=1,
        package_slug_perm=package_slug_perm,
        source_kind="CUSTOM",
    )
    entries = [entry for entry in entries if _is_supported_sbom_entry(entry)]
    if page_all:
        return entries, None

    count = len(entries)
    page_info = _SbomPageInfo()
    page_info.count = count
    page_info.page = page
    page_info.page_size = page_size
    page_info.page_total = max(1, (count + page_size - 1) // page_size)
    start = (page - 1) * page_size
    return entries[start : start + page_size], page_info


def _format_sbom_row(entry):
    """Format an SBOM metadata entry using the established list style."""
    content = entry.get("content")
    sbom_format, components = (
        _sbom_summary(content) if isinstance(content, dict) else ("unknown", 0)
    )
    return [
        click.style(entry.get("slug_perm") or "", fg="cyan"),
        click.style(sbom_format, fg="yellow"),
        click.style(str(components), fg="blue"),
        click.style(entry.get("source_identity") or "", fg="green"),
        entry.get("created_at") or "",
    ]


def _print_sbom_table(opts, entries, page_info=None, page_all=False, no_content=False):
    """Print SBOM metadata as a table with the standard list summary."""
    json_entries = (
        [{k: v for k, v in entry.items() if k != "content"} for entry in entries]
        if no_content
        else list(entries)
    )
    if utils.maybe_print_as_json(
        opts, json_entries, page_info=None if page_all else page_info
    ):
        return

    rows = [
        _format_sbom_row(entry)
        for entry in sorted(entries, key=lambda entry: entry.get("slug_perm") or "")
    ]
    if rows:
        click.echo()
        utils.pretty_print_table(_SBOM_HEADERS, rows)

    click.echo()
    num_results = len(rows)
    total_results = (
        page_info.count if page_info is not None and not page_all else num_results
    )
    list_suffix = f"SBOM{'s' if total_results != 1 else ''}"
    utils.pretty_print_list_info(
        num_results=num_results,
        page_info=None if page_all or not rows else page_info,
        suffix=f"{list_suffix} retrieved" if page_all else f"{list_suffix} visible",
        page_all=page_all,
    )


def _print_sbom_entry(opts, entry):
    """Print a single SBOM entry as a table plus its document, as metadata does."""
    if utils.maybe_print_as_json(opts, entry):
        return

    click.echo()
    utils.pretty_print_table(_SBOM_HEADERS, [_format_sbom_row(entry)])
    click.echo()

    content = entry.get("content")
    if content is not None:
        click.secho("Document:", bold=True)
        click.echo(json.dumps(content, indent=2, sort_keys=True))


@main.group(name="sbom", cls=command.AliasGroup)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.pass_context
def sbom_(ctx, opts):  # pylint: disable=unused-argument
    """
    Generate and manage package software bills of materials.

    Use generate for a local document, add for an existing package, list or get
    to inspect attached SBOMs, and remove to detach one.
    """
    _inherit_parent_output_format(ctx, opts)
    ctx.meta["sbom_output_format"] = opts.output


@sbom_.command(name="generate")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.argument("source")
@click.option(
    "--generator",
    type=click.Choice(GENERATOR_NAMES),
    default=DEFAULT_GENERATOR,
    show_default=True,
    help=(
        "SBOM generator to run. The generator must be installed on PATH. "
        "'auto' selects an installed generator that supports the requested "
        "format."
    ),
)
@click.option(
    "--format",
    "sbom_format",
    type=click.Choice(SBOM_FORMATS),
    default=DEFAULT_SBOM_FORMAT,
    show_default=True,
    help=(
        "SBOM document format and schema version. Defaults to a format the "
        "selected generator supports."
    ),
)
@click.option(
    "--sbom-source-type",
    "source_type",
    type=click.Choice(SOURCE_TYPES),
    default=SOURCE_TYPE_AUTO,
    show_default=True,
    help=(
        "How to interpret SOURCE. 'auto' infers a directory or an image; "
        "'image' scans a local image archive as an image."
    ),
)
@click.option(
    "--output",
    default="-",
    show_default=True,
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Write the raw SBOM document to FILE, or '-' for stdout.",
)
@click.pass_context
def generate_sbom(ctx, opts, source, generator, sbom_format, source_type, output):
    """
    Generate an SBOM for SOURCE using an external generator.

    SOURCE may be a directory, archive, or image understood by the selected
    generator. The generator must be installed on PATH.

    \b
    Examples:
        $ cloudsmith sbom generate . --output sbom.cdx.json
        $ cloudsmith sbom generate image:tag --format spdx-json --output -
    """
    _inherit_parent_output_format(ctx, opts)
    _require_raw_output(ctx, opts)
    sbom_format = _resolve_default_format(ctx, generator, sbom_format)
    try:
        payload = generate_sbom_document(
            source,
            generator=generator,
            output_format=sbom_format,
            source_type=source_type,
        )
    except SbomError as exc:
        raise click.ClickException(str(exc)) from exc
    _write_raw_json(payload, output)


@sbom_.command(name="add")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.option(
    "--file",
    "sbom_file",
    required=True,
    type=click.Path(
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        allow_dash=True,
    ),
    help="CycloneDX 1.6 or SPDX 2.3 JSON file. Use '-' for stdin.",
)
@click.option(
    "--source-identity",
    default=DEFAULT_IMPORTED_SBOM_SOURCE_IDENTITY,
    show_default=True,
    help=(
        "Identifier describing where the SBOM originated. Imported documents "
        "use a neutral identity unless explicitly identified."
    ),
)
@click.option(
    "--subject-digest",
    default=None,
    callback=validators.validate_sha256_digest,
    help="Require this package SHA-256 digest.",
)
@click.pass_context
def add_sbom(
    ctx,
    opts,
    owner_repo_package,
    sbom_file,
    source_identity,
    subject_digest,
):
    """
    Validate and attach a CycloneDX 1.6 or SPDX 2.3 SBOM.

    OWNER/REPO/PACKAGE identifies an existing package. In automation,
    --subject-digest can ensure it resolves to the expected SHA-256 digest.
    Duplicate detection is a client-side, sequential best-effort check;
    concurrent invocations can create duplicate entries.

    \b
    Examples:
        $ cloudsmith sbom add your-org/your-repo/your-pkg --file sbom.json
        $ cloudsmith sbom generate . --output - | \\
            cloudsmith sbom add your-org/your-repo/your-pkg --file -
    """
    _inherit_parent_output_format(ctx, opts)
    owner, repo, identifier = owner_repo_package
    metadata = resolve_metadata_content(
        content_file=sbom_file,
        inline_content=None,
        required=True,
        file_option_name="--file",
        content_option_name="--content",
    )
    try:
        payload = metadata.content
        assert payload is not None
        validate_sbom(payload)
        ensure_within_metadata_size(payload, source_identity)
    except SbomError as exc:
        raise click.ClickException(str(exc)) from exc

    use_stderr = utils.should_use_stderr(opts)
    _echo_action(
        "Attaching SBOM to %(package)s ... "
        % {"package": click.style(identifier, bold=True)},
        use_stderr,
    )

    with _handle_sbom_api_exceptions(ctx, opts, "Could not attach SBOM."):
        with maybe_spinner(opts):
            package = get_package(owner, repo, identifier)
            digest = _optional_package_digest(package)
            if subject_digest:
                if digest is None:
                    raise click.ClickException(
                        "Package exposes no SHA-256 digest to verify "
                        "--subject-digest against."
                    )
                if normalize_sha256(subject_digest) != digest:
                    raise click.ClickException(
                        "--subject-digest does not match the resolved package digest."
                    )
            entries, _ = paginate_results(
                list_metadata,
                page_all=True,
                page=1,
                package_slug_perm=package["slug_perm"],
                source_kind="CUSTOM",
            )
            entry = next(
                (
                    item
                    for item in entries
                    if item.get("content") == payload
                    and item.get("content_type") == CLOUDSMITH_SBOM_CONTENT_TYPE
                    and item.get("source_identity") == source_identity
                ),
                None,
            )
            created = entry is None
            if created:
                try:
                    validate_metadata(
                        content=payload,
                        content_type=CLOUDSMITH_SBOM_CONTENT_TYPE,
                    )
                    entry = create_metadata(
                        package["slug_perm"],
                        content=payload,
                        content_type=CLOUDSMITH_SBOM_CONTENT_TYPE,
                        source_identity=source_identity,
                    )
                except ApiException as exc:
                    if getattr(exc, "status", None) == 413:
                        raise click.ClickException(
                            f"Could not attach SBOM. {SBOM_METADATA_SIZE_LIMIT_HINT}"
                        ) from exc
                    raise

    click.secho("OK", fg="green", err=use_stderr)

    result = {"created": created, "metadata": entry, "package_sha256": digest}
    if not utils.maybe_print_as_json(opts, result):
        action = "attached as" if created else "already exists as"
        click.echo()
        click.secho(f"SBOM {action} {entry.get('slug_perm', 'metadata')}", fg="green")
        if digest:
            click.echo(f"Package SHA-256: {digest}")


@sbom_.command(name="list", aliases=["ls"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_cli_list_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.option(
    "--no-content",
    is_flag=True,
    default=False,
    help="Omit the full SBOM document from JSON output; list identifiers only.",
)
@click.pass_context
def list_sboms(ctx, opts, owner_repo_package, page, page_size, page_all, no_content):
    """
    List SBOM metadata attached to a package.

    \b
    Examples:
        $ cloudsmith sbom list your-org/your-repo/your-pkg
        $ cloudsmith sbom list your-org/your-repo/your-pkg --no-content -F json
    """
    _inherit_parent_output_format(ctx, opts)
    owner, repo, identifier = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)
    _echo_action(
        "Listing SBOMs for %(package)s ... "
        % {"package": click.style(identifier, bold=True)},
        use_stderr,
    )

    with _handle_sbom_api_exceptions(ctx, opts, "Could not list SBOMs."):
        with maybe_spinner(opts):
            slug_perm = _resolve_package_slug(owner, repo, identifier)
            entries, page_info = _list_sbom_entries(
                slug_perm,
                page=page,
                page_size=page_size,
                page_all=page_all,
            )

    click.secho("OK", fg="green", err=use_stderr)
    _print_sbom_table(
        opts, entries, page_info=page_info, page_all=page_all, no_content=no_content
    )


@sbom_.command(name="get")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.argument("metadata_slug_perm")
@click.option(
    "--output",
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Write the raw SBOM document to FILE, or '-' for stdout.",
)
@click.pass_context
def get_sbom(ctx, opts, owner_repo_package, metadata_slug_perm, output):
    """
    Retrieve one SBOM attached to a package.

    METADATA_SLUG_PERM selects the entry; run sbom list to see the identifiers
    for a package. Use --output to write the raw document; raw output cannot be
    combined with JSON -F modes.

    \b
    Examples:
        $ cloudsmith sbom get your-org/your-repo/your-pkg meta-slug -F pretty_json
        $ cloudsmith sbom get your-org/your-repo/your-pkg meta-slug --output -
    """
    _inherit_parent_output_format(ctx, opts)
    _require_raw_output(ctx, opts)
    owner, repo, identifier = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)
    _echo_action(
        "Fetching SBOM %(sbom)s for %(package)s ... "
        % {
            "sbom": click.style(metadata_slug_perm, bold=True),
            "package": click.style(identifier, bold=True),
        },
        use_stderr,
    )

    with _handle_sbom_api_exceptions(ctx, opts, "Could not retrieve SBOM."):
        with maybe_spinner(opts):
            slug_perm = _resolve_package_slug(owner, repo, identifier)
            entry = get_metadata(slug_perm, metadata_slug_perm)
            if not _is_supported_sbom_entry(entry):
                raise click.ClickException(
                    "The requested metadata entry is not a supported SBOM. "
                    "Run sbom list to see the SBOM identifiers for this package."
                )

    click.secho("OK", fg="green", err=use_stderr)

    if output is not None:
        _write_raw_json(entry["content"], output)
    else:
        _print_sbom_entry(opts, entry)


@sbom_.command(name="remove", aliases=["rm"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.argument("metadata_slug_perm")
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@click.pass_context
def remove_sbom(ctx, opts, owner_repo_package, metadata_slug_perm, yes):
    """
    Remove an SBOM attached to a package.

    METADATA_SLUG_PERM identifies the entry; run sbom list to see the
    identifiers. Only SBOM entries are removable here. Use cloudsmith metadata
    remove for other metadata.

    \b
    Example:
        $ cloudsmith sbom remove your-org/your-repo/your-pkg meta-slug
    """
    _inherit_parent_output_format(ctx, opts)
    owner, repo, identifier = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)

    remove_args = {
        "sbom": click.style(metadata_slug_perm, bold=True),
        "package": click.style(identifier, bold=True),
    }

    with _handle_sbom_api_exceptions(ctx, opts, "Could not remove SBOM."):
        with maybe_spinner(opts):
            slug_perm = _resolve_package_slug(owner, repo, identifier)
            entry = get_metadata(slug_perm, metadata_slug_perm)
        if not _is_supported_sbom_entry(entry):
            raise click.ClickException(
                "The requested metadata entry is not a supported SBOM. "
                "Use cloudsmith metadata remove for other metadata."
            )

    prompt = "remove SBOM %(sbom)s from package %(package)s" % remove_args
    if not utils.confirm_operation(prompt, assume_yes=yes, err=use_stderr):
        return

    _echo_action("Removing SBOM %(sbom)s ... " % remove_args, use_stderr)

    with _handle_sbom_api_exceptions(ctx, opts, "Could not remove SBOM."):
        with maybe_spinner(opts):
            delete_metadata(slug_perm, metadata_slug_perm)

    click.secho("OK", fg="green", err=use_stderr)

    result = {"deleted": True, "slug_perm": metadata_slug_perm}
    if not utils.maybe_print_as_json(opts, result):
        click.echo()
        click.secho(
            "SBOM removed: %(sbom)s"
            % {"sbom": click.style(metadata_slug_perm, bold=True)}
        )
