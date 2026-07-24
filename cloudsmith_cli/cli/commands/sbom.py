"""CLI commands for generating and managing package SBOM metadata."""

from __future__ import annotations

import contextlib
import json

import click
from click.core import ParameterSource

from ...core.api.exceptions import ApiException
from ...core.api.metadata import (
    create_metadata,
    get_metadata,
    list_metadata,
    validate_metadata,
)
from ...core.api.packages import PackageResolutionError, package_sha256, resolve_package
from ...core.pagination import PageInfo, paginate_results
from ...core.sbom import (
    CLOUDSMITH_SBOM_CONTENT_TYPE,
    SbomError,
    generate_sbom as generate_sbom_document,
    normalize_sha256,
    validate_sbom,
)
from ...core.sbom.contracts import DEFAULT_SBOM_FORMAT, SBOM_FORMATS
from ...core.sbom.generators import DEFAULT_GENERATOR, GENERATOR_NAMES
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..metadata_common import resolve_metadata_content
from .main import main

DEFAULT_IMPORTED_SBOM_SOURCE_IDENTITY = "cli:imported"

_SBOM_HEADERS = ["Slug", "Content type", "Source identity", "Created"]


class _SbomPageInfo(PageInfo):
    """Report accurate filtered-page counts without changing shared CLI output."""

    def as_dict(self, num_results=None):
        data = super().as_dict(num_results=num_results)
        if num_results is not None and self.is_valid:
            data["page_results_len"] = num_results
        return data


@contextlib.contextmanager
def _handle_sbom_api_exceptions(ctx, opts, context_msg):
    """Render one standard API error document and preserve its exit status."""
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
        # AliasGroup runs Click in non-standalone mode and converts
        # click.Exit into a successful return value. SystemExit preserves the
        # API status without asking AliasGroup to render a second JSON error.
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


def _require_raw_output(opts, output: str | None) -> None:
    if output is not None and opts.output != "pretty":
        raise click.UsageError(
            "--output cannot be combined with -F/--output-format JSON modes."
        )


def _is_supported_sbom_entry(entry: dict) -> bool:
    """Recognize schema-valid documents attached by the typed SBOM workflow."""
    if entry.get("content_type") != CLOUDSMITH_SBOM_CONTENT_TYPE:
        return False
    try:
        validate_sbom(entry.get("content") or {})
    except SbomError:
        return False
    return True


def _resolve_package(owner: str, repo: str, identifier: str) -> dict:
    """Resolve a digest-bound package and render local resolution failures."""
    try:
        return resolve_package(owner, repo, identifier)
    except PackageResolutionError as exc:
        raise click.ClickException(str(exc)) from exc


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
    return [
        click.style(entry.get("slug_perm") or "", fg="cyan"),
        click.style(entry.get("content_type") or "", fg="yellow"),
        click.style(entry.get("source_identity") or "", fg="green"),
        entry.get("created_at") or "",
    ]


def _print_sbom_table(opts, entries, page_info=None, page_all=False):
    """Print SBOM metadata as a table with the standard list summary."""
    if utils.maybe_print_as_json(
        opts, list(entries), page_info=None if page_all else page_info
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


@main.group(name="sbom", cls=command.AliasGroup)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.pass_context
def sbom_(ctx, opts):  # pylint: disable=unused-argument
    """
    Generate and manage package software bills of materials.

    Use generate for a local document, add for an existing package, and list
    or get to inspect attached SBOMs.
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
        "External generator must be installed on PATH. 'auto' prefers Syft, "
        "then falls back to another installed, qualified provider that supports "
        "the requested format."
    ),
)
@click.option(
    "--format",
    "sbom_format",
    type=click.Choice(SBOM_FORMATS),
    default=DEFAULT_SBOM_FORMAT,
    show_default=True,
    help="SBOM document format and schema version.",
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Write the raw SBOM document to FILE, or '-' for stdout.",
)
@click.pass_context
def generate_sbom(ctx, opts, source, generator, sbom_format, output):
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
    _require_raw_output(opts, output)
    try:
        payload = generate_sbom_document(
            source, generator=generator, output_format=sbom_format
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
    except SbomError as exc:
        raise click.ClickException(str(exc)) from exc

    with _handle_sbom_api_exceptions(ctx, opts, "Could not attach SBOM."):
        package = _resolve_package(owner, repo, identifier)
        digest = package_sha256(package)
        if subject_digest and normalize_sha256(subject_digest) != digest:
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

    result = {"created": created, "metadata": entry, "package_sha256": digest}
    if not utils.maybe_print_as_json(opts, result):
        action = "attached as" if created else "already exists as"
        click.secho(f"SBOM {action} {entry.get('slug_perm', 'metadata')}", fg="green")
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
@click.pass_context
def list_sboms(ctx, opts, owner_repo_package, page, page_size, page_all):
    """
    List SBOM metadata attached to a package.

    \b
    Examples:
        $ cloudsmith sbom list your-org/your-repo/your-pkg
        $ cloudsmith sbom list your-org/your-repo/your-pkg --page-all -F json
    """
    _inherit_parent_output_format(ctx, opts)
    owner, repo, identifier = owner_repo_package
    with _handle_sbom_api_exceptions(ctx, opts, "Could not list SBOMs."):
        package = _resolve_package(owner, repo, identifier)
        entries, page_info = _list_sbom_entries(
            package["slug_perm"],
            page=page,
            page_size=page_size,
            page_all=page_all,
        )

    _print_sbom_table(opts, entries, page_info=page_info, page_all=page_all)


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
@click.argument("metadata_slug_perm", required=False)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Write the raw SBOM document to FILE, or '-' for stdout.",
)
@click.pass_context
def get_sbom(ctx, opts, owner_repo_package, metadata_slug_perm, output):
    """
    Retrieve package SBOMs, optionally selecting one metadata entry.

    Without METADATA_SLUG_PERM, all SBOM entries are returned. Select one entry
    to use --output; raw output cannot be combined with JSON -F modes.

    \b
    Examples:
        $ cloudsmith sbom get your-org/your-repo/your-pkg -F pretty_json
        $ cloudsmith sbom get your-org/your-repo/your-pkg meta-slug --output -
    """
    _inherit_parent_output_format(ctx, opts)
    _require_raw_output(opts, output)
    owner, repo, identifier = owner_repo_package
    with _handle_sbom_api_exceptions(ctx, opts, "Could not retrieve SBOM."):
        package = _resolve_package(owner, repo, identifier)
        if metadata_slug_perm:
            entry = get_metadata(package["slug_perm"], metadata_slug_perm)
            if not _is_supported_sbom_entry(entry):
                raise click.ClickException(
                    "The requested metadata entry is not a supported SBOM."
                )
            entries = [entry]
        else:
            entries, _ = _list_sbom_entries(package["slug_perm"], page_all=True)

    if output is not None:
        if len(entries) != 1:
            raise click.UsageError(
                "--output requires exactly one SBOM. Pass its metadata identifier "
                "when the package has zero or multiple SBOMs."
            )
        _write_raw_json(entries[0]["content"], output)
    elif metadata_slug_perm:
        if not utils.maybe_print_as_json(opts, entries[0]):
            click.echo(json.dumps(entries[0], indent=2, sort_keys=True))
    elif not utils.maybe_print_as_json(opts, entries):
        for entry in entries:
            click.echo(json.dumps(entry, indent=2, sort_keys=True))
