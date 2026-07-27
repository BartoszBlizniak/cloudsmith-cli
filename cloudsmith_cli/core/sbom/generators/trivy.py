"""Trivy SBOM generator provider."""

from __future__ import annotations

from pathlib import Path

from cloudsmith_cli.core.sbom.contracts import CYCLONEDX_JSON, SPDX_JSON
from cloudsmith_cli.core.sbom.generators.base import (
    VERSION_TIMEOUT_SECONDS,
    ExternalGenerator,
    GeneratorVersion,
)


class TrivyGenerator(ExternalGenerator):
    """Generate supported SPDX documents with Trivy."""

    name = "trivy"
    executable_name = "trivy"
    minimum_version = (0, 72, 0)
    tested_version = (0, 72, 0)
    # Trivy 0.72 emits CycloneDX 1.7, while the Build Insights contract accepts
    # CycloneDX 1.6. Support current Trivy through its SPDX 2.3 output instead.
    supported_formats = frozenset({SPDX_JSON})

    def version(self) -> GeneratorVersion:
        completed = self._run(
            [self.executable, "--version"],
            timeout=VERSION_TIMEOUT_SECONDS,
            operation="detect its version",
        )
        return GeneratorVersion.parse(completed.stdout)

    def build_command(
        self, source: str, output_format: str, source_type: str = "auto"
    ) -> list[str]:
        output = {
            CYCLONEDX_JSON: "cyclonedx",
            SPDX_JSON: "spdx-json",
        }[output_format]
        if source_type == "directory":
            return [self.executable, "fs", "--format", output, source]
        if source_type == "image":
            # A local image archive needs --input; a registry/daemon reference
            # is passed positionally. Path existence disambiguates the two.
            if Path(source).exists():
                return [self.executable, "image", "--input", source, "--format", output]
            return [self.executable, "image", "--format", output, source]
        # auto: a filesystem path if it exists, otherwise an image reference.
        # Note: a local image archive is scanned as a filesystem here; pass
        # --sbom-source-type image to scan it as an image instead.
        scan_kind = "fs" if Path(source).exists() else "image"
        return [self.executable, scan_kind, "--format", output, source]

    def environment(self) -> dict[str, str]:
        environment = super().environment()
        environment["TRIVY_CACHE_DIR"] = self.cache_directory("trivy")
        return environment
