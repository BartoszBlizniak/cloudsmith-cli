"""Local SBOM generation and validation support."""

from __future__ import annotations

import json
import re
from typing import Any

from .contracts import (
    CYCLONEDX_CONTENT_TYPE,
    CYCLONEDX_JSON,
    SPDX_CONTENT_TYPE,
    SPDX_JSON,
)
from .generators import get_generator
from .generators.base import GeneratedSbom, GeneratorProviderError
from .validation import SbomValidationError, validate_document

CLOUDSMITH_SBOM_CONTENT_TYPE = "application/vnd.cloudsmith.sbom+json"
DEFAULT_SBOM_SOURCE_IDENTITY = "cli:syft"

# Package metadata is capped at roughly 5 MiB server-side; larger SBOMs are
# rejected with HTTP 413. Surfaced to users so an oversized document produces
# actionable guidance instead of a raw transport error.
SBOM_METADATA_SIZE_LIMIT_HINT = (
    "The SBOM exceeds the package metadata size limit of about 5 MiB. "
    "Reduce the scan scope, or store the document out-of-band."
)

# Server-side package metadata request-body cap. Used to fail fast locally
# before an expensive scan or upload rather than surfacing a raw HTTP 413.
SBOM_METADATA_MAX_BYTES = 5 * 1024 * 1024


class SbomError(Exception):
    """Base exception for local SBOM failures."""


class GeneratorError(SbomError):
    """Raised when an external SBOM generator cannot produce output."""


def normalize_sha256(value: str) -> str:
    """Return a lowercase SHA-256 hex digest, accepting an optional prefix."""
    digest = value.strip().lower()
    if digest.startswith("sha256:"):
        digest = digest.split(":", 1)[1]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("subject digest must be a 64-character SHA-256 value")
    return digest


def validate_sbom(payload: dict[str, Any]) -> tuple[str, str]:
    """Validate a supported SBOM against its official schema."""
    if payload.get("bomFormat") == "CycloneDX":
        if payload.get("specVersion") != "1.6":
            raise SbomError("CycloneDX SBOMs must use specVersion 1.6.")
        output_format = CYCLONEDX_JSON
        content_type = CYCLONEDX_CONTENT_TYPE
    elif payload.get("spdxVersion") == "SPDX-2.3":
        output_format = SPDX_JSON
        content_type = SPDX_CONTENT_TYPE
    else:
        raise SbomError("SBOM must be CycloneDX JSON 1.6 or SPDX JSON 2.3.")

    try:
        validate_document(payload, output_format)
    except SbomValidationError as exc:
        raise SbomError(str(exc)) from exc
    return output_format, content_type


def exceeds_metadata_size(payload: Any) -> bool:
    """Return True if the JSON payload would exceed the metadata size cap."""
    return len(json.dumps(payload).encode("utf-8")) > SBOM_METADATA_MAX_BYTES


def ensure_within_metadata_size(payload: Any) -> None:
    """Raise before upload if the payload exceeds the metadata size cap."""
    if exceeds_metadata_size(payload):
        raise SbomError(SBOM_METADATA_SIZE_LIMIT_HINT)


def generate_sbom_details(
    source: str, *, generator: str, output_format: str, source_type: str = "auto"
) -> GeneratedSbom:
    """Generate an SBOM and return its external generator identity."""
    try:
        provider = get_generator(generator, output_format=output_format)
        result = provider.generate(source, output_format, source_type=source_type)
    except GeneratorProviderError as exc:
        raise GeneratorError(str(exc)) from exc
    detected_format, _ = validate_sbom(result.payload)
    if detected_format != output_format:
        raise GeneratorError(
            f"{result.generator} returned {detected_format}, but "
            f"{output_format} was requested."
        )
    return result


def generate_sbom(
    source: str, *, generator: str, output_format: str, source_type: str = "auto"
) -> dict[str, Any]:
    """Generate and compatibility-check an SBOM using an installed external tool."""
    return generate_sbom_details(
        source,
        generator=generator,
        output_format=output_format,
        source_type=source_type,
    ).payload
