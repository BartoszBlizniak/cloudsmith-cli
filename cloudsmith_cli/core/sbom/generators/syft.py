"""Syft SBOM generator provider."""

from __future__ import annotations

import json

from cloudsmith_cli.core.sbom.contracts import CYCLONEDX_JSON, SPDX_JSON
from cloudsmith_cli.core.sbom.generators.base import (
    VERSION_TIMEOUT_SECONDS,
    ExternalGenerator,
    GeneratorProviderError,
    GeneratorVersion,
)


class SyftGenerator(ExternalGenerator):
    """Generate CycloneDX or SPDX documents with Syft."""

    name = "syft"
    executable_name = "syft"
    minimum_version = (1, 49, 0)
    tested_version = (1, 49, 0)

    def version(self) -> GeneratorVersion:
        completed = self._run(
            [self.executable, "version", "-o", "json"],
            timeout=VERSION_TIMEOUT_SECONDS,
            operation="detect its version",
        )
        try:
            payload = json.loads(completed.stdout)
        except ValueError as exc:
            raise GeneratorProviderError(
                f"{self.name} returned invalid version information."
            ) from exc
        value = payload.get("version") if isinstance(payload, dict) else None
        if not isinstance(value, str):
            raise GeneratorProviderError(
                f"{self.name} returned invalid version information."
            )
        return GeneratorVersion.parse(value)

    def build_command(self, source: str, output_format: str) -> list[str]:
        output = {
            CYCLONEDX_JSON: "cyclonedx-json@1.6",
            SPDX_JSON: "spdx-json@2.3",
        }[output_format]
        return [self.executable, "scan", source, "--output", output]

    def environment(self) -> dict[str, str]:
        environment = super().environment()
        environment["SYFT_CHECK_FOR_APP_UPDATE"] = "false"
        environment["SYFT_CACHE_DIR"] = self.cache_directory("syft")
        return environment
