"""Shared command and provider contracts for supported SBOM formats."""

CYCLONEDX_JSON = "cyclonedx-json"
SPDX_JSON = "spdx-json"
SBOM_FORMATS = (CYCLONEDX_JSON, SPDX_JSON)
DEFAULT_SBOM_FORMAT = CYCLONEDX_JSON

CYCLONEDX_CONTENT_TYPE = "application/vnd.cyclonedx+json"
SPDX_CONTENT_TYPE = "application/spdx+json"

FORMAT_CONTENT_TYPES = {
    CYCLONEDX_JSON: CYCLONEDX_CONTENT_TYPE,
    SPDX_JSON: SPDX_CONTENT_TYPE,
}
