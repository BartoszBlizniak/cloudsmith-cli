# Nuitka standalone build entry point + config for the Cloudsmith CLI.
#
# Built natively per target (Nuitka cannot cross-compile, same as PyInstaller).
# --standalone produces a ``.dist/`` folder (renamed to ``cloudsmith/`` by the
# workflow), not --onefile: onefile re-extracts the payload on every run; the
# standalone folder starts immediately. Distributed as tar.gz/zip, matching the
# old PyInstaller onedir layout.
#
# Build config lives in the nuitka-project pragmas below (the analog of the old
# PyInstaller .spec): force-include the packages whose imports static analysis
# cannot see (keyring backends via entry points, the mcp subtree, the
# data-driven boto3/botocore SDKs), bundle package data + distribution
# metadata, and drop the test/CLI-only trees.
#
# nuitka-project: --standalone
# nuitka-project: --output-dir=dist
# nuitka-project: --output-filename=cloudsmith
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --include-package=cloudsmith_cli
# nuitka-project: --include-package-data=cloudsmith_cli
# nuitka-project: --include-package=keyring
# nuitka-project: --include-distribution-metadata=keyring
# nuitka-project: --include-package=mcp
# nuitka-project: --include-package-data=certifi
# nuitka-project: --include-distribution-metadata=cloudsmith-cli
# nuitka-project: --include-distribution-metadata=cloudsmith-api
# nuitka-project: --include-distribution-metadata=mcp
# nuitka-project: --nofollow-import-to=mcp.cli
# nuitka-project: --nofollow-import-to=cloudsmith_cli.cli.tests
# nuitka-project: --nofollow-import-to=cloudsmith_cli.core.tests
# nuitka-project: --nofollow-import-to=tkinter

import importlib
import os
import pkgutil
import sys

import cloudsmith_cli
from cloudsmith_cli.cli.commands.main import main


def _force_utf8_output() -> None:
    """Prevent UnicodeEncodeError on legacy Windows consoles.

    A frozen Windows console defaults to a legacy code page (e.g. cp1252) that
    cannot encode the check/cross/warning UI glyphs the CLI prints; without
    this, commands such as ``mcp configure`` and the download progress output
    crash with UnicodeEncodeError. Reconfiguring the streams to UTF-8 is a
    no-op on POSIX (already UTF-8) and is skipped when a stream cannot be
    reconfigured (e.g. a redirected non-text stream).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (ValueError, OSError):
                pass


def _selftest() -> int:
    """Import every bundled ``cloudsmith_cli`` module; fail on any ImportError.

    Runtime check that the compiled standalone build is complete:
    ``pkgutil.walk_packages`` enumerates the package inside the Nuitka bundle
    and each module is imported. A module the binary needs but Nuitka did not
    compile in surfaces here as an ImportError instead of crashing a user at
    runtime. Triggered only by the ``CLOUDSMITH_SELFTEST`` env var (set by the
    packaging smoketest), so it is never reachable as a normal CLI command.
    Data-file, dist-metadata, and dynamic-dispatch paths (which importing a
    module does not exercise) are covered by the functional smoketest steps,
    not here.

    Note: Nuitka compiles modules into the binary; if ``walk_packages`` cannot
    enumerate the compiled package (count == 0) this fails loudly so the
    packaging smoketest catches a broken sweep rather than silently passing.
    """
    failed = []

    def _is_test_module(name: str) -> bool:
        # Test packages are excluded from the binary (--nofollow-import-to).
        # Under Nuitka they stay enumerable but raise an "actively excluded"
        # ImportError on import; they are not runtime code, so the completeness
        # sweep skips them (PyInstaller dropped them from the bundle entirely).
        return "tests" in name.split(".")

    def _onerror(name):
        if _is_test_module(name):
            return
        failed.append(f"{name}: {sys.exc_info()[1]!r}")

    count = 0
    for info in pkgutil.walk_packages(
        cloudsmith_cli.__path__, "cloudsmith_cli.", onerror=_onerror
    ):
        if _is_test_module(info.name):
            continue
        count += 1
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # pylint: disable=broad-except
            failed.append(f"{info.name}: {exc!r}")

    if count == 0:
        failed.append("walk_packages enumerated 0 modules (frozen sweep broken)")

    for line in failed:
        print(f"SELFTEST missing: {line}")
    print(f"SELFTEST: {'FAIL' if failed else 'OK'} ({count} modules)")
    return 1 if failed else 0


if __name__ == "__main__":
    _force_utf8_output()
    if os.environ.get("CLOUDSMITH_SELFTEST"):
        sys.exit(_selftest())
    main()  # pylint: disable=no-value-for-parameter
