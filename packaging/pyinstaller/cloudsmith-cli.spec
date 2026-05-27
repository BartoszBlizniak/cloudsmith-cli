# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Cloudsmith CLI single-file/onedir binary."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# pyi `SPEC` is the absolute path to this spec file, set by PyInstaller.
SPEC_DIR = Path(SPEC).resolve().parent  # packaging/pyinstaller
REPO_ROOT = SPEC_DIR.parent.parent

ENTRY = str(REPO_ROOT / "scripts" / "cloudsmith_binary_entry.py")
PKG = REPO_ROOT / "cloudsmith_cli"

datas = []
# CLI package data: VERSION, default config/credentials, HTML templates.
datas += [
    (str(PKG / "data"), "cloudsmith_cli/data"),
    (str(PKG / "templates"), "cloudsmith_cli/templates"),
]
# certifi CA bundle — TLS validation needs cacert.pem at runtime.
datas += collect_data_files("certifi")

# importlib.metadata.version() probes for these distribution names. Without
# copy_metadata they raise PackageNotFoundError inside the frozen binary.
metadata_packages = [
    "cloudsmith-api",
    "cloudsmith-cli",
    "mcp",
    "keyring",
    "click",
    "requests",
    "rich",
    "semver",
]
for name in metadata_packages:
    try:
        datas += copy_metadata(name)
    except Exception as exc:  # pragma: no cover - best-effort metadata
        print(f"warning: copy_metadata({name!r}) failed: {exc}", file=sys.stderr)

# Hidden imports: PyInstaller's static analysis misses dynamic imports.
hiddenimports = []
# Skip mcp.cli — it imports typer at module top, which isn't a runtime dep.
hiddenimports += collect_submodules(
    "mcp", filter=lambda name: not name.startswith("mcp.cli")
)
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += [
    # keyring + secretstorage need explicit hints on some Linux variants.
    "keyring",
    "keyring.backend",
    "keyring.credentials",
    "jaraco.classes",
    "jaraco.context",
    "jaraco.functools",
    # Pydantic v2 native core sometimes needs explicit nudge.
    "pydantic",
    "pydantic_core",
    # cryptography is transitive (keyring → secretstorage on Linux); listed
    # explicitly so `check cryptography-selftest` works on every target.
    "cryptography",
    "cryptography.fernet",
    "cryptography.hazmat.bindings._rust",
    # MCP transport modules are imported lazily by name.
    "mcp.server.stdio",
    "mcp.server.fastmcp",
    "mcp.shared",
    # cloudsmith_cli's own dynamic command discovery.
    "cloudsmith_cli.cli.commands",
    "cloudsmith_cli.cli.commands.main",
    "cloudsmith_cli.core.mcp",
    "cloudsmith_cli.core.mcp.server",
]

# Platform-specific keyring backends.
if sys.platform.startswith("darwin"):
    hiddenimports += ["keyring.backends.macOS"]
elif sys.platform.startswith("linux"):
    hiddenimports += [
        "keyring.backends.SecretService",
        "keyring.backends.kwallet",
        "secretstorage",
    ]
elif sys.platform.startswith("win"):
    hiddenimports += ["keyring.backends.Windows"]

block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test/dev only — drop to shrink the binary.
        "pytest",
        "pylint",
        "isort",
        "flake8",
        "black",
        "mypy",
        "coverage",
        "pip",
        "setuptools._distutils",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# CLOUDSMITH_BINARY_MODE=onedir → folder bundle (fallback for AV/codesign issues).
# Anything else (default) → single-file executable.
ONEDIR = os.environ.get("CLOUDSMITH_BINARY_MODE", "onefile").lower() == "onedir"

if ONEDIR:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="cloudsmith",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="cloudsmith",
    )
else:
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
