"""Tests for offline SBOM schema validation."""

import pytest

from cloudsmith_cli.core.sbom.contracts import CYCLONEDX_JSON, SPDX_JSON
from cloudsmith_cli.core.sbom.validation import SbomValidationError, validate_document


def test_validate_document_accepts_cyclonedx_16():
    validate_document(
        {"bomFormat": "CycloneDX", "specVersion": "1.6"},
        CYCLONEDX_JSON,
    )


def test_validate_document_resolves_bundled_cyclonedx_references():
    validate_document(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [
                {
                    "type": "library",
                    "name": "example",
                    "licenses": [{"license": {"id": "MIT"}}],
                }
            ],
        },
        CYCLONEDX_JSON,
    )


def test_validate_document_accepts_spdx_23():
    validate_document(
        {
            "SPDXID": "SPDXRef-DOCUMENT",
            "creationInfo": {
                "created": "2026-07-24T08:00:00Z",
                "creators": ["Tool: cloudsmith-cli-tests"],
            },
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.invalid/spdx/document",
            "name": "example",
            "spdxVersion": "SPDX-2.3",
        },
        SPDX_JSON,
    )


def test_validate_document_enforces_format_checks():
    with pytest.raises(
        SbomValidationError,
        match=r"metadata\.timestamp.*required date-time format",
    ):
        validate_document(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {"timestamp": "not-a-timestamp"},
            },
            CYCLONEDX_JSON,
        )


def test_validate_document_reports_missing_required_property_safely():
    with pytest.raises(
        SbomValidationError,
        match=r"SPDXID is required",
    ):
        validate_document(
            {"spdxVersion": "SPDX-2.3"},
            SPDX_JSON,
        )


def test_validate_document_does_not_echo_unknown_properties():
    secret_property = "customer_token_super_secret"

    with pytest.raises(SbomValidationError) as exc_info:
        validate_document(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                secret_property: "sensitive-value",
            },
            CYCLONEDX_JSON,
        )

    message = str(exc_info.value)
    assert "document violates a schema constraint" in message
    assert secret_property not in message
    assert "sensitive-value" not in message
