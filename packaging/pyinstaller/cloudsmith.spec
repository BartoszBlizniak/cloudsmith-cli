# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir spec for the Cloudsmith CLI. Built natively per target.
# onedir (not onefile): onefile re-extracts the whole bundle on every
# invocation (~6s/run); onedir starts in ~0.4s. Distributed as tar.gz/zip.

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

datas, binaries, hiddenimports = [], [], []

d, b, h = collect_all("cloudsmith_cli")
datas += d
binaries += b
hiddenimports += h

hiddenimports += collect_submodules("cloudsmith_api")
# mcp.cli imports the optional `typer` dependency; exclude it.
hiddenimports += collect_submodules("mcp", filter=lambda n: not n.startswith("mcp.cli"))
datas += collect_data_files("mcp")
hiddenimports += collect_submodules("keyring.backends")

for dist in ("cloudsmith-cli", "cloudsmith-api", "mcp", "keyring"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "pylint", "black", "isort"],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cloudsmith",
    console=True,
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="cloudsmith",
    strip=False,
    upx=False,
)
