# PyInstaller Binary PoC — Execution Results

Generated: 2026-05-21
Branch: `binary-poc` on `BartoszBlizniak/cloudsmith-cli`
Source plan: `research_2.md`
Tooling: PyInstaller **6.20.0** (latest at execution time), Python **3.12**

## TL;DR

- **All 8 target platforms produced a working single-file binary in GitHub Actions, with zero onedir fallbacks.**
- Every artifact ran `--version`, `--help`, command-specific help, `check service` (live TLS to `api.cloudsmith.io`), and `mcp start` JSON-RPC initialize — all on hosts/containers with **no Python on `PATH`**.
- Total CI wall-clock for the full matrix: ~5 minutes per push.
- `research_2.md`'s prediction that PyInstaller would clear the platform matrix held up; the one risk it called out (Windows being the deciding factor against PEX scie) is the same reason PyInstaller wins in execution.
- Only material deviation from the plan: GitHub's hosted runners refuse to run JavaScript actions (e.g. `actions/checkout`) inside Alpine containers on ARM64 (`"JavaScript Actions in Alpine containers are only supported on x64 Linux runners"`). The `linux-arm64-musl` target was therefore moved into its own job that runs on `ubuntu-24.04-arm` and shells out to `docker run python:3.12-alpine` for the build.

## Artifacts (run [26224885317](https://github.com/BartoszBlizniak/cloudsmith-cli/actions/runs/26224885317))

All artifacts are onefile binaries with `CLOUDSMITH_BINARY_MODE=onefile`.

| Target | Runner | Size | Cold `--version` × 3 | SHA-256 |
|---|---|---:|---:|---|
| `linux-amd64-glibc` | `ubuntu-latest` | 38 MB | 1.21 / 1.20 / 1.21 s | `e8bb34db…` |
| `linux-arm64-glibc` | `ubuntu-24.04-arm` | 37 MB | 0.93 / 0.97 / 0.94 s | `836d7b70…` |
| `linux-amd64-musl` | `ubuntu-latest` + `python:3.12-alpine` container | 25 MB | 1.16 / 1.17 / 1.17 s | `d0c3fb29…` |
| `linux-arm64-musl` | `ubuntu-24.04-arm` host + `docker run python:3.12-alpine` | 25 MB | 1.01 / 1.05 / 1.06 s | `6fed5586…` |
| `macos-arm64` | `macos-latest` (Apple Silicon) | 19 MB | 0.66 / 0.76 / ~0.8 s | `f3b4fdf8…` |
| `macos-amd64` | `macos-15-intel` | 20 MB | 2.24 / 2.19 / ~2.2 s | `b3c3cc8c…` |
| `windows-amd64` | `windows-latest` | 20 MB | ~2 s | `4a2875a9…` |
| `windows-arm64` | `windows-11-arm` | 20 MB | ~2 s | `06199108…` |

`SHA256SUMS` is published as a separate artifact alongside the binaries.

## What was added to the repo

Branch `binary-poc` (1 PoC commit + 1 CI fix commit):

```
.github/workflows/binary-poc.yml         # 8-target matrix + arm64-musl job + SHA256SUMS
packaging/pyinstaller/cloudsmith-cli.spec # data, templates, certifi, metadata, hidden imports
scripts/cloudsmith_binary_entry.py       # PyInstaller entry script
cloudsmith_cli/cli/commands/mcp.py       # sys.frozen branch in _get_server_config()
.typos.toml                              # whitelist PyInstaller's `datas` keyword
```

## Validation evidence (per target)

For every target the CI job ran, in order:

1. `cloudsmith --version` → prints `CLI Package Version: 1.17.0` + `API Package Version: 2.0.25`.
2. `cloudsmith --help`, `cloudsmith list repos --help`, `cloudsmith push raw --help`, `cloudsmith mcp --help` → all exit 0.
3. `CLOUDSMITH_NO_KEYRING=1 cloudsmith check service` → live TLS handshake to `api.cloudsmith.io`, response `"Cloudsmith API is operational"`. This is the strongest TLS/CA-bundle test in the matrix.
4. `printf '{"jsonrpc":"2.0",…initialize…}' | cloudsmith mcp start` → returns `{"jsonrpc":"2.0","id":1,"result":{…serverInfo:{"name":"Cloudsmith MCP Server","version":"1.9.1"}}}`. MCP transport modules (`mcp.server.stdio`, `mcp.server.fastmcp`) loaded inside the frozen binary.
5. Cold-start `--version` measured 3× (`/usr/bin/time -p` on POSIX, `Measure-Command` on Windows).

Additionally, the explicit **no-Python** step:

- **Linux glibc**: ran the artifact inside `debian:stable-slim` (no `python` or `python3` on `PATH`) and asserted `! command -v python` / `! command -v python3`. Output: `CLI Package Version: 1.17.0`.
- **Linux musl (amd64)**: same, executed inside the build container itself with `PATH` stripped via `env -i`.
- **Linux musl (arm64)**: same as above, inside the `docker run python:3.12-alpine` invocation.
- **macOS (both archs)**: `env -i PATH=/tmp/no-py HOME=/tmp ./cloudsmith --version` succeeded.
- **Windows (both archs)**: `$env:PATH = "C:\no-py"; .\cloudsmith.exe --version` succeeded.

No artifact required onedir fallback.

## Differences from the research_2.md predictions

| Prediction in `research_2.md` | What happened in execution | Impact |
|---|---|---|
| "PyInstaller onefile POC failed in this macOS sandbox with a semaphore initialization error." | Onefile built and ran on `macos-latest` (M1) **and** locally on the same Mac with no semaphore error. | None. Treat the prior failure as environment-specific. Onefile is the working default. |
| "Use Python 3.12 for parity with the current Docker image. Python 3.13/3.14 can be evaluated after the packaging path is proven." | CI uses 3.12 across all targets. Local build also worked on Python 3.14 with PyInstaller 6.20.0. | Path to 3.13/3.14 is open; 3.12 stays as the release baseline. |
| Spec includes `metadata for cloudsmith-api, cloudsmith-cli, mcp, keyring`. | Added the same plus `click`, `requests`, `rich`, `semver` defensively (cheap and silences any other `importlib.metadata.version()` call sites). | None. |
| `mcp` submodules collected as a group. | `collect_submodules("mcp")` walks `mcp.cli.cli`, which imports `typer` at module top. Filter out `mcp.cli` from the collection. | Spec now uses `collect_submodules("mcp", filter=lambda n: not n.startswith("mcp.cli"))`. |
| `cloudsmith mcp configure` should point at the binary, not `python -m cloudsmith_cli`. | Added `sys.frozen` branch to `_get_server_config()`. | Verified `sys.frozen` is True inside PyInstaller bundles. |
| Build matrix includes `linux-arm64-musl` via `container: python:3.12-alpine` on `ubuntu-24.04-arm`. | GitHub fails the step with `"JavaScript Actions in Alpine containers are only supported on x64 Linux runners"` before `actions/checkout` can run. | Split into a dedicated job that runs on the host and execs PyInstaller inside `docker run --platform linux/arm64 python:3.12-alpine`. Build + smoke + no-Python all happen inside that single `docker run`. |
| Spec uses `datas=` (PyInstaller's plural keyword). | Repo pre-commit `typos` hook auto-rewrote `datas` to `data`. | Added `datas` to `[default.extend-words]` plus an `extend-exclude` for `packaging/pyinstaller/*.spec`. |
| `pylint` ran in pre-commit. | `pylint` flagged `main()` in the entry script for `no-value-for-parameter` (false positive — `main` is a click command). | Added `# pylint: disable=no-value-for-parameter` to the call. |

Everything else in the plan held: data dirs, templates, certifi, metadata, keyring backends, MCP submodules, no UPX, `runtime_tmpdir=None`.

## Acceptance criteria from research_2.md

Each item is checked against the CI run that produced the artifacts.

- [x] Every required target builds in GitHub Actions — 8/8.
- [x] Every artifact runs with no Python on `PATH` — Linux glibc inside `debian:stable-slim`, Linux musl inside Alpine, macOS / Windows with stripped `PATH`.
- [x] `--version`, top-level `--help`, and representative command help work — `list repos --help`, `push raw --help`, `mcp --help` exercised.
- [x] `cloudsmith_cli/data/*` and `cloudsmith_cli/templates/*` available at runtime — `--version` reads `VERSION` via `get_data_path()`.
- [x] `cloudsmith_api` version metadata works — `importlib.metadata.version("cloudsmith_api")` returns `2.0.25`.
- [x] `mcp` imports and stdio startup work — JSON-RPC initialize completes on every target.
- [x] TLS validation to `api.cloudsmith.io` works — `check service` returns operational on every target with `CLOUDSMITH_NO_KEYRING=1`.
- [x] Keyring either works or can be cleanly disabled in headless environments — `CLOUDSMITH_NO_KEYRING=1` honored everywhere.
- [x] Windows x86_64 artifact runs on `windows-latest` — `--version` + `check service` succeed.
- [x] Alpine/musl artifacts run in `alpine:latest`/`python:3.12-alpine` — both amd64 and arm64.
- [x] Artifact size, startup time, checksum recorded — see table above.
- [x] Onefile artifacts pass — onedir fallback unused.
- [ ] SBOM emitted — **not yet**. The plan defers SBOM to release workflow shape; SHA256SUMS is the only attestation in the PoC.

## Open items / next steps before this becomes a release path

1. **Authenticated workflow.** Smoke tests deliberately stayed at `check service`. Confirm push/pull against a real Cloudsmith repo (e.g. `bartoszblizniak/binary-poc`) with `CLOUDSMITH_API_KEY` set in repo secrets. The plan's Phase 4 `cloudsmith push raw … && cloudsmith download raw …` script is ready to drop into the workflow once the repo exists in your namespace.
2. **Code signing.**
   - macOS: codesign + notarize before public distribution (Gatekeeper will quarantine downloads otherwise).
   - Windows: Authenticode sign to defuse SmartScreen; UPX intentionally disabled in the spec.
   - Linux: not signed; cover via SHA256SUMS + GH artifact attestations.
3. **AV/SmartScreen telemetry.** Submit `cloudsmith-windows-amd64.exe` to Microsoft Defender / SmartScreen for warm-up before public release.
4. **macOS `universal2`.** The plan calls this an optimization. Two arch-specific binaries already work; combining them is `lipo -create` + a small spec change, but only worth it after each arch is signed and notarized.
5. **Runtime-only requirements file.** The PoC installs `requirements.txt` (dev + runtime) before building. Per the plan: produce a `requirements-runtime.txt` / `constraints-runtime.txt` to shrink the freeze and reduce CVE surface in the binary.
6. **Onefile startup on macOS amd64 and Windows.** Cold start is ~2 s on those targets vs ≤1 s on Linux/macOS-arm64. Onedir typically halves Windows cold start (no per-launch extraction) — worth re-running the workflow with `mode=onedir` via `workflow_dispatch` and comparing before committing onefile across the board.
7. **`cloudsmith-cli-action` resolution layer.** Plan section "Auto-resolution plan" — wire the action to download the right artifact by `os/arch/libc` with SHA256 verification. Not in scope for this PoC.
8. **SBOM + provenance.** Add `anchore/sbom-action` (Syft) and `actions/attest-build-provenance` after the artifact shape is locked.

## Reproducing locally (macOS arm64)

```bash
git checkout binary-poc
python3.12 -m venv .venv && . .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -e .
pip install pyinstaller==6.20.0
# default: single-file
pyinstaller --clean --noconfirm packaging/pyinstaller/cloudsmith-cli.spec
# fallback: folder bundle
CLOUDSMITH_BINARY_MODE=onedir pyinstaller --clean --noconfirm packaging/pyinstaller/cloudsmith-cli.spec
./dist/cloudsmith --version
```

Local builds on this developer Mac (Python 3.14, Apple Silicon):

| Mode | Size | Cold `--version` |
|---|---:|---:|
| onefile | 22 MB | 6.7 s (first run; subsequent runs similar — onefile extracts on every launch) |
| onedir | 37 MB total, 13 MB launcher | 7.0 s |

(The CI macOS-arm64 numbers are far lower because `actions/setup-python` lays down a pristine 3.12, and the runner doesn't pay any first-run Gatekeeper translocation cost the way a locally built unsigned binary does on a developer machine.)

## Verdict against the plan

PyInstaller 6.20.0 is the right pick. The execution confirmed all of `research_2.md`'s assumptions, with one workflow-only correction (ARM64 Alpine container limitation) and no fallbacks needed for the artifact mode. The PoC artifacts are now sitting under run 26224885317 in `BartoszBlizniak/cloudsmith-cli`, ready to be promoted into the upstream release workflow alongside the existing `cloudsmith.pyz` and Docker pipelines.
