"""Tests for SBOM commands."""

import json
from unittest.mock import call, patch

from click.testing import CliRunner

from cloudsmith_cli.cli.commands.main import main
from cloudsmith_cli.cli.commands.sbom import sbom_
from cloudsmith_cli.core.api.exceptions import ApiException
from cloudsmith_cli.core.api.packages import PackageResolutionError
from cloudsmith_cli.core.pagination import PageInfo

PACKAGE = {
    "slug": "example",
    "slug_perm": "pkg123",
    "purl": "pkg:pypi/example@1.0",
    "checksum_sha256": "d" * 64,
}
SPDX_SBOM = {
    "SPDXID": "SPDXRef-DOCUMENT",
    "creationInfo": {
        "created": "2026-07-23T12:00:00Z",
        "creators": ["Tool: test-suite"],
    },
    "dataLicense": "CC0-1.0",
    "documentNamespace": "https://example.test/spdx/test",
    "name": "test",
    "spdxVersion": "SPDX-2.3",
}


def _empty_page_info():
    return PageInfo()


def _page_info(*, page=1, page_total=1, count=0, page_size=1000):
    info = PageInfo()
    info.page = page
    info.page_total = page_total
    info.count = count
    info.page_size = page_size
    return info


def test_unsupported_attestation_command_is_not_registered():
    result = CliRunner().invoke(main, ["package", "attest", "org/repo/example"])

    assert result.exit_code == 2
    assert "No such command 'package'" in result.output


@patch("cloudsmith_cli.cli.commands.sbom.generate_sbom_document")
@patch("cloudsmith_cli.cli.decorators._initialise_api")
def test_generate_writes_only_raw_sbom_without_initialising_api(
    mock_initialise_api, mock_generate
):
    mock_generate.return_value = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
    }
    result = CliRunner().invoke(
        sbom_, ["generate", ".", "--output", "-", "--generator", "syft"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["bomFormat"] == "CycloneDX"
    mock_initialise_api.assert_not_called()


def test_generate_rejects_json_envelope_with_raw_output():
    result = CliRunner().invoke(sbom_, ["generate", "-F", "json", ".", "--output", "-"])
    assert result.exit_code == 2
    assert "cannot be combined" in result.output


@patch("cloudsmith_cli.cli.commands.sbom.generate_sbom_document")
def test_generate_rejects_group_json_format_with_raw_output(mock_generate):
    result = CliRunner().invoke(sbom_, ["-F", "json", "generate", ".", "--output", "-"])

    assert result.exit_code == 2
    assert "cannot be combined" in result.output
    mock_generate.assert_not_called()


@patch("cloudsmith_cli.cli.commands.sbom.generate_sbom_document")
def test_generate_rejects_top_level_json_format_with_raw_output(mock_generate):
    result = CliRunner().invoke(
        main,
        ["-F", "json", "sbom", "generate", ".", "--output", "-"],
    )

    assert result.exit_code == 2
    assert "cannot be combined" in result.output
    mock_generate.assert_not_called()


def test_sbom_help_describes_generator_and_raw_output_contract():
    result = CliRunner().invoke(sbom_, ["generate", "--help"], terminal_width=120)

    assert result.exit_code == 0, result.output
    assert "The generator must be installed" in result.output
    assert "PATH." in result.output
    assert "'auto' prefers Syft" in result.output
    assert "installed, qualified provider" in result.output
    assert "'-' for stdout" in result.output


def test_sbom_add_help_describes_stdin_and_digest_safety():
    result = CliRunner().invoke(sbom_, ["add", "--help"], terminal_width=120)

    assert result.exit_code == 0, result.output
    assert "Use '-' for stdin" in result.output
    assert "expected SHA-256 digest" in result.output
    assert "cli:imported" in result.output
    assert "Imported documents use a neutral" in result.output
    assert "--content-type" not in result.output


def test_sbom_add_rejects_invalid_subject_digest_as_pretty_usage_error(tmp_path):
    sbom_file = tmp_path / "bom.json"
    sbom_file.write_text(json.dumps(SPDX_SBOM), encoding="utf-8")

    result = CliRunner().invoke(
        sbom_,
        [
            "add",
            "org/repo/example",
            "--file",
            str(sbom_file),
            "--subject-digest",
            "not-a-digest",
        ],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--subject-digest'" in result.output
    assert "64-character SHA-256" in result.output


def test_sbom_add_rejects_invalid_subject_digest_as_json_usage_error(
    monkeypatch, tmp_path
):
    sbom_file = tmp_path / "bom.json"
    sbom_file.write_text(json.dumps(SPDX_SBOM), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["cloudsmith", "sbom", "add", "-F", "json"])

    result = CliRunner().invoke(
        sbom_,
        [
            "add",
            "-F",
            "json",
            "org/repo/example",
            "--file",
            str(sbom_file),
            "--subject-digest",
            "not-a-digest",
        ],
    )

    assert result.exit_code == 2
    output = json.loads(result.stdout)
    assert output["meta"]["code"] == 2
    assert "Invalid value for '--subject-digest'" in output["detail"]
    assert "64-character SHA-256" in output["detail"]


@patch("cloudsmith_cli.cli.commands.sbom.create_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.validate_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_add_validates_before_create(
    mock_resolve, mock_list, mock_validate, mock_create, tmp_path
):
    mock_list.return_value = ([], _empty_page_info())
    mock_create.return_value = {"slug_perm": "meta123"}
    sbom_file = tmp_path / "bom.json"
    sbom_file.write_text(
        '{"bomFormat":"CycloneDX","specVersion":"1.6","version":1}',
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        sbom_,
        ["add", "-F", "json", "org/repo/example", "--file", str(sbom_file)],
    )
    assert result.exit_code == 0, result.output
    mock_validate.assert_called_once()
    mock_create.assert_called_once()
    assert mock_validate.call_args.kwargs["content_type"] == (
        "application/vnd.cloudsmith.sbom+json"
    )
    assert mock_create.call_args.kwargs["source_identity"] == "cli:imported"
    assert json.loads(result.stdout)["data"]["package_sha256"] == "d" * 64


@patch("cloudsmith_cli.cli.commands.sbom.create_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.validate_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_add_reads_sbom_from_stdin(
    _mock_resolve, mock_list, mock_validate, mock_create
):
    mock_list.return_value = ([], _empty_page_info())
    mock_create.return_value = {"slug_perm": "meta123"}
    payload = {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1}

    result = CliRunner().invoke(
        sbom_,
        ["add", "-F", "json", "org/repo/example", "--file", "-"],
        input=json.dumps(payload),
    )

    assert result.exit_code == 0, result.output
    assert mock_validate.call_args.kwargs["content"] == payload
    assert mock_create.call_args.kwargs["content"] == payload
    assert mock_create.call_args.kwargs["source_identity"] == "cli:imported"


@patch("cloudsmith_cli.cli.commands.sbom.create_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.validate_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_add_is_idempotent(
    _mock_resolve, mock_list, mock_validate, mock_create, tmp_path
):
    payload = {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1}
    mock_list.return_value = (
        [
            {
                "slug_perm": "existing",
                "content": payload,
                "content_type": "application/vnd.cloudsmith.sbom+json",
                "source_identity": "same-source",
            }
        ],
        _empty_page_info(),
    )
    sbom_file = tmp_path / "bom.json"
    sbom_file.write_text(json.dumps(payload), encoding="utf-8")
    result = CliRunner().invoke(
        sbom_,
        [
            "add",
            "-F",
            "json",
            "org/repo/example",
            "--file",
            str(sbom_file),
            "--source-identity",
            "same-source",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["created"] is False
    mock_validate.assert_not_called()
    mock_create.assert_not_called()


@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_add_rejects_digest_mismatch(_mock_resolve, tmp_path):
    sbom_file = tmp_path / "bom.json"
    sbom_file.write_text(json.dumps(SPDX_SBOM), encoding="utf-8")
    result = CliRunner().invoke(
        sbom_,
        [
            "add",
            "org/repo/example",
            "--file",
            str(sbom_file),
            "--subject-digest",
            "e" * 64,
        ],
    )
    assert result.exit_code == 1
    assert "does not match" in result.output


@patch(
    "cloudsmith_cli.cli.commands.sbom.resolve_package",
    side_effect=PackageResolutionError(
        "Resolved package does not expose a SHA-256 digest."
    ),
)
def test_list_renders_digest_resolution_failure_as_pretty_error(_mock_resolve):
    result = CliRunner().invoke(sbom_, ["list", "org/repo/example"])

    assert result.exit_code == 1
    assert "Error: Resolved package does not expose a SHA-256 digest." in result.output
    assert result.exception is not None
    assert not isinstance(result.exception, PackageResolutionError)


@patch(
    "cloudsmith_cli.cli.commands.sbom.resolve_package",
    side_effect=PackageResolutionError(
        "Resolved package does not expose a SHA-256 digest."
    ),
)
def test_list_renders_digest_resolution_failure_as_json(_mock_resolve, monkeypatch):
    monkeypatch.setattr("sys.argv", ["cloudsmith", "sbom", "list", "-F", "json"])

    result = CliRunner().invoke(
        sbom_,
        ["list", "-F", "json", "org/repo/example"],
    )

    assert result.exit_code == 1
    output = json.loads(result.stdout)
    assert output["meta"]["code"] == 1
    assert output["detail"] == ("Resolved package does not expose a SHA-256 digest.")


@patch("cloudsmith_cli.cli.commands.sbom.get_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_get_rejects_sbom_shaped_metadata_with_an_untyped_content_type(
    _mock_resolve, mock_get_metadata
):
    mock_get_metadata.return_value = {
        "classification": "GENERIC",
        "content_type": "application/vnd.example.build-sbom+json",
        "content": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
        },
    }
    result = CliRunner().invoke(
        sbom_,
        ["get", "org/repo/example", "meta123", "--output", "-"],
    )
    assert result.exit_code == 1
    assert "not a supported SBOM" in result.output


@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_list_ignores_sbom_shaped_metadata_with_an_untyped_content_type(
    _mock_resolve, mock_list_metadata
):
    custom_sbom = {
        "slug_perm": "custom-sbom",
        "classification": "GENERIC",
        "content_type": "application/vnd.example.build-sbom+json",
        "source_identity": "buildkit:production",
        "content": SPDX_SBOM,
    }
    mock_list_metadata.return_value = ([custom_sbom], _empty_page_info())

    result = CliRunner().invoke(
        sbom_,
        ["list", "-F", "json", "org/repo/example", "--page-all"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"] == []


@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_list_honors_group_level_json_format(_mock_resolve, mock_list_metadata):
    entry = {
        "slug_perm": "sbom-1",
        "content_type": "application/vnd.cloudsmith.sbom+json",
        "source_identity": "cli:syft",
        "content": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
        },
    }
    mock_list_metadata.return_value = ([entry], _empty_page_info())

    result = CliRunner().invoke(
        sbom_,
        ["-F", "json", "list", "org/repo/example", "--page-all"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"data": [entry]}


@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_list_child_output_format_overrides_group_format(
    _mock_resolve, mock_list_metadata
):
    entry = {
        "slug_perm": "sbom-1",
        "content_type": "application/vnd.cloudsmith.sbom+json",
        "source_identity": "cli:syft",
        "content": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
        },
    }
    mock_list_metadata.return_value = ([entry], _empty_page_info())

    result = CliRunner().invoke(
        sbom_,
        ["-F", "json", "list", "-F", "pretty", "org/repo/example", "--page-all"],
    )

    assert result.exit_code == 0, result.output
    assert "Slug" in result.output
    assert "Results: 1 SBOM retrieved" in result.output


@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_list_pretty_output_uses_table_and_result_summary(
    _mock_resolve, mock_list_metadata
):
    entry = {
        "slug_perm": "sbom-1",
        "created_at": "2026-07-23T12:00:00Z",
        "content_type": "application/vnd.cloudsmith.sbom+json",
        "source_identity": "cli:syft",
        "content": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
        },
    }
    mock_list_metadata.return_value = ([entry], _empty_page_info())

    result = CliRunner().invoke(
        sbom_,
        ["list", "org/repo/example", "--page-all"],
    )

    assert result.exit_code == 0, result.output
    assert "Slug" in result.output
    assert "Content type" in result.output
    assert "Source identity" in result.output
    assert "Created" in result.output
    assert "sbom-1" in result.output
    assert "cli:syft" in result.output
    assert "2026-07-23T12:00:00Z" in result.output
    assert "Results: 1 SBOM retrieved" in result.output


@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_list_pretty_output_has_clear_empty_state(_mock_resolve, mock_list_metadata):
    mock_list_metadata.return_value = ([], _empty_page_info())

    result = CliRunner().invoke(sbom_, ["list", "org/repo/example"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Results: 0 SBOMs visible"


@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_get_by_package_returns_empty_json_data(_mock_resolve, mock_list_metadata):
    mock_list_metadata.return_value = ([], _empty_page_info())

    result = CliRunner().invoke(
        sbom_,
        ["get", "-F", "json", "org/repo/example"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"data": []}


@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_get_by_package_returns_full_supported_entries(
    _mock_resolve, mock_list_metadata
):
    entry = {
        "slug_perm": "meta123",
        "created_at": "2026-07-23T12:00:00Z",
        "source_identity": "cli:syft",
        "content_type": "application/vnd.cloudsmith.sbom+json",
        "content": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
        },
    }
    mock_list_metadata.return_value = ([entry], _empty_page_info())

    result = CliRunner().invoke(
        sbom_,
        ["get", "-F", "json", "org/repo/example"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"] == [entry]


@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_list_paginates_the_filtered_sbom_collection(_mock_resolve, mock_list_metadata):
    first_sbom = {
        "slug_perm": "sbom-1",
        "content_type": "application/vnd.cloudsmith.sbom+json",
        "content": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
        },
    }
    second_sbom = {
        "slug_perm": "sbom-2",
        "content_type": "application/vnd.cloudsmith.sbom+json",
        "content": SPDX_SBOM,
    }
    other_metadata = {
        "slug_perm": "other",
        "content_type": "application/json",
        "content": {"kind": "build"},
    }
    mock_list_metadata.side_effect = [
        ([other_metadata, first_sbom], _page_info(page=1, page_total=2, count=3)),
        ([second_sbom], _page_info(page=2, page_total=2, count=3)),
    ]

    result = CliRunner().invoke(
        sbom_,
        [
            "list",
            "-F",
            "json",
            "org/repo/example",
            "--page",
            "2",
            "--page-size",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output["data"] == [second_sbom]
    assert output["meta"]["pagination"] == {
        "page": 2,
        "page_max": 2,
        "page_results_from": 2,
        "page_results_len": 1,
        "page_results_to": 2,
        "page_size": 1,
        "results_total": 2,
    }
    assert mock_list_metadata.call_args_list == [
        call(
            page=1,
            page_size=1000,
            package_slug_perm="pkg123",
            source_kind="CUSTOM",
        ),
        call(
            page=2,
            page_size=1000,
            package_slug_perm="pkg123",
            source_kind="CUSTOM",
        ),
    ]


@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_list_pretty_output_includes_filtered_pagination(
    _mock_resolve, mock_list_metadata
):
    entries = [
        {
            "slug_perm": f"sbom-{number}",
            "content_type": "application/vnd.cloudsmith.sbom+json",
            "source_identity": "cli:syft",
            "content": {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "version": 1,
            },
        }
        for number in (1, 2)
    ]
    mock_list_metadata.return_value = (entries, _empty_page_info())

    result = CliRunner().invoke(
        sbom_,
        [
            "list",
            "org/repo/example",
            "--page",
            "2",
            "--page-size",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "sbom-2" in result.output
    assert "sbom-1" not in result.output
    assert (
        "Results: 2-2 (1) of 2 SBOMs visible "
        "(page: 2/2, page size: 1)" in result.output
    )


@patch("cloudsmith_cli.cli.commands.sbom.create_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.validate_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_add_allows_source_identity_override(
    _mock_resolve, mock_list, mock_validate, mock_create, tmp_path
):
    mock_list.return_value = ([], _empty_page_info())
    mock_create.return_value = {"slug_perm": "meta123"}
    sbom_file = tmp_path / "bom.json"
    sbom_file.write_text(json.dumps(SPDX_SBOM), encoding="utf-8")

    result = CliRunner().invoke(
        sbom_,
        [
            "add",
            "org/repo/example",
            "--file",
            str(sbom_file),
            "--source-identity",
            "buildkit:production",
        ],
    )

    assert result.exit_code == 0, result.output
    mock_validate.assert_called_once_with(
        content=SPDX_SBOM,
        content_type="application/vnd.cloudsmith.sbom+json",
    )
    mock_create.assert_called_once_with(
        "pkg123",
        content=SPDX_SBOM,
        content_type="application/vnd.cloudsmith.sbom+json",
        source_identity="buildkit:production",
    )


@patch(
    "cloudsmith_cli.cli.commands.sbom.resolve_package",
    side_effect=ApiException(status=404, detail="Package not found"),
)
def test_add_renders_clear_missing_package_error(_mock_resolve, tmp_path):
    sbom_file = tmp_path / "bom.json"
    sbom_file.write_text(
        '{"bomFormat":"CycloneDX","specVersion":"1.6","version":1}',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        sbom_,
        ["add", "org/repo/missing", "--file", str(sbom_file)],
    )

    assert result.exit_code != 0
    assert "Could not attach SBOM" in result.output
    assert "Package not found" in result.output


@patch(
    "cloudsmith_cli.cli.commands.sbom.resolve_package",
    side_effect=ApiException(status=404, detail="Package not found"),
)
def test_add_json_api_error_emits_one_document(_mock_resolve, tmp_path):
    sbom_file = tmp_path / "bom.json"
    sbom_file.write_text(json.dumps(SPDX_SBOM), encoding="utf-8")

    result = CliRunner().invoke(
        sbom_,
        [
            "add",
            "-F",
            "json",
            "org/repo/missing",
            "--file",
            str(sbom_file),
        ],
    )

    assert result.exit_code == 404
    output = json.loads(result.stdout)
    assert output["detail"] == "Package not found"
    assert output["help"]["context"] == "Could not attach SBOM."
    assert output["meta"]["code"] == 404


@patch(
    "cloudsmith_cli.cli.commands.sbom.create_metadata",
    side_effect=ApiException(status=403, detail="Permission denied"),
)
@patch("cloudsmith_cli.cli.commands.sbom.validate_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.list_metadata")
@patch("cloudsmith_cli.cli.commands.sbom.resolve_package", return_value=PACKAGE)
def test_add_renders_clear_permission_error(
    _mock_resolve, mock_list, _mock_validate, _mock_create, tmp_path
):
    mock_list.return_value = ([], _empty_page_info())
    sbom_file = tmp_path / "bom.json"
    sbom_file.write_text(json.dumps(SPDX_SBOM), encoding="utf-8")

    result = CliRunner().invoke(
        sbom_,
        ["add", "org/repo/example", "--file", str(sbom_file)],
    )

    assert result.exit_code != 0
    assert "Could not attach SBOM" in result.output
    assert "Permission denied" in result.output
