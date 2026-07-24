"""Tests for external SBOM generator providers."""

import os
import subprocess
import sys
import threading
import time
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from cloudsmith_cli.core.sbom.generators.base import (
    MAX_ERROR_BYTES,
    GeneratorProviderError,
    GeneratorVersion,
    _OutputLimitExceeded,
    _run_bounded,
)
from cloudsmith_cli.core.sbom.generators.registry import get_generator
from cloudsmith_cli.core.sbom.generators.syft import SyftGenerator
from cloudsmith_cli.core.sbom.generators.trivy import TrivyGenerator


def completed(
    stdout: str, stderr: str = "", returncode: int = 0
) -> CompletedProcess[bytes]:
    """Return a binary subprocess result."""
    return CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout.encode(),
        stderr=stderr.encode(),
    )


def test_generator_version_parses_prerelease():
    version = GeneratorVersion.parse("Application: syft\nVersion: v1.49.0-rc.1")
    assert version.release == (1, 49, 0)
    assert version.raw == "1.49.0-rc.1"
    assert version.prerelease is True


def test_generator_version_error_is_bounded_and_redacted():
    output = "token=super-secret " "https://user:password@example.invalid/version " + (
        "x" * (MAX_ERROR_BYTES * 2)
    )

    with pytest.raises(GeneratorProviderError) as exc_info:
        GeneratorVersion.parse(output)

    message = str(exc_info.value)
    assert "super-secret" not in message
    assert "user:password" not in message
    assert "https://" not in message
    assert len(message) < MAX_ERROR_BYTES + 100


@patch("cloudsmith_cli.core.sbom.generators.base._run_bounded")
def test_syft_generation_pins_schema_and_checks_version(mock_run):
    mock_run.side_effect = [
        completed('{"version":"1.49.0"}'),
        completed('{"bomFormat":"CycloneDX","specVersion":"1.6"}'),
    ]

    result = SyftGenerator("/opt/syft").generate(".", "cyclonedx-json")

    assert result.generator == "syft"
    assert result.generator_version == "1.49.0"
    assert mock_run.call_args_list[0].args[0] == [
        "/opt/syft",
        "version",
        "-o",
        "json",
    ]
    assert mock_run.call_args_list[1].args[0] == [
        "/opt/syft",
        "scan",
        ".",
        "--output",
        "cyclonedx-json@1.6",
    ]
    assert mock_run.call_args_list[1].kwargs["timeout"] == 300
    environment = mock_run.call_args_list[1].kwargs["environment"]
    assert environment["SYFT_CHECK_FOR_APP_UPDATE"] == "false"


@patch("cloudsmith_cli.core.sbom.generators.base._run_bounded")
def test_trivy_selects_image_and_keeps_json_on_stdout(mock_run):
    mock_run.side_effect = [
        completed("Version: 0.72.0"),
        completed('{"spdxVersion":"SPDX-2.3"}'),
    ]

    result = TrivyGenerator("/opt/trivy").generate(
        "example.invalid/image:1", "spdx-json"
    )

    assert result.generator == "trivy"
    assert mock_run.call_args_list[1].args[0] == [
        "/opt/trivy",
        "image",
        "--format",
        "spdx-json",
        "example.invalid/image:1",
    ]


def test_trivy_rejects_cyclonedx_until_the_contract_accepts_17():
    with pytest.raises(
        GeneratorProviderError,
        match=r"trivy does not support 'cyclonedx-json'.*spdx-json",
    ):
        TrivyGenerator("/opt/trivy").generate(".", "cyclonedx-json")


@patch(
    "cloudsmith_cli.core.sbom.generators.registry.SyftGenerator.discover",
    return_value=None,
)
@patch(
    "cloudsmith_cli.core.sbom.generators.registry.TrivyGenerator.discover",
    return_value=TrivyGenerator("/opt/trivy"),
)
def test_auto_falls_back_to_trivy_for_spdx(mock_trivy, _mock_syft):
    provider = mock_trivy.return_value
    with patch.object(
        provider,
        "ensure_compatible",
        return_value=GeneratorVersion.parse("0.72.0"),
    ) as mock_compatible:
        assert get_generator("auto", output_format="spdx-json") is provider
    mock_compatible.assert_called_once_with()


@patch(
    "cloudsmith_cli.core.sbom.generators.registry.SyftGenerator.discover",
    return_value=None,
)
@patch(
    "cloudsmith_cli.core.sbom.generators.registry.TrivyGenerator.discover",
    return_value=TrivyGenerator("/opt/trivy"),
)
def test_auto_skips_installed_provider_that_cannot_emit_format(_mock_trivy, _mock_syft):
    with pytest.raises(
        GeneratorProviderError,
        match="No installed SBOM generator supports 'cyclonedx-json'",
    ):
        get_generator("auto", output_format="cyclonedx-json")


@patch(
    "cloudsmith_cli.core.sbom.generators.registry.TrivyGenerator.discover",
    return_value=TrivyGenerator("/opt/trivy"),
)
@patch(
    "cloudsmith_cli.core.sbom.generators.registry.SyftGenerator.discover",
    return_value=SyftGenerator("/opt/syft"),
)
def test_auto_skips_unqualified_syft_and_uses_qualified_trivy(mock_syft, mock_trivy):
    syft = mock_syft.return_value
    trivy = mock_trivy.return_value
    with (
        patch.object(
            syft,
            "ensure_compatible",
            side_effect=GeneratorProviderError(
                "syft 1.48.0 is not a qualified stable release."
            ),
        ) as mock_syft_compatible,
        patch.object(
            trivy,
            "ensure_compatible",
            return_value=GeneratorVersion.parse("0.72.0"),
        ) as mock_trivy_compatible,
    ):
        assert get_generator("auto", output_format="spdx-json") is trivy

    mock_syft_compatible.assert_called_once_with()
    mock_trivy_compatible.assert_called_once_with()


@patch(
    "cloudsmith_cli.core.sbom.generators.registry.TrivyGenerator.discover",
    return_value=TrivyGenerator("/opt/trivy"),
)
@patch(
    "cloudsmith_cli.core.sbom.generators.registry.SyftGenerator.discover",
    return_value=SyftGenerator("/opt/syft"),
)
def test_auto_reports_each_incompatible_provider(mock_syft, mock_trivy):
    syft = mock_syft.return_value
    trivy = mock_trivy.return_value
    with (
        patch.object(
            syft,
            "ensure_compatible",
            side_effect=GeneratorProviderError(
                "syft 1.48.0 is not a qualified stable release."
            ),
        ),
        patch.object(
            trivy,
            "ensure_compatible",
            side_effect=GeneratorProviderError(
                "trivy 0.71.0 is not a qualified stable release."
            ),
        ),
        pytest.raises(GeneratorProviderError) as error,
    ):
        get_generator("auto", output_format="spdx-json")

    message = str(error.value)
    assert "No compatible installed SBOM generator" in message
    assert "syft 1.48.0" in message
    assert "trivy 0.71.0" in message


@patch(
    "cloudsmith_cli.core.sbom.generators.registry.TrivyGenerator.discover",
    return_value=None,
)
@patch(
    "cloudsmith_cli.core.sbom.generators.registry.SyftGenerator.discover",
    return_value=None,
)
def test_auto_requires_an_installed_generator(_mock_syft, _mock_trivy):
    with pytest.raises(
        GeneratorProviderError,
        match=r"No supported SBOM generator is installed\. Install Syft or Trivy\.",
    ):
        get_generator("auto", output_format="spdx-json")


@patch("cloudsmith_cli.core.sbom.generators.base._run_bounded")
def test_compatible_version_is_checked_once_per_provider(mock_run):
    mock_run.side_effect = [
        completed('{"version":"1.49.0"}'),
        completed('{"bomFormat":"CycloneDX","specVersion":"1.6"}'),
    ]
    provider = SyftGenerator("/opt/syft")

    assert provider.ensure_compatible().raw == "1.49.0"
    result = provider.generate(".", "cyclonedx-json")

    assert result.generator_version == "1.49.0"
    assert len(mock_run.call_args_list) == 2


@pytest.mark.parametrize("version", ["1.48.0", "1.49.0-rc.1", "2.0.0"])
@patch("cloudsmith_cli.core.sbom.generators.base._run_bounded")
def test_rejects_unqualified_or_prerelease_version(mock_run, version):
    mock_run.return_value = completed(f'{{"version":"{version}"}}')

    with pytest.raises(
        GeneratorProviderError,
        match=rf"syft {version} is not a qualified stable release.*syft 1.49.0",
    ):
        SyftGenerator("/opt/syft").generate(".", "cyclonedx-json")


@patch("cloudsmith_cli.core.sbom.generators.base._run_bounded")
def test_reports_generation_timeout(mock_run):
    mock_run.side_effect = [
        completed('{"version":"1.49.0"}'),
        subprocess.TimeoutExpired(["/opt/syft"], 300),
    ]

    with pytest.raises(GeneratorProviderError, match="timed out after 300 seconds"):
        SyftGenerator("/opt/syft").generate(".", "cyclonedx-json")


@patch("cloudsmith_cli.core.sbom.generators.base._run_bounded")
def test_reports_oversized_output(mock_run):
    mock_run.side_effect = [
        completed('{"version":"1.49.0"}'),
        _OutputLimitExceeded(),
    ]

    with pytest.raises(GeneratorProviderError, match="output limit"):
        SyftGenerator("/opt/syft").generate(".", "cyclonedx-json")


def test_bounded_reader_kills_process_at_output_limit():
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(b'x' * 100000)",
    ]

    with pytest.raises(_OutputLimitExceeded):
        _run_bounded(
            command,
            environment=None,
            timeout=10,
            output_limit=10,
            error_limit=10,
        )


def test_bounded_reader_enforces_timeout():
    command = [sys.executable, "-c", "import time; time.sleep(10)"]

    with pytest.raises(subprocess.TimeoutExpired):
        _run_bounded(
            command,
            environment=None,
            timeout=0.01,
            output_limit=10,
            error_limit=10,
        )


def test_bounded_reader_waits_for_stream_draining(monkeypatch):
    real_thread = threading.Thread
    reader_number = 0

    def delayed_thread(*args, **kwargs):
        nonlocal reader_number
        delay = 1.1 if reader_number == 0 else 0
        reader_number += 1
        target = kwargs["target"]

        def delayed_target(*target_args, **target_kwargs):
            time.sleep(delay)
            target(*target_args, **target_kwargs)

        return real_thread(
            *args,
            target=delayed_target,
            args=kwargs["args"],
            kwargs=kwargs["kwargs"],
            daemon=kwargs["daemon"],
        )

    monkeypatch.setattr(
        "cloudsmith_cli.core.sbom.generators.base.threading.Thread",
        delayed_thread,
    )

    completed_process = _run_bounded(
        [sys.executable, "-c", "print('complete')"],
        environment=None,
        timeout=3,
        output_limit=100,
        error_limit=100,
    )

    assert completed_process.stdout == b"complete\n"


@patch("cloudsmith_cli.core.sbom.generators.base._run_bounded")
def test_truncates_generator_errors(mock_run):
    mock_run.side_effect = [
        completed('{"version":"1.49.0"}'),
        completed("", "failure " + ("x" * 5_000), returncode=1),
    ]

    with pytest.raises(GeneratorProviderError) as error:
        SyftGenerator("/opt/syft").generate(".", "cyclonedx-json")
    assert len(str(error.value)) < 2_100


@patch("cloudsmith_cli.core.sbom.generators.base._run_bounded")
def test_redacts_urls_and_credentials_from_generator_errors(mock_run):
    mock_run.side_effect = [
        completed('{"version":"1.49.0"}'),
        completed(
            "",
            (
                "failed https://user:pass@example.invalid/image?token=secret "
                "Authorization=Bearer-secret"
            ),
            returncode=1,
        ),
    ]

    with pytest.raises(GeneratorProviderError) as error:
        SyftGenerator("/opt/syft").generate(".", "cyclonedx-json")
    message = str(error.value)
    assert "https://" not in message
    assert "user:pass" not in message
    assert "secret" not in message


def test_cache_directory_is_user_scoped_and_private(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    cache_dir = SyftGenerator.cache_directory("syft")

    user_id = os.getuid() if hasattr(os, "getuid") else os.getpid()
    root = tmp_path / f"cloudsmith-cli-{user_id}"
    assert cache_dir == str(root / "sbom" / "syft")
    assert root.stat().st_mode & 0o777 == 0o700


def test_cache_filesystem_failures_use_provider_error(tmp_path, monkeypatch):
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("file", encoding="utf-8")
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(occupied))

    with pytest.raises(GeneratorProviderError, match=r"Could not prepare.*syft cache"):
        SyftGenerator.cache_directory("syft")


def test_provider_controls_cache_without_dropping_registry_auth(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("SYFT_CACHE_DIR", "/untrusted/shared-cache")
    monkeypatch.setenv("SYFT_CHECK_FOR_APP_UPDATE", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "private-registry-identity")

    environment = SyftGenerator("/opt/syft").environment()

    assert environment["SYFT_CACHE_DIR"].startswith(str(tmp_path))
    assert environment["SYFT_CHECK_FOR_APP_UPDATE"] == "false"
    assert environment["AWS_ACCESS_KEY_ID"] == "private-registry-identity"
