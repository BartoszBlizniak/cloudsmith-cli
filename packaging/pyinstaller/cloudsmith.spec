# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller onefile spec for the Cloudsmith CLI single binary.
#
# Built per-target natively (PyInstaller cannot cross-compile). The output
# executable is named "cloudsmith"; the workflow renames it to the
# target-suffixed artifact name afterwards.
#
# The non-obvious parts are dynamic imports and metadata:
#   * cloudsmith_api resolves OpenAPI model/api classes by name -> needs all
#     submodules collected.
#   * keyring discovers backends through entry points -> needs the backend
#     submodules and the package metadata.
#   * cloudsmith_cli ships data files (data/VERSION, templates/) that the CLI
#     reads at runtime.
#   * mcp / pydantic pull a native pydantic_core extension.

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

datas = []
binaries = []
hiddenimports = []

# cloudsmith_cli: its submodules + data files (data/VERSION, templates/). Safe
# to collect whole -- the only optional-dep module (boto3 in the AWS OIDC
# detector) imports lazily inside methods, so importing the module is fine.
d, b, h = collect_all("cloudsmith_cli")
datas += d
binaries += b
hiddenimports += h

# cloudsmith_api resolves OpenAPI api/model classes by name at runtime.
hiddenimports += collect_submodules("cloudsmith_api")

# mcp: we use mcp.server.*; skip mcp.cli, which imports the optional `typer`
# dependency and would abort collection.
hiddenimports += collect_submodules("mcp", filter=lambda n: not n.startswith("mcp.cli"))
datas += collect_data_files("mcp")

# keyring backends are entry-point plugins; freeze them in explicitly.
hiddenimports += collect_submodules("keyring.backends")

# pydantic / pydantic_core (native ext) are handled by PyInstaller's built-in
# hooks once discovered via the mcp import graph -- no manual collect needed.

# Some libraries read their own dist metadata at runtime (importlib.metadata).
for dist in ("cloudsmith-cli", "cloudsmith-api", "mcp", "keyring"):
    try:
        datas += copy_metadata(dist)
    except Exception:  # pragma: no cover - metadata optional
        pass

a = Analysis(
    # Script paths in a spec are resolved relative to the spec file's dir.
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "pylint", "black", "isort"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="cloudsmith",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
