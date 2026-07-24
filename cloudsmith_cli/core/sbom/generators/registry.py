"""Registry for supported external SBOM generators."""

from __future__ import annotations

from cloudsmith_cli.core.sbom.generators.base import (
    ExternalGenerator,
    GeneratorProviderError,
)
from cloudsmith_cli.core.sbom.generators.syft import SyftGenerator
from cloudsmith_cli.core.sbom.generators.trivy import TrivyGenerator

_GENERATORS: dict[str, type[ExternalGenerator]] = {
    SyftGenerator.name: SyftGenerator,
    TrivyGenerator.name: TrivyGenerator,
}
AUTO_GENERATOR = "auto"
DEFAULT_GENERATOR = SyftGenerator.name
GENERATOR_NAMES = (AUTO_GENERATOR, *_GENERATORS)


def get_generator(name: str, output_format: str | None = None) -> ExternalGenerator:
    """Resolve a named generator, or the first compatible provider for auto."""
    if name == AUTO_GENERATOR:
        installed = False
        format_supported = False
        compatibility_errors: list[str] = []
        for provider_type in _GENERATORS.values():
            provider = provider_type.discover()
            if not provider:
                continue
            installed = True
            if (
                output_format is not None
                and output_format not in provider.supported_formats
            ):
                continue
            format_supported = True
            try:
                provider.ensure_compatible()
            except GeneratorProviderError as exc:
                compatibility_errors.append(str(exc))
                continue
            return provider
        if compatibility_errors:
            details = "; ".join(compatibility_errors)
            format_scope = f" for '{output_format}'" if output_format else ""
            raise GeneratorProviderError(
                "No compatible installed SBOM generator is qualified"
                f"{format_scope}. {details}"
            )
        if installed and output_format is not None and not format_supported:
            raise GeneratorProviderError(
                "No installed SBOM generator supports "
                f"'{output_format}'. Install Syft or select a supported format."
            )
        raise GeneratorProviderError(
            "No supported SBOM generator is installed. Install Syft or select Trivy."
        )

    provider_type = _GENERATORS.get(name)
    if provider_type is None:
        choices = ", ".join(GENERATOR_NAMES)
        raise GeneratorProviderError(
            f"Unknown SBOM generator '{name}'. Choose from: {choices}."
        )
    provider = provider_type.discover()
    if provider is None:
        raise GeneratorProviderError(
            f"SBOM generator '{name}' is not installed. Install "
            f"{provider_type.executable_name} or select another generator."
        )
    return provider
