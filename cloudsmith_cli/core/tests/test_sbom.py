"""Tests for local SBOM generation and validation."""

from unittest.mock import MagicMock, patch

import pytest
from cloudsmith_api.rest import ApiException as SdkApiException

from cloudsmith_cli.core.api.exceptions import ApiException
from cloudsmith_cli.core.api.packages import (
    PackageResolutionError,
    get_package,
    resolve_package,
)
from cloudsmith_cli.core.sbom import (
    GeneratorError,
    SbomError,
    generate_sbom,
    normalize_sha256,
    validate_sbom,
)

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


@patch("cloudsmith_cli.core.api.packages.ratelimits.maybe_rate_limit")
@patch("cloudsmith_cli.core.api.packages.get_packages_api")
def test_get_package_wraps_sdk_and_obeys_rate_limits(mock_get_api, mock_rate_limit):
    client = mock_get_api.return_value
    package_model = MagicMock()
    package_model.to_dict.return_value = {
        "slug_perm": "pkg",
        "checksum_sha256": "a" * 64,
    }
    headers = {"X-RateLimit-Remaining": "10"}
    client.packages_read_with_http_info.return_value = (
        package_model,
        200,
        headers,
    )

    result = get_package("org", "repo", "pkg")

    assert result["slug_perm"] == "pkg"
    client.packages_read_with_http_info.assert_called_once_with(
        owner="org",
        repo="repo",
        identifier="pkg",
    )
    mock_rate_limit.assert_called_once_with(client, headers)


@patch("cloudsmith_cli.core.api.packages.get_packages_api")
def test_get_package_translates_sdk_exceptions(mock_get_api):
    mock_get_api.return_value.packages_read_with_http_info.side_effect = (
        SdkApiException(status=404, reason="Package not found")
    )

    with pytest.raises(ApiException) as exc_info:
        get_package("org", "repo", "missing")

    assert exc_info.value.status == 404
    assert exc_info.value.detail == "Package not found"


@patch("cloudsmith_cli.core.api.packages.get_package")
def test_resolve_package_requires_and_returns_digest_bound_package(mock_get):
    mock_get.return_value = {"slug_perm": "pkg", "checksum_sha256": "a" * 64}

    assert resolve_package("org", "repo", "pkg")["slug_perm"] == "pkg"


@patch("cloudsmith_cli.core.api.packages.get_package")
def test_resolve_package_rejects_invalid_digest(mock_get):
    mock_get.return_value = {"slug_perm": "pkg", "checksum_sha256": "invalid"}

    with pytest.raises(PackageResolutionError, match="does not expose"):
        resolve_package("org", "repo", "pkg")


def test_normalize_sha256_accepts_prefix():
    digest = "a" * 64
    assert normalize_sha256(f"sha256:{digest.upper()}") == digest


def test_normalize_sha256_rejects_non_sha256():
    with pytest.raises(ValueError, match="64-character"):
        normalize_sha256("abcd")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"bomFormat": "CycloneDX", "specVersion": "1.6"},
            ("cyclonedx-json", "application/vnd.cyclonedx+json"),
        ),
        (
            SPDX_SBOM,
            ("spdx-json", "application/spdx+json"),
        ),
    ],
)
def test_validate_sbom(payload, expected):
    assert validate_sbom(payload) == expected


def test_validate_sbom_rejects_old_cyclonedx():
    with pytest.raises(SbomError, match="1.6"):
        validate_sbom({"bomFormat": "CycloneDX", "specVersion": "1.5"})


def test_validate_sbom_rejects_malformed_cyclonedx_component():
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [{"type": "library"}],
    }

    with pytest.raises(
        SbomError,
        match=r"CycloneDX 1\.6 schema validation failed.*name.*required",
    ):
        validate_sbom(payload)


def test_validate_sbom_enforces_official_timestamp_format():
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"timestamp": "not-a-date"},
    }

    with pytest.raises(
        SbomError,
        match=r"CycloneDX 1\.6 schema validation failed.*timestamp.*format",
    ):
        validate_sbom(payload)


def test_validate_sbom_bounds_external_schema_enum_errors():
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [
            {
                "type": "library",
                "name": "example",
                "licenses": [{"license": {"id": "not-an-spdx-license"}}],
            }
        ],
    }

    with pytest.raises(SbomError) as exc_info:
        validate_sbom(payload)

    message = str(exc_info.value)
    assert "value is not one of the allowed values" in message
    assert len(message) < 250


def test_validate_sbom_rejects_incomplete_spdx_document():
    with pytest.raises(
        SbomError,
        match=r"SPDX 2\.3 schema validation failed.*SPDXID.*required",
    ):
        validate_sbom({"spdxVersion": "SPDX-2.3"})


@patch("cloudsmith_cli.core.sbom.get_generator")
def test_generate_sbom_validates_provider_output(mock_get_generator):
    mock_get_generator.return_value.generate.return_value.payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
    }

    assert generate_sbom(".", generator="syft", output_format="cyclonedx-json") == {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
    }
    mock_get_generator.assert_called_once_with("syft", output_format="cyclonedx-json")


@patch("cloudsmith_cli.core.sbom.get_generator")
def test_generate_sbom_rejects_provider_format_mismatch(mock_get_generator):
    generated = mock_get_generator.return_value.generate.return_value
    generated.payload = SPDX_SBOM
    generated.generator = "syft"

    with pytest.raises(GeneratorError, match="spdx-json.*cyclonedx-json"):
        generate_sbom(".", generator="syft", output_format="cyclonedx-json")
