"""Offline validation against the official supported SBOM schemas."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, FormatChecker
from jsonschema.exceptions import ValidationError, best_match
from referencing import Registry, Resource

from cloudsmith_cli.core import utils

from .contracts import CYCLONEDX_JSON, SPDX_JSON

_CYCLONEDX_SCHEMA_URI = "http://cyclonedx.org/schema/bom-1.6.schema.json"
_CYCLONEDX_REFERENCES = {
    "http://cyclonedx.org/schema/jsf-0.82.schema.json": (
        "cyclonedx-jsf-0.82.schema.json"
    ),
    "http://cyclonedx.org/schema/spdx.schema.json": (
        "cyclonedx-spdx-3.24.0.schema.json"
    ),
}
_SCHEMA_FILES = {
    CYCLONEDX_JSON: "cyclonedx-bom-1.6.schema.json",
    SPDX_JSON: "spdx-2.3.schema.json",
}


class SbomValidationError(Exception):
    """Raised when an SBOM does not conform to its official schema."""


def _load_schema(filename: str) -> dict[str, Any]:
    path = Path(utils.get_data_path(), filename)
    try:
        with path.open(encoding="utf-8") as schema_file:
            schema = json.load(schema_file)
    except (OSError, ValueError) as exc:  # pragma: no cover - packaging failure
        raise RuntimeError(
            f"Could not load bundled SBOM schema {filename}: {exc}"
        ) from exc
    if not isinstance(schema, dict):  # pragma: no cover - trusted bundled resource
        raise RuntimeError(f"Bundled SBOM schema {filename} is not a JSON object.")
    return schema


@lru_cache(maxsize=1)
def _validators() -> dict[str, Draft7Validator]:
    cyclone_schema = _load_schema(_SCHEMA_FILES[CYCLONEDX_JSON])
    registry = Registry().with_resource(
        _CYCLONEDX_SCHEMA_URI,
        Resource.from_contents(cyclone_schema),
    )
    for uri, filename in _CYCLONEDX_REFERENCES.items():
        registry = registry.with_resource(
            uri,
            Resource.from_contents(_load_schema(filename)),
        )

    return {
        CYCLONEDX_JSON: Draft7Validator(
            cyclone_schema,
            registry=registry,
            format_checker=FormatChecker(),
        ),
        SPDX_JSON: Draft7Validator(
            _load_schema(_SCHEMA_FILES[SPDX_JSON]),
            format_checker=FormatChecker(),
        ),
    }


def _json_path(error: ValidationError) -> str:
    path = "$"
    for element in error.absolute_path:
        if isinstance(element, int):
            path += f"[{element}]"
        else:
            path += f".{element}"
    return path


def _validation_message(error: ValidationError) -> str:
    """Render bounded diagnostics without echoing arbitrary document values."""
    if error.validator == "required":
        missing = next(
            (
                name
                for name in error.validator_value
                if isinstance(error.instance, dict) and name not in error.instance
            ),
            None,
        )
        return f"{missing} is required" if missing else "a required property is missing"
    if error.validator == "enum":
        return "value is not one of the allowed values"
    if error.validator == "type":
        return f"value must be of type {error.validator_value}"
    if error.validator == "pattern":
        return "value does not match the required pattern"
    if error.validator == "format":
        return f"value does not match the required {error.validator_value} format"
    return "document violates a schema constraint"


def validate_document(payload: dict[str, Any], output_format: str) -> None:
    """Validate one document using only bundled, version-pinned schemas."""
    validator = _validators().get(output_format)
    if validator is None:  # pragma: no cover - guarded by the CLI contract
        raise ValueError(f"Unsupported SBOM format: {output_format}")

    error = best_match(validator.iter_errors(payload))
    if error is None:
        return

    label = "CycloneDX 1.6" if output_format == CYCLONEDX_JSON else "SPDX 2.3"
    raise SbomValidationError(
        f"{label} schema validation failed at {_json_path(error)}: "
        f"{_validation_message(error)}"
    )
