"""Shared command and provider contracts for supported SBOM formats."""

CYCLONEDX_JSON = "cyclonedx-json"
SPDX_JSON = "spdx-json"
SBOM_FORMATS = (CYCLONEDX_JSON, SPDX_JSON)
DEFAULT_SBOM_FORMAT = CYCLONEDX_JSON

# How the scan source should be interpreted. "auto" infers directory-vs-image
# from filesystem existence (Syft always auto-detects); "directory"/"image"
# force the interpretation, which matters for local image archives under Trivy.
SOURCE_TYPE_AUTO = "auto"
SOURCE_TYPES = (SOURCE_TYPE_AUTO, "directory", "image")

CYCLONEDX_CONTENT_TYPE = "application/vnd.cyclonedx+json"
SPDX_CONTENT_TYPE = "application/spdx+json"

FORMAT_CONTENT_TYPES = {
    CYCLONEDX_JSON: CYCLONEDX_CONTENT_TYPE,
    SPDX_JSON: SPDX_CONTENT_TYPE,
}
