"""Shared contracts and safeguards for external SBOM generators."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloudsmith_cli.core.sbom.contracts import SBOM_FORMATS

GENERATION_TIMEOUT_SECONDS = 300
VERSION_TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 50 * 1024 * 1024
MAX_ERROR_BYTES = 2_000
_READ_CHUNK_BYTES = 64 * 1024

_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


class GeneratorProviderError(Exception):
    """Raised when an external generator cannot safely produce an SBOM."""


@dataclass(frozen=True)
class GeneratorVersion:
    """A detected external generator version."""

    raw: str
    major: int
    minor: int
    patch: int
    prerelease: bool

    @classmethod
    def parse(cls, value: str) -> GeneratorVersion:
        """Parse the first semantic version in a generator's output."""
        match = re.search(r"\bv?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?\b", value)
        if not match:
            detail = _redact_error(value[:MAX_ERROR_BYTES])
            raise GeneratorProviderError(
                f"Could not determine the SBOM generator version from: {detail!r}"
            )
        raw = match.group(0).removeprefix("v")
        return cls(
            raw=raw,
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease="-" in raw,
        )

    @property
    def release(self) -> tuple[int, int, int]:
        """Return the comparable release tuple."""
        return self.major, self.minor, self.patch


@dataclass(frozen=True)
class GeneratedSbom:
    """An SBOM and the external tool that produced it."""

    payload: dict[str, Any]
    generator: str
    generator_version: str


class ExternalGenerator(ABC):
    """Base class for a versioned command-line SBOM generator."""

    name: str
    executable_name: str
    qualified_versions: frozenset[tuple[int, int, int]]
    supported_formats = frozenset(SBOM_FORMATS)

    def __init__(self, executable: str):
        self.executable = executable
        self._compatible_version: GeneratorVersion | None = None

    @classmethod
    def discover(cls) -> ExternalGenerator | None:
        """Return a provider using the executable resolved from PATH."""
        executable = shutil.which(cls.executable_name)
        return cls(executable) if executable else None

    def generate(self, source: str, output_format: str) -> GeneratedSbom:
        """Check compatibility, execute the tool, and decode its JSON output."""
        if output_format not in self.supported_formats:
            supported = ", ".join(sorted(self.supported_formats))
            raise GeneratorProviderError(
                f"{self.name} does not support '{output_format}'. "
                f"Supported formats: {supported}."
            )

        version = self.ensure_compatible()
        command = self.build_command(source, output_format)
        completed = self._run(
            command,
            timeout=GENERATION_TIMEOUT_SECONDS,
            environment=self.environment(),
            operation="generate an SBOM",
        )
        try:
            payload = json.loads(completed.stdout)
        except ValueError as exc:
            raise GeneratorProviderError(
                f"{self.name} returned invalid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise GeneratorProviderError(
                f"{self.name} returned a non-object JSON document."
            )
        return GeneratedSbom(
            payload=payload,
            generator=self.name,
            generator_version=version.raw,
        )

    def ensure_compatible(self) -> GeneratorVersion:
        """Return the detected version or require a stable qualified release."""
        if self._compatible_version is not None:
            return self._compatible_version

        version = self.version()
        if version.prerelease or version.release not in self.qualified_versions:
            qualified = ", ".join(
                ".".join(str(part) for part in release)
                for release in sorted(self.qualified_versions)
            )
            raise GeneratorProviderError(
                f"{self.name} {version.raw} is not a qualified stable release. "
                f"Install {self.name} {qualified}."
            )
        self._compatible_version = version
        return version

    def environment(self) -> dict[str, str]:
        """Preserve registry authentication while providers control their settings.

        Registry tools use many ecosystem-specific variables for private images and
        package indexes. Removing unknown variables here would silently break those
        authenticated scans; providers override only settings affecting repeatable
        CLI execution.
        """
        return os.environ.copy()

    @abstractmethod
    def version(self) -> GeneratorVersion:
        """Detect the installed generator version."""

    @abstractmethod
    def build_command(self, source: str, output_format: str) -> list[str]:
        """Build the generation command."""

    def _run(
        self,
        command: list[str],
        *,
        timeout: int,
        environment: dict[str, str] | None = None,
        operation: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = _run_bounded(
                command,
                environment=environment,
                timeout=timeout,
                output_limit=MAX_OUTPUT_BYTES,
                error_limit=MAX_ERROR_BYTES,
            )
        except subprocess.TimeoutExpired as exc:
            raise GeneratorProviderError(
                f"{self.name} timed out after {timeout} seconds while trying to "
                f"{operation}."
            ) from exc
        except _OutputLimitExceeded as exc:
            raise GeneratorProviderError(
                f"{self.name} exceeded the {MAX_OUTPUT_BYTES}-byte output limit "
                f"while trying to {operation}."
            ) from exc
        except OSError as exc:
            detail = _redact_error(str(exc)[:MAX_ERROR_BYTES])
            raise GeneratorProviderError(
                f"{self.name} failed to {operation}: {detail}"
            ) from exc

        stdout_text = completed.stdout.decode("utf-8", errors="replace")
        stderr_text = completed.stderr[:MAX_ERROR_BYTES].decode(
            "utf-8", errors="replace"
        )
        result = subprocess.CompletedProcess(
            command,
            completed.returncode,
            stdout=stdout_text,
            stderr=stderr_text,
        )
        if result.returncode:
            detail = _redact_error(stderr_text) or "generator exited unsuccessfully"
            raise GeneratorProviderError(f"{self.name} failed to {operation}: {detail}")
        return result

    @staticmethod
    def cache_directory(name: str) -> str:
        """Return a private, user-scoped generator cache directory."""
        try:
            user_id = os.getuid() if hasattr(os, "getuid") else os.getpid()
            root = Path(tempfile.gettempdir()) / f"cloudsmith-cli-{user_id}"
            root.mkdir(mode=0o700, exist_ok=True)
            stat = root.stat()
            if hasattr(os, "getuid") and stat.st_uid != os.getuid():
                raise GeneratorProviderError(
                    "The SBOM generator cache directory is not owned by the "
                    "current user."
                )
            root.chmod(0o700)
            cache_dir = root / "sbom" / name
            cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            return str(cache_dir)
        except OSError as exc:
            raise GeneratorProviderError(
                f"Could not prepare the private {name} cache: {exc.strerror or exc}."
            ) from exc


class _OutputLimitExceeded(Exception):
    """Raised after terminating a process whose stdout exceeds its limit."""


def _run_bounded(
    command: list[str],
    *,
    environment: dict[str, str] | None,
    timeout: float,
    output_limit: int,
    error_limit: int,
) -> subprocess.CompletedProcess[bytes]:
    """Run a process while concurrently draining and strictly bounding output."""
    # A context manager can wait indefinitely during __exit__; lifecycle and
    # timeout cleanup are deliberately controlled below.
    process = subprocess.Popen(  # noqa: S603  # pylint: disable=consider-using-with
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    if process.stdout is None or process.stderr is None:  # pragma: no cover
        process.kill()
        raise OSError("could not capture generator output")
    deadline = time.monotonic() + timeout

    stdout = bytearray()
    stderr = bytearray()
    output_exceeded = threading.Event()

    def drain(stream, destination: bytearray, limit: int, *, fatal: bool) -> None:
        try:
            while chunk := stream.read(_READ_CHUNK_BYTES):
                remaining = limit - len(destination)
                if remaining > 0:
                    destination.extend(chunk[:remaining])
                if fatal and len(chunk) > remaining:
                    output_exceeded.set()
                    with suppress(OSError):
                        process.kill()
        except (OSError, ValueError):
            pass

    readers = (
        threading.Thread(
            target=drain,
            args=(process.stdout, stdout, output_limit),
            kwargs={"fatal": True},
            daemon=True,
        ),
        threading.Thread(
            target=drain,
            args=(process.stderr, stderr, error_limit),
            kwargs={"fatal": False},
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    def finish_readers() -> bool:
        for reader in readers:
            remaining = max(0.0, deadline - time.monotonic())
            reader.join(timeout=remaining)
        return all(not reader.is_alive() for reader in readers)

    try:
        returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as exc:
        with suppress(OSError):
            process.kill()
        process.wait()
        finish_readers()
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=bytes(stdout),
            stderr=bytes(stderr),
        ) from exc

    if not finish_readers():
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=bytes(stdout),
            stderr=bytes(stderr),
        )
    if output_exceeded.is_set():
        raise _OutputLimitExceeded
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
    )


def _redact_error(value: str) -> str:
    """Remove common credentials and URLs from external-tool diagnostics."""
    value = _URL.sub("[REDACTED URL]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", value)
    return value.strip()
