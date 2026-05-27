# Final Research: Cloudsmith CLI Python-Free Binary Packaging Decision

Generated: 2026-05-21T10:30:40Z

Input reports compared:

- `docs/cloudsmith-cli-single-binary-research-findings-2026-05-20.md`
- `cloudsmith-cli-single-binary-research-findings-20260520T143536Z.md`

## Executive decision

**Winner: PyInstaller 6.20.0, targeting one-file executables where validation passes, with onedir archives retained as the operational fallback.**

Both input research reports correctly rejected the current `cloudsmith.pyz` as Python-free, because it is a PEX zipapp with a `#!/usr/bin/env python3` shebang. Both reports also converged on PEX scie as the first-choice candidate because it is easy to adopt from the current release workflow and because a local macOS arm64 POC worked without Python on `PATH`.

The final validation changes the overall winner: **current PEX scie does not cover Windows in the validated `PEX 2.95.2` platform list.** Local `pex --help` for `2.95.2` lists `--scie-platform` choices for Linux, musl Linux, and macOS only:

```text
linux-aarch64
musl-linux-aarch64
linux-armv7l
linux-powerpc64
linux-riscv64
linux-s390x
linux-x86_64
musl-linux-x86_64
macos-aarch64
macos-x86_64
```

Windows x86_64 is a current Cloudsmith CLI support target. That makes PEX scie an excellent POSIX candidate, but not the best overall winner for the stated requirement.

PyInstaller is the best overall choice because it satisfies the hard "no Python installed" requirement and has current upstream support for the full required OS/architecture/libc set: Linux glibc x86_64/aarch64, Linux musl x86_64/aarch64, macOS arm64/x86_64, Windows x86_64, and Windows arm64 as a tracked target. It requires more explicit packaging configuration than PEX scie, but that configuration is manageable and can live in a single `.spec` file.

## Decision against the user's criteria

| Criterion | PyInstaller assessment | Decision impact |
|---|---|---|
| Easy setup and use | Moderate. More configuration than PEX scie, but standard for Python CLIs: one entry script, one `.spec`, data files, metadata, and hidden imports. | Acceptable. PEX is easier, but does not cover Windows scie output. |
| Outputs all currently required platforms | Yes, using native/per-target GitHub Actions builds. Linux musl must be built/tested in Alpine containers. | Primary reason PyInstaller wins. |
| One binary across multiple platforms | No true native option can produce one executable that runs across Linux, macOS, Windows, all CPU architectures, and glibc/musl. PyInstaller can produce one file per target. macOS `universal2` may be possible but must be proven with `pydantic-core` and all collected binaries. | Use per-platform artifacts plus auto-resolution in `cloudsmith-cli-action`. |
| No need to stay with PEX | PyInstaller is a clean switch for native artifacts while keeping PyPI, Docker, and existing `.pyz` during migration. | Adopt native binary path additively. |

## Comparison of the two input reports

| Finding | First report | Second report | Final validation |
|---|---|---|---|
| Current `.pyz` requires Python | Yes | Yes, locally validated with `PATH` stripped | Confirmed. Current `.pyz` is not sufficient. |
| Package data requirements | `cloudsmith_cli/data`, `templates`, metadata required | Same; PyInstaller failed without data/metadata | Confirmed. PyInstaller spec must make these explicit. |
| Native dependency risk | `pydantic-core`, `charset-normalizer`, `keyring` | Same, with local native extension scan | Confirmed. Tests must cover startup, MCP, TLS, and keyring. |
| PEX scie | Strong candidate | Strong candidate with successful macOS arm64 POC | Downgraded to runner-up because latest validated platform list lacks Windows. |
| PyInstaller | Candidate with risks | Candidate with risks; local onedir worked | Upgraded to winner because it covers the full platform matrix. |
| Nuitka | Needs investigation | Needs investigation | Remains third choice due build complexity, toolchain burden, and no local POC. |

## Latest-tool validation

### PyInstaller 6.20.0

Current local validation:

```text
.venv-single-binary-research/bin/pyinstaller --version
6.20.0
```

Relevant upstream state:

- PyInstaller documentation describes `-F/--onefile` and `-D/--onedir` build modes.
- PyInstaller documentation explicitly states it is **not a cross-compiler**. Build the executable on the target OS, or in a target-compatible container where appropriate.
- PyInstaller PyPI metadata for the current release line states that PyInstaller bundles a Python application and required libraries into one package without requiring a Python interpreter or modules to be installed by the user.
- Current PyInstaller distributions include wheels for macOS universal2, manylinux x86_64/aarch64, musllinux x86_64/aarch64, Windows x86_64, and Windows ARM64.
- Local PyInstaller onedir POC worked after adding an explicit entry script, `cloudsmith_cli/data`, `cloudsmith_cli/templates`, and metadata for `cloudsmith_api` and `cloudsmith-cli`.
- Local PyInstaller onefile POC failed in this macOS sandbox with a semaphore initialization error. Treat this as an environment-specific failure until GitHub Actions proves or disproves onefile on real runners.

Verdict: **validated enough to select as final POC winner, but not yet release-approved.**

### PEX scie 2.95.2

Current local validation:

```text
.venv-single-binary-research/bin/pex --version
2.95.2
```

Local POC from the second report:

```bash
pex . \
  --output-file /private/tmp/cloudsmith-scie \
  --console-script cloudsmith \
  --venv \
  --scie eager
```

This produced a macOS arm64 executable that embedded CPython and ran `--version` and `--help` with `PATH` stripped to a directory containing no Python.

Final validation issue:

- `PEX 2.95.2` exposes `--scie-platform` choices for Linux, musl Linux, and macOS.
- It does not expose Windows x86_64 or Windows ARM64 as scie targets in the validated tool output.

Verdict: **excellent runner-up for POSIX, not the overall winner while Windows is mandatory.**

### Nuitka 4.1.x

Nuitka remains a viable future investigation path because it can produce standalone/onefile applications and may have better Windows AV behavior than PyInstaller onefile. It is not the winner for this decision because:

- It needs a C/C++ toolchain on every build target.
- It has materially longer build times.
- It usually needs more dependency-specific flags and plugin tuning than PyInstaller.
- It was not locally proven against `cloudsmith-cli`.
- It is less transparent for SBOM and vulnerability scanning because Python code is compiled into native artifacts.

Verdict: **third choice, keep as fallback if PyInstaller fails materially.**

## Small decision matrix

| Option | No Python installed? | Full current platform coverage? | Configuration burden | GitHub Actions fit | Main blocker | Final status |
|---|---:|---:|---|---|---|---|
| **PyInstaller 6.20.0** | Yes | Yes, with native/container builds | Medium | Good | Onefile must be validated; signing/AV/keyring risks | **Winner** |
| PEX scie 2.95.2 | Yes on supported scie platforms | No, validated platform list lacks Windows | Low | Good for Linux/macOS | Windows scie target gap | Runner-up / POSIX-only candidate |
| Nuitka 4.1.x | Yes | Likely, but not proven here | High | Moderate | Toolchain, build time, tuning, SBOM opacity | Third choice |

## Required platform strategy

PyInstaller should be built on, or inside, the target platform. Do not attempt to generate the full release matrix from a developer Mac. Use GitHub Actions for the authoritative POC and release builds.

| Target | Build environment | Runtime validation environment | Notes |
|---|---|---|---|
| linux/amd64 glibc | x86_64 Linux runner, preferably a conservative glibc container such as manylinux or Debian stable | `debian:stable-slim` with no Python | Avoid building on too-new glibc if broad distro compatibility matters. |
| linux/arm64 glibc | Native ARM64 Linux runner or ARM64 Docker on ARM64 runner | ARM64 Debian slim with no Python | Prefer native ARM64 runner over QEMU for release confidence. |
| linux/amd64 musl / Alpine | x86_64 Alpine build container with Python and PyInstaller | `alpine:latest` with no Python | Must prove `pydantic-core`, `charset-normalizer`, TLS, and keyring behavior. |
| linux/arm64 musl / Alpine | ARM64 Alpine container on ARM64 runner | ARM64 Alpine with no Python | Highest Linux risk; make this a required POC target, not a later surprise. |
| macOS arm64 | `macos-latest` / Apple Silicon runner | PATH stripped to no Python | Sign/notarize before public distribution. |
| macOS x86_64 | Intel macOS runner | PATH stripped to no Python | Track `universal2` as an optimization only after separate x86_64 works. |
| Windows x86_64 | `windows-latest` | PATH stripped to no Python | Must test Defender/SmartScreen behavior after signing. |
| Windows arm64 | `windows-11-arm` runner if available | ARM64 Windows runner | Track as feasible; x86_64-on-ARM emulation is fallback. |

## Artifact model

Use one file per platform where onefile validation passes:

```text
cloudsmith-${VERSION}-linux-amd64-glibc
cloudsmith-${VERSION}-linux-arm64-glibc
cloudsmith-${VERSION}-linux-amd64-musl
cloudsmith-${VERSION}-linux-arm64-musl
cloudsmith-${VERSION}-macos-arm64
cloudsmith-${VERSION}-macos-amd64
cloudsmith-${VERSION}-windows-amd64.exe
cloudsmith-${VERSION}-windows-arm64.exe
SHA256SUMS
sbom-${VERSION}.cdx.json
```

If onefile fails on any target, publish an archive for that target:

```text
cloudsmith-${VERSION}-${TARGET}.tar.gz
cloudsmith-${VERSION}-${TARGET}.zip
```

The archive should still expose a top-level `cloudsmith` or `cloudsmith.exe` executable after extraction.

## Auto-resolution plan

Update `cloudsmith-cli-action` to prefer native artifacts, with `.pyz` and pip as fallback paths during migration.

Resolution logic:

| Runtime | Detection | Artifact |
|---|---|---|
| Linux x64 glibc | `process.platform == "linux"`, `process.arch == "x64"`, `getconf GNU_LIBC_VERSION` succeeds | `linux-amd64-glibc` |
| Linux x64 musl | Linux x64 and glibc detection fails or `ldd` reports musl | `linux-amd64-musl` |
| Linux ARM64 glibc | Linux arm64 and glibc detection succeeds | `linux-arm64-glibc` |
| Linux ARM64 musl | Linux arm64 and musl detection succeeds | `linux-arm64-musl` |
| macOS arm64 | `darwin` + `arm64` | `macos-arm64` |
| macOS x64 | `darwin` + `x64` | `macos-amd64` |
| Windows x64 | `win32` + `x64` | `windows-amd64.exe` |
| Windows ARM64 | `win32` + `arm64` | `windows-arm64.exe`, fallback to `windows-amd64.exe` if needed |

Download flow:

1. Resolve target.
2. Fetch artifact and `SHA256SUMS`.
3. Verify checksum before execution.
4. Mark executable on POSIX.
5. Add containing directory to `PATH`.
6. If native artifact is missing for a requested version, fall back to current `.pyz` behavior with a warning that Python is required.

## PyInstaller implementation shape

Add a tiny first-party entry script so PyInstaller does not need to freeze package-relative `__main__` behavior:

```python
from cloudsmith_cli.cli.commands.main import main

if __name__ == "__main__":
    main()
```

Use a `.spec` file instead of long CLI flags. This avoids platform-specific `--add-data` separator differences and keeps metadata/data collection explicit.

The spec should include:

- `cloudsmith_cli/data`
- `cloudsmith_cli/templates`
- `certifi` data
- metadata for `cloudsmith-api`, `cloudsmith-cli`, `mcp`, and `keyring`
- submodules for `mcp`
- submodules for `keyring.backends`
- platform-specific hidden imports discovered during POC

Initial command for agents:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
python -m pip install pyinstaller==6.20.0
pyinstaller --clean --noconfirm cloudsmith-cli.spec
```

Important: use a runtime-only lock or constraints file before this becomes a release workflow. The current `requirements.txt` includes dev/test/lint packages and should not be blindly frozen into production binaries.

## POC plan for agents

### Phase 1: Build the PyInstaller candidate

Create a branch that adds:

- `scripts/cloudsmith_binary_entry.py`
- `packaging/pyinstaller/cloudsmith-cli.spec`
- `.github/workflows/binary-poc.yml`
- optional `requirements-runtime.lock` or `constraints-runtime.txt`

The first pass should build with Python 3.12 for parity with the current Docker image. Python 3.13/3.14 can be evaluated after the packaging path is proven.

### Phase 2: GitHub Actions build matrix

Run the POC in GitHub Actions, not only from a Mac:

```yaml
strategy:
  fail-fast: false
  matrix:
    include:
      - target: linux-amd64-glibc
        runs-on: ubuntu-latest
      - target: linux-arm64-glibc
        runs-on: ubuntu-24.04-arm
      - target: linux-amd64-musl
        runs-on: ubuntu-latest
        container: python:3.12-alpine
      - target: linux-arm64-musl
        runs-on: ubuntu-24.04-arm
        container: python:3.12-alpine
      - target: macos-arm64
        runs-on: macos-latest
      - target: macos-amd64
        runs-on: macos-15-intel
      - target: windows-amd64
        runs-on: windows-latest
      - target: windows-arm64
        runs-on: windows-11-arm
```

If a runner label is unavailable in the repository, mark that target as blocked by runner access, not by PyInstaller.

### Phase 3: No-Python validation

Linux glibc:

```bash
docker run --rm -v "$PWD/dist:/work" -w /work debian:stable-slim sh -c '
  ! command -v python
  ! command -v python3
  ./cloudsmith --version
  ./cloudsmith --help
'
```

Linux musl:

```bash
docker run --rm -v "$PWD/dist:/work" -w /work alpine:latest sh -c '
  ! command -v python
  ! command -v python3
  ./cloudsmith --version
  ./cloudsmith --help
'
```

macOS:

```bash
mkdir -p /tmp/no-python-path /tmp/cloudsmith-clean-home
env -i PATH=/tmp/no-python-path HOME=/tmp/cloudsmith-clean-home ./cloudsmith --version
env -i PATH=/tmp/no-python-path HOME=/tmp/cloudsmith-clean-home ./cloudsmith --help
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force .\no-python-path
$env:PATH = "$pwd\no-python-path"
.\cloudsmith.exe --version
.\cloudsmith.exe --help
```

The validation should assert that `python` and `python3` are not discoverable before the artifact is executed.

### Phase 4: Functional smoke tests

Run on every artifact:

```bash
./cloudsmith --version
./cloudsmith --help
./cloudsmith list repos --help
./cloudsmith push raw --help
./cloudsmith mcp --help
```

TLS/CA behavior:

```bash
CLOUDSMITH_NO_KEYRING=1 ./cloudsmith whoami || true
```

Expected without credentials: an auth/config error, not a certificate validation error and not a missing CA bundle error.

MCP stdio:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n' | ./cloudsmith mcp serve
```

Auth/keyring:

```bash
CLOUDSMITH_NO_KEYRING=1 ./cloudsmith whoami
./cloudsmith login --api-key "$CLOUDSMITH_API_KEY"
./cloudsmith whoami
```

Upload/download test against a controlled repo:

```bash
printf 'binary-poc\n' > fixture.txt
./cloudsmith push raw "$CLOUDSMITH_NAMESPACE/$CLOUDSMITH_REPOSITORY" fixture.txt --name fixture.txt --version "$GITHUB_RUN_ID"
./cloudsmith download raw "$CLOUDSMITH_NAMESPACE/$CLOUDSMITH_REPOSITORY/fixture.txt/$GITHUB_RUN_ID" downloaded-fixture.txt
cmp fixture.txt downloaded-fixture.txt
```

### Phase 5: Size and startup measurements

Linux/macOS:

```bash
ls -lh ./cloudsmith
/usr/bin/time -p ./cloudsmith --version
HOME="$(mktemp -d)" /usr/bin/time -p ./cloudsmith --version
```

Windows:

```powershell
Get-Item .\cloudsmith.exe | Select-Object Name,Length
Measure-Command { .\cloudsmith.exe --version }
```

Record cold and warm startup separately.

## Acceptance criteria

The PyInstaller POC is successful only if all of the following are true:

- Every required target builds in GitHub Actions or has a documented runner-access blocker.
- Every artifact runs with no Python on `PATH`.
- `--version`, top-level `--help`, and representative command help work.
- `cloudsmith_cli/data/*` and `cloudsmith_cli/templates/*` are available at runtime.
- `cloudsmith_api` version metadata works.
- `mcp` imports and stdio startup work.
- TLS validation to `api.cloudsmith.io` works with the bundled/default CA strategy.
- Keyring either works or can be cleanly disabled in headless environments.
- Windows x86_64 artifact runs on `windows-latest`.
- Alpine/musl artifacts run in `alpine:latest`.
- Artifact size, startup time, checksum, and SBOM are recorded.
- Onefile artifacts pass. If onefile fails on any target, the report must identify whether onedir archive is acceptable for that target.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| PyInstaller onefile fails on a target | Fall back to onedir archive for that target; keep onefile as goal. |
| Windows AV/SmartScreen friction | Sign with Authenticode, avoid UPX, publish checksums/SBOM/provenance, submit false-positive reports if needed. |
| macOS Gatekeeper blocks downloads | Codesign and notarize public artifacts. |
| Linux glibc compatibility too narrow | Build in conservative glibc containers and test on Debian/Ubuntu baseline images. |
| Alpine/musl native extension issue | Build in Alpine, test in Alpine, pin wheels, and fail release if `pydantic-core` or `charset-normalizer` cannot load. |
| Keyring hangs or silently degrades in CI/headless Linux | Test `CLOUDSMITH_NO_KEYRING=1`, assert backend behavior, document headless mode. |
| CA bundle goes stale inside binary | Publish SBOM, rebuild on `certifi`/OpenSSL/Python security updates, support `SSL_CERT_FILE`. |
| Runtime dependency drift | Use runtime-only lock/constraints, not combined dev/test `requirements.txt`. |
| `cloudsmith mcp` config points at Python rather than binary | Patch `cloudsmith_cli/cli/commands/mcp.py` to detect frozen binaries and write the binary path. |

## Release workflow shape

Recommended migration:

1. Keep current `.pyz`, PyPI wheel/sdist, and Docker image.
2. Add PyInstaller native artifacts as beta assets for 2-3 releases.
3. Update `cloudsmith-cli-action` to prefer native artifacts by OS/arch/libc, with fallback to `.pyz`.
4. Update Docker to consume Linux musl or glibc native artifact after Alpine/glibc validation passes.
5. Add checksums, SBOM, provenance, and signing before declaring native binaries stable.
6. Deprecate `.pyz` only after at least one full release cycle with green binary telemetry and user feedback.

Required jobs:

- `build-binary-linux-amd64-glibc`
- `build-binary-linux-arm64-glibc`
- `build-binary-linux-amd64-musl`
- `build-binary-linux-arm64-musl`
- `build-binary-macos-arm64`
- `build-binary-macos-amd64`
- `build-binary-windows-amd64`
- `build-binary-windows-arm64` if runner access is available
- `smoke-test-binaries`
- `generate-checksums`
- `generate-sbom`
- `sign-artifacts`
- `publish-github-release`
- `publish-cloudsmith-raw`

## Final recommendation

Adopt **PyInstaller 6.20.0** as the final POC winner because it is the only evaluated option that currently satisfies both hard requirements at once:

1. Users can run the artifact without installing Python.
2. The tool can produce artifacts for the full current Cloudsmith platform matrix, including Windows.

PEX scie remains a strong technical path for Linux/macOS and may still be useful later if Windows support lands or if Cloudsmith decides to use a hybrid strategy. It should not be the primary final decision while Windows x86_64 is non-negotiable.

Nuitka should remain a reserve option, not the next action. Its build complexity is higher, and it does not yet have a Cloudsmith-specific POC.

## Appendix: commands used

```bash
sed -n '1,260p' docs/cloudsmith-cli-single-binary-research-findings-2026-05-20.md
sed -n '1,260p' cloudsmith-cli-single-binary-research-findings-20260520T143536Z.md
wc -l docs/cloudsmith-cli-single-binary-research-findings-2026-05-20.md cloudsmith-cli-single-binary-research-findings-20260520T143536Z.md
rg -n "Recommendation|Strong candidate|Candidate|PEX|scie|PyInstaller|Nuitka|winner|Recommended|Option:" docs/cloudsmith-cli-single-binary-research-findings-2026-05-20.md cloudsmith-cli-single-binary-research-findings-20260520T143536Z.md
.venv-single-binary-research/bin/pex --version
.venv-single-binary-research/bin/pex --help
.venv-single-binary-research/bin/pex --help | rg -n -C 3 -- "--scie"
.venv-single-binary-research/bin/pyinstaller --version
.venv-single-binary-research/bin/pyinstaller --help
date -u +%Y%m%dT%H%M%SZ
```

## Appendix: sources

Cloudsmith:

- https://github.com/cloudsmith-io/cloudsmith-cli
- https://github.com/cloudsmith-io/cloudsmith-cli/blob/master/.github/workflows/release.yml
- https://github.com/cloudsmith-io/cloudsmith-cli/tree/master/.github/.platforms
- https://github.com/cloudsmith-io/cloudsmith-cli/blob/master/setup.py
- https://github.com/cloudsmith-io/cloudsmith-cli/blob/master/requirements.in
- https://github.com/cloudsmith-io/cloudsmith-cli/blob/master/requirements.txt
- https://github.com/cloudsmith-io/cloudsmith-cli/blob/master/Dockerfile
- https://github.com/cloudsmith-io/cloudsmith-cli-action

Packaging tools:

- https://pyinstaller.org/en/stable/
- https://pyinstaller.org/en/stable/operating-mode.html
- https://pyinstaller.org/en/stable/usage.html
- https://pypi.org/project/pyinstaller/
- https://docs.pex-tool.org/scie.html
- https://docs.pex-tool.org/
- https://pypi.org/project/pex/
- https://nuitka.net/user-documentation/user-manual.html
- https://nuitka.net/user-documentation/use-cases.html
- https://pypi.org/project/Nuitka/

Release and security:

- https://docs.github.com/actions/reference/runners/github-hosted-runners
- https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations
- https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution
- https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool
- https://github.com/anchore/syft
