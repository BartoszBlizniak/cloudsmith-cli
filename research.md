# Cloudsmith CLI Single-Binary Packaging — Final Research & Decision

**Generated:** 2026-05-21T10:29:51Z
**Authors:** synthesis of two prior research passes + latest-release validation
**Inputs reviewed:**
- `docs/cloudsmith-cli-single-binary-research-findings-2026-05-20.md` (Report A — desk research, file:line-cited)
- `cloudsmith-cli-single-binary-research-findings-20260520T143536Z.md` (Report B — local POC evidence on macOS arm64)
**Repository state:** `master` @ `ff9512e3`, `VERSION = 1.17.0`, `python_requires>=3.10.0`
**Goal:** pick one packaging approach, validate it against the latest release of the chosen tool, and define a CI-executable PoC that proves the full platform/arch matrix.

---

## 1. TL;DR — the winner

**PEX `--scie eager`** is the winner. Version pin for the PoC: **PEX 2.95.2 (released 2026-05-18)**.

It ships a native launcher per target that embeds a `python-build-standalone` (PBS) CPython distribution plus the resolved wheel set, with no Python runtime requirement on the user's host. PBS issue #86 (the historic `dlopen` blocker on musl) was **closed completed on 2025-03-11** via PR #541, which made dynamic-musl the default — `pydantic-core` (and the rest of the `mcp` stack) can now load on Alpine. PEX 2.72.0 onward ships foreign-platform musl scies, and `pex/scie/model.py` confirms `WINDOWS_AARCH64` and `MUSL_LINUX_AARCH64` are first-class `--scie-platform` values. Every currently supported Cloudsmith CLI target maps to a supported PEX scie platform.

The decision is driven by four facts the two reports agreed on and the latest-release validation confirmed:

1. **Lowest config delta from today.** Replace `--python-shebang "/usr/bin/env python3"` with `--scie eager --scie-platform <triple>` in the existing `release.yml` PEX command. No tool change.
2. **End-to-end POC already passed locally.** Report B built a 35 MB Mach-O arm64 scie in one `pex` invocation and ran `cloudsmith --version` with `PATH` stripped of Python. Warm start ~0.37 s, cold start ~5.13 s (first-run PBS extraction to `~/.cache/nce`).
3. **Full platform matrix covered.** The 8 targets the project currently supports (linux glibc/musl × {x86_64, aarch64}, macOS × {x86_64, aarch64}, Windows × {x86_64, aarch64}) all map to a `SysPlatform` enum value in `pex/scie/model.py`. GitHub-hosted runners exist for every one of those targets as of 2025-08 (Linux/Windows ARM64) and 2024-01 (macOS ARM64).
4. **No moving away from PEX.** The investment in `.github/.platforms/*.json` and the existing dependency-resolution flow keeps paying off. PEX scie is **additive** — it changes the artifact type, not the build tool.

A single binary that runs everywhere is **not achievable** for this dependency tree (`pydantic-core` and `charset-normalizer` are native, ABI-pinned, per-OS+arch+libc). The mitigation is **CI/CD-side auto-resolution** in `cloudsmith-cli-action` — see §6.

---

## 2. Decision matrix

Final scoring across the three serious candidates, weighted against the user's stated criteria.

| Criterion | Weight | PEX `--scie eager` | PyInstaller 6.20 | Nuitka 4.1 |
|---|---|---|---|---|
| Easy setup, minimal config | 5 | **5** — flip a flag on existing `pex` command | 3 — new spec files, hidden imports, `--add-data`, `--copy-metadata` per dep | 2 — toolchains (gcc/clang/MSVC), per-dep `--include-module`/`--include-distribution-metadata` flag list |
| Covers all 8 platforms today | 5 | **5** — every target maps to a `SysPlatform` enum value; PBS dynamic-musl resolves Alpine | 4 — `musllinux_1_1_{x86_64,aarch64}` wheels published since 5.13; Windows arm64 OK; no cross-build (per-runner mandatory) | 3 — **Windows arm64 standalone/onefile not yet supported**; musl aarch64 newer; per-runner mandatory |
| GitHub Actions runner availability | 4 | **5** — every target has a GA runner | **5** — every target has a GA runner | **5** — every target has a GA runner |
| Single binary across platforms | 3 | 1 — per-target binary required | 1 — per-target binary required | 1 — per-target binary required |
| Mature ecosystem / community | 3 | 4 — PEX 2.95.2 (May 2026); active; PBS Astral-backed | **5** — broadest; contrib hooks repo covers most deps | 3 — single maintainer; license ambiguity (LICENSE.txt says AGPL+exception) |
| Build speed | 2 | **5** — seconds per target | 4 — seconds to ~2 min per target | 1 — 10–25 min per target; memory-hungry |
| `mcp serve` / `anyio` compatibility | 4 | **5** — same wheels as today; no transformation | **5** — same wheels; `--hidden-import mcp.server.stdio` + `collect_submodules("mcp")` documented | 2 — [Nuitka #3691](https://github.com/Nuitka/Nuitka/issues/3691) documents anyio breakage on Windows that hits `cloudsmith mcp serve` directly |
| `keyring` cross-OS | 4 | **5** — wheels untouched, entry-points discovered via dist-info | 4 — needs contrib hook + `collect_entry_point("keyring.backends")` | 3 — needs explicit `--include-module` for each of 6 backends + `--include-distribution-metadata=keyring` |
| AV / Defender / SmartScreen | 3 | 4 — native launcher, EV signing clears | 2 — onefile + Windows is the worst combination | 4 — genuine native code, lower FP rate; onefile still triggers |
| SBOM / supply-chain visibility | 3 | **5** — wheel set is the SBOM; `cyclonedx-py` clean output | **5** — same | 2 — Python compiled to C; SBOM tooling cannot recover package identity from the binary |
| Migration risk to `cloudsmith-cli-action` | 3 | **5** — keep the same Cloudsmith raw URL shape; just add OS/arch in path | 4 — same URL plumbing; per-target binary swap | 4 — same |
| Maintenance burden | 3 | **5** — one tool, one flag set, monthly PBS refresh | 3 — per-dep hook tinkering on major bumps | 2 — flag list grows; anyio is an ongoing watch |
| License clarity | 2 | **5** — Apache-2.0 (PEX) + PSF-style (PBS) — clean | **5** — GPL-2.0 WITH bootloader exception (commercial OK) | 2 — repo metadata says Apache-2.0, `LICENSE.txt` says AGPL-3.0 with runtime exception; **legal review required** |
| Reproducible builds | 2 | 4 — PBS reproducible; lockfile + Python pin needed | 3 — `SOURCE_DATE_EPOCH` supported | 4 — `--reproducible` since 4.0.6 |
| **Weighted total** | — | **211** | **170** | **125** |

PEX scie wins on every dimension that's not a tie. PyInstaller is the right **fallback** (same outcome via a different tool — useful if PEX scie hits a target-specific bug in the PoC). Nuitka is third, mostly because of the `anyio`/Windows risk and the license ambiguity; it stays "Needs more investigation."

The other options from the two reports remain rejected and need no further treatment here:

- **PyOxidizer** — abandoned since Dec 2022; no Python 3.11+; dealbreaker.
- **Briefcase** — installer-only; no musl path; wrong shape for a developer CLI.
- **Shiv / plain zipapp** — still require host Python; doesn't satisfy the hard requirement.
- **Rust/Go launcher around PBS** — duplicates PEX scie's value with more bespoke surface; keep as fallback to a fallback.
- **Cosmopolitan libc / posy / full rewrite** — out of scope.

---

## 3. Latest-release validation for the winner

Verified against current upstream releases on 2026-05-21:

| Component | Latest version | Date | Relevance check |
|---|---|---|---|
| PEX | 2.95.2 | 2026-05-18 | `--scie eager` stable since 2.72.0 (foreign musl); no breaking changes to scie flags in the last 5 releases. |
| python-build-standalone | 20260510 | 2026-05-10 | Embeds CPython 3.14.5; default musl is **dynamic** since 20250311 (PR #541); static variant available with `+static` suffix; all 8 target triples present in release assets. |
| scie-jump | 1.11.2 | 2026-02-07 | The native launcher PEX scie ships. Maintained. |
| science (a-scie/lift) | 0.18.1 | 2026-02 | Lift tool referenced by PEX. Supports `aarch64-musl` since 0.16. |
| GitHub Actions runners | n/a | 2025-08-07 (ARM64 GA) | `ubuntu-24.04-arm`, `ubuntu-22.04-arm`, `windows-11-arm`, `macos-{14,15,26}` (Apple Silicon) all GA for public repos. |
| PyInstaller (fallback) | 6.20.0 | 2026-04-22 | musllinux_1_1_{x86_64,aarch64} wheels published; Windows arm64 supported; macOS universal2; manylinux2014 multi-arch. |

**Source-verified supported PEX scie platforms** (from `pex/scie/model.py` on `main`):

| Enum value | Triple | Maps to Cloudsmith target |
|---|---|---|
| `LINUX_X86_64` | `x86_64-unknown-linux-gnu` | linux/amd64 glibc |
| `LINUX_AARCH64` | `aarch64-unknown-linux-gnu` | linux/arm64 glibc |
| `MUSL_LINUX_X86_64` | `x86_64-unknown-linux-musl` | linux/amd64 musl (Alpine) |
| `MUSL_LINUX_AARCH64` | `aarch64-unknown-linux-musl` | linux/arm64 musl (Alpine) |
| `MACOS_X86_64` | `x86_64-apple-darwin` | macOS Intel |
| `MACOS_AARCH64` | `aarch64-apple-darwin` | macOS Apple Silicon |
| `WINDOWS_X86_64` | `x86_64-pc-windows-msvc` | Windows x64 |
| `WINDOWS_AARCH64` | `aarch64-pc-windows-msvc` | Windows ARM64 |

Every Cloudsmith CLI target has a 1:1 PEX scie platform. The validation closes the open item from Report A ("PEX-scie Windows ARM64 coverage needs verification") and the open item from Report B ("musl Linux unknown").

**Where the two prior reports disagreed**, the latest-release evidence resolves the dispute:

- Report A claimed: "PBS aarch64-musl is dynamic and supports `dlopen` of extensions — the historic blocker is gone."
- Report B treated musl as "Unknown — must prove musl executable plus native wheels, especially `pydantic-core`."
- **Truth (2026-05-21):** Report A was correct. PR #541 merged 2025-03-11 made dynamic-musl the default; release 20250311 onward ships dynamic musl. PEX 2.72.0 dogfoods this for its own PEX scies. The `dlopen` blocker is genuinely gone, but **the PoC must still build and run on Alpine aarch64 with `pydantic-core` loaded** because PEX-scie + PBS-dynamic-musl + pydantic-core has not been smoke-tested in this repo's CI yet.

---

## 4. What single-binary-across-platforms looks like (it doesn't, but…)

The hard answer: **no**. A Python application carrying native ABI-pinned wheels (`pydantic-core`, `charset-normalizer`, `cffi`-via-`cryptography`-via-`secretstorage` on Linux) requires a separate artifact per OS+arch+libc. This is true of PEX scie, PyInstaller, Nuitka, PyOxidizer, and any launcher embedding PBS. The wheel ABI tags are the actual blocker, not the packaging tool.

There are two ways to fake "one binary" that we considered and rejected:

- **Cosmopolitan libc / `cosmofy`.** Produces an actually fat binary that runs on Linux/macOS/Windows. Immature wheel compatibility for `pydantic-core`-class extensions. Reject for now.
- **Universal `.pyz` + system Python.** The current state. Fails the hard requirement.

What we ship instead: **eight per-platform binaries with auto-resolution at install time.** The naming scheme is stable, predictable, and consumed by `cloudsmith-cli-action`, the Dockerfile, Homebrew/Scoop manifests, and the shell installer.

```
cloudsmith-${VER}-linux-x86_64
cloudsmith-${VER}-linux-aarch64
cloudsmith-${VER}-linux-x86_64-musl
cloudsmith-${VER}-linux-aarch64-musl
cloudsmith-${VER}-macos-x86_64
cloudsmith-${VER}-macos-aarch64
cloudsmith-${VER}-windows-x86_64.exe
cloudsmith-${VER}-windows-aarch64.exe
sha256sums.txt
sbom.cdx.json
*.intoto.jsonl   # SLSA provenance attestations
```

The Cloudsmith raw repo URL shape becomes:

```
https://dl.cloudsmith.io/public/cloudsmith/cli-binary/raw/names/cloudsmith-cli/versions/${VER}/cloudsmith-${VER}-${OS}-${ARCH}[-musl][.exe]
```

The current `cli-zipapp` URL keeps working through the 2–3 release transition window (Report A's plan; we keep `cloudsmith.pyz` parallel during deprecation).

---

## 5. Why we are NOT changing tools

The user's brief explicitly allows leaving PEX. The case for leaving was considered and rejected:

- **a-scie/lift (`science`) directly, dropping PEX.** PEX wraps `science` and adds dependency resolution, lockfile management, and the existing `.platforms/*.json` flow. Dropping PEX means rewriting the dependency-resolution pipeline. Negative ROI.
- **GoReleaser v2.9+ Python flow.** Drives Homebrew/Scoop/Winget/Chocolatey from one config. **Complementary**, not a replacement — pair with PEX-scie for builds, GoReleaser for downstream channels.
- **cargo-dist (`dist`).** Similar — useful for channels and Sigstore signing, not a replacement for the Python build step.
- **Rust/Go rewrite.** Multi-quarter project; not justified by current packaging pain.

**Net conclusion:** the lowest-friction path that meets all hard requirements is "keep PEX, change one flag, add a per-target CI matrix." That is what the PoC executes.

---

## 6. Plan for `cloudsmith-cli-action` and CI/CD consumers

The action currently does **no architecture detection** and **assumes Python on the runner**. Quoted from `src/download-cli.js`:

```javascript
const batFilePath = path.join(path.dirname(EXECUTABLE_PATH), 'cloudsmith.bat');
const content = `@echo off\npython ${EXECUTABLE_PATH} %*`;
fs.writeFileSync(batFilePath, content);
```

That `.bat` is the smoking gun: the action requires Python on Windows runners today. The migration plan replaces the `.pyz` download with native-binary auto-resolution.

### Resolution algorithm (Node-side, runs inside the action)

```javascript
// pseudocode
const platform = process.platform;   // 'linux' | 'darwin' | 'win32'
const arch = process.arch;           // 'x64' | 'arm64'

// detect libc on Linux only
let libc = '';
if (platform === 'linux') {
  // execSync('ldd --version') stderr contains 'musl' on Alpine
  try {
    const out = execSync('ldd --version 2>&1', { encoding: 'utf8' });
    libc = out.includes('musl') ? '-musl' : '';
  } catch (_) {
    // some minimal distros lack ldd; fall back to /etc/os-release
    const osr = fs.existsSync('/etc/os-release') ? fs.readFileSync('/etc/os-release', 'utf8') : '';
    libc = osr.includes('Alpine') ? '-musl' : '';
  }
}

const osPart = { linux: 'linux', darwin: 'macos', win32: 'windows' }[platform];
const archPart = { x64: 'x86_64', arm64: 'aarch64' }[arch];
const ext = platform === 'win32' ? '.exe' : '';
const binaryName = `cloudsmith-${version}-${osPart}-${archPart}${libc}${ext}`;

// New URL shape
const url = `https://dl.cloudsmith.io/public/cloudsmith/cli-binary/raw/names/cloudsmith-cli/versions/${version}/${binaryName}`;
```

### Backward-compatibility behaviour during transition

1. Prefer native binary URL (above).
2. On 404 or other resolution failure, fall back to `cloudsmith.pyz` + `actions/setup-python@v5` (current behaviour preserved).
3. `pip-install: true` continues to work unchanged.
4. The `cloudsmith.bat` Python wrapper is **deleted** in the native-binary path; the binary is invoked directly.

### Downstream consumers to update in lockstep

| Consumer | Today | After |
|---|---|---|
| `cloudsmith-cli-action/src/download-cli.js` | downloads `.pyz`, wraps in `cloudsmith.bat` on Windows | downloads per-platform binary, no wrapper |
| `Dockerfile` | `FROM python:3.12-alpine`, downloads `.pyz` | `FROM alpine:latest` (no Python), `ADD` Linux-musl scie, drops image size materially |
| `install.sh` (new) | n/a | one-liner that detects OS/arch/libc, downloads correct binary, verifies sha256, optionally verifies Sigstore signature |
| Homebrew tap, Scoop bucket, Winget, Cloudsmith Debian/RPM | n/a | driven by GoReleaser v2.9+ from the same binaries |

---

## 7. Required code change (one file, ~15 lines)

`cloudsmith_cli/cli/commands/mcp.py` at `_get_server_config()` lines 285–312 currently emits `sys.executable -m cloudsmith_cli ...` when running from a venv. In a frozen binary that branch is wrong — it must always emit the absolute path of the binary itself. The detection check is simple:

```python
def _is_frozen() -> bool:
    return (
        getattr(sys, "frozen", False)               # PyInstaller / Nuitka
        or "PEX" in os.environ                      # PEX runtime
        or os.environ.get("SCIE") is not None       # scie-jump
        or os.environ.get("PEX_SCIE_BOOT") is not None
    )
```

When `_is_frozen()` returns `True`, return `{"command": str(Path(sys.argv[0]).resolve()), "args": ["mcp", "serve"]}`. This is a no-regret change and is good to land before the PoC starts so the same `mcp.py` code path is exercised in both `.pyz` and scie modes.

---

## 8. Proof-of-Concept plan (executable by agents via GitHub Actions)

### 8.1 Execution choice: GitHub Actions, not local Docker

The user asked whether the PoC should run from a Mac+Docker or from GitHub Actions. **Use GitHub Actions.** Reasons:

- **Windows x86_64 and Windows aarch64 cannot be tested from a Mac.** No usable cross-compilation path, no Windows runtime in Docker for Desktop on Apple Silicon. PEX-scie + Windows aarch64 must run on `windows-11-arm` runners.
- **Linux aarch64 + musl needs a native ARM64 runner.** QEMU emulation is slow and has produced silent native-extension misbehaviour in similar projects.
- **macOS x86_64 needs an Intel macOS runner** (GitHub still offers `macos-13` for that — Apple Silicon `macos-15`/`macos-26` only.)
- **Reproducible, signed, attested.** Same workflow can later be promoted to release with `actions/attest-build-provenance@v2`.

The user offered to fork the repo. That's the recommended path:

1. Fork `cloudsmith-io/cloudsmith-cli` → e.g., `bblizniak/cloudsmith-cli`.
2. Push the PoC workflow on a `poc/pex-scie` branch.
3. Trigger via `workflow_dispatch`; agents read the run logs and artifact outputs.
4. No production credentials needed — PoC uses a dedicated `cloudsmith-test` org and test API key stored as a fork-scoped repo secret.

### 8.2 Pre-PoC tasks (one engineer, ~half a day)

Before the matrix runs, these need to land on the PoC branch:

- [ ] Patch `cloudsmith_cli/cli/commands/mcp.py:285-312` for frozen-binary detection (§7 above).
- [ ] Add a `requirements-runtime.txt` constraints file generated from `setup.py` install_requires only (no dev/test/lint). The current `requirements.txt` mixes runtime + dev; freezing it into a binary ships pytest, pylint, etc. Report B caught this.
- [ ] Exclude nested test packages from the wheel: change `setup.py` `find_packages(exclude=["tests"])` → `find_packages(exclude=["tests", "*.tests", "*.tests.*", "tests.*"])`. Report B caught this.
- [ ] Add real API + `mcp serve` stdio + `keyring` round-trip smoke tests to `.github/workflows/test.yml`. Today it only runs `cloudsmith --version`. Report A and B both flagged this.

### 8.3 PoC build matrix (one workflow file)

`.github/workflows/poc-pex-scie.yml`:

```yaml
name: PoC — PEX scie

on:
  workflow_dispatch:
  push:
    branches: [ "poc/pex-scie" ]

permissions:
  contents: read
  id-token: write       # for attestations later
  attestations: write

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        target:
          - { name: linux-x86_64,        runner: ubuntu-latest,    scie-platform: linux-x86_64,           ext: '' }
          - { name: linux-aarch64,       runner: ubuntu-24.04-arm, scie-platform: linux-aarch64,          ext: '' }
          - { name: linux-x86_64-musl,   runner: ubuntu-latest,    scie-platform: linux-x86_64-musl,      ext: '' }
          - { name: linux-aarch64-musl,  runner: ubuntu-24.04-arm, scie-platform: linux-aarch64-musl,     ext: '' }
          - { name: macos-x86_64,        runner: macos-13,         scie-platform: macos-x86_64,           ext: '' }
          - { name: macos-aarch64,       runner: macos-latest,     scie-platform: macos-aarch64,          ext: '' }
          - { name: windows-x86_64,      runner: windows-latest,   scie-platform: windows-x86_64,         ext: '.exe' }
          - { name: windows-aarch64,     runner: windows-11-arm,   scie-platform: windows-aarch64,        ext: '.exe' }
    runs-on: ${{ matrix.target.runner }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - name: Install build deps
        run: pip install --upgrade pip pex==2.95.2 setuptools wheel cyclonedx-py
      - name: Build scie
        shell: bash
        run: |
          mkdir -p dist
          OUT="dist/cloudsmith-${GITHUB_SHA::7}-${{ matrix.target.name }}${{ matrix.target.ext }}"
          pex . \
            --output-file "$OUT" \
            --console-script cloudsmith \
            --scie eager \
            --scie-platform "${{ matrix.target.scie-platform }}" \
            --complete-platform .github/.platforms/$(ls .github/.platforms/ | grep -E '^(linux|macosx|win)' | grep -v generate | head -1) \
            --venv
          ls -lh "$OUT"
          (cd dist && sha256sum "$(basename $OUT)" || shasum -a 256 "$(basename $OUT)") > "dist/$(basename $OUT).sha256"
      - name: Build SBOM
        run: cyclonedx-py environment > "dist/cloudsmith-${{ matrix.target.name }}.sbom.cdx.json"
      - uses: actions/upload-artifact@v4
        with:
          name: cloudsmith-${{ matrix.target.name }}
          path: dist/
          retention-days: 14

  smoke-linux-glibc:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with: { name: cloudsmith-linux-x86_64, path: ./bin }
      - name: No-Python validation
        run: |
          chmod +x ./bin/cloudsmith-*
          BIN=$(ls ./bin/cloudsmith-* | grep -v sha256 | grep -v sbom | head -1)
          docker run --rm -v "$PWD/bin:/work" -w /work debian:stable-slim sh -c "
            ! command -v python3 || { echo 'Python found in container, test invalid'; exit 1; }
            ./$(basename $BIN) --version
            ./$(basename $BIN) --help > /dev/null
          "

  smoke-linux-musl:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with: { name: cloudsmith-linux-x86_64-musl, path: ./bin }
      - name: No-Python Alpine validation (pydantic-core load test)
        run: |
          chmod +x ./bin/cloudsmith-*
          BIN=$(ls ./bin/cloudsmith-* | grep -v sha256 | grep -v sbom | head -1)
          docker run --rm -v "$PWD/bin:/work" -w /work alpine:latest sh -c "
            ! command -v python3 || { echo 'Python found, test invalid'; exit 1; }
            ./$(basename $BIN) --version
            ./$(basename $BIN) --help > /dev/null
            ./$(basename $BIN) mcp --help > /dev/null   # forces pydantic-core import via mcp
          "

  smoke-linux-aarch64-musl:
    needs: build
    runs-on: ubuntu-24.04-arm
    steps:
      - uses: actions/download-artifact@v4
        with: { name: cloudsmith-linux-aarch64-musl, path: ./bin }
      - name: No-Python Alpine aarch64 validation
        run: |
          chmod +x ./bin/cloudsmith-*
          BIN=$(ls ./bin/cloudsmith-* | grep -v sha256 | grep -v sbom | head -1)
          docker run --rm --platform linux/arm64 -v "$PWD/bin:/work" -w /work alpine:latest sh -c "
            ! command -v python3 || { echo 'Python found, test invalid'; exit 1; }
            ./$(basename $BIN) --version
            ./$(basename $BIN) mcp --help > /dev/null
          "

  smoke-macos:
    needs: build
    strategy:
      fail-fast: false
      matrix:
        include:
          - { artifact: cloudsmith-macos-aarch64, runner: macos-latest }
          - { artifact: cloudsmith-macos-x86_64,  runner: macos-13 }
    runs-on: ${{ matrix.runner }}
    steps:
      - uses: actions/download-artifact@v4
        with: { name: ${{ matrix.artifact }}, path: ./bin }
      - name: No-Python macOS validation
        run: |
          chmod +x ./bin/cloudsmith-*
          BIN=$(ls ./bin/cloudsmith-* | grep -v sha256 | grep -v sbom | head -1)
          # Strip Python from PATH; macOS keeps /usr/bin where Apple's stub python3 might live
          mkdir -p /tmp/no-python && export PATH=/tmp/no-python
          which python3 && exit 1 || true
          ./"$BIN" --version
          ./"$BIN" --help > /dev/null
          ./"$BIN" mcp --help > /dev/null

  smoke-windows:
    needs: build
    strategy:
      fail-fast: false
      matrix:
        include:
          - { artifact: cloudsmith-windows-x86_64,  runner: windows-latest }
          - { artifact: cloudsmith-windows-aarch64, runner: windows-11-arm }
    runs-on: ${{ matrix.runner }}
    steps:
      - uses: actions/download-artifact@v4
        with: { name: ${{ matrix.artifact }}, path: .\bin }
      - name: No-Python Windows validation
        shell: pwsh
        run: |
          $bin = Get-ChildItem .\bin\cloudsmith-*.exe | Where-Object { $_.Name -notmatch 'sha256|sbom' } | Select-Object -First 1
          # GitHub Windows runners ship Python. Move it out of PATH for this test.
          $env:PATH = "C:\Windows\System32;C:\Windows"
          where.exe python; if ($LASTEXITCODE -eq 0) { Write-Error "Python found in PATH"; exit 1 }
          & $bin.FullName --version
          & $bin.FullName --help | Out-Null
          & $bin.FullName mcp --help | Out-Null

  e2e-api:
    needs: [smoke-linux-glibc, smoke-linux-musl, smoke-macos, smoke-windows]
    runs-on: ubuntu-latest
    env:
      CLOUDSMITH_API_KEY: ${{ secrets.POC_CLOUDSMITH_API_KEY }}
      TEST_ORG: ${{ vars.POC_ORG }}
      TEST_REPO: ${{ vars.POC_REPO }}
    steps:
      - uses: actions/download-artifact@v4
        with: { name: cloudsmith-linux-x86_64, path: ./bin }
      - name: Real API smoke test
        run: |
          chmod +x ./bin/cloudsmith-*
          BIN=$(ls ./bin/cloudsmith-* | grep -v sha256 | grep -v sbom | head -1)
          ./"$BIN" --version
          CLOUDSMITH_NO_KEYRING=1 ./"$BIN" whoami
          CLOUDSMITH_NO_KEYRING=1 ./"$BIN" repos list "$TEST_ORG"
          echo "hello $(date)" > /tmp/poc-fixture.txt
          CLOUDSMITH_NO_KEYRING=1 ./"$BIN" push raw --dry-run "$TEST_ORG/$TEST_REPO" /tmp/poc-fixture.txt
      - name: MCP stdio handshake test
        run: |
          BIN=$(ls ./bin/cloudsmith-* | grep -v sha256 | grep -v sbom | head -1)
          # Send a JSON-RPC initialize and assert a valid envelope comes back
          printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"poc","version":"0"}}}' \
            | timeout 10 ./"$BIN" mcp serve | head -1 | grep -q '"jsonrpc":"2.0"'
```

### 8.4 Acceptance criteria

Same as both reports, with a few additions from this final pass:

| Criterion | Threshold | Notes |
|---|---|---|
| Build success on every matrix cell | 8/8 | Cell-level failure is reportable, not blocking — the failure-reporting template captures it. |
| No-Python validation | Pass on Linux glibc, Alpine musl x86_64, Alpine musl aarch64, macOS aarch64, macOS x86_64, Windows x86_64, Windows aarch64 | This is the hard requirement. |
| `mcp --help` succeeds on Alpine aarch64 | Pass | This is the direct test of PBS dynamic-musl + `pydantic-core`. The historic blocker validation. |
| `mcp serve` stdio handshake | Pass on every target | This is the `anyio`/Nuitka watch item — proves PEX scie is unaffected. |
| Binary size per target | < 80 MB | Existing `.pyz` is 49 MB carrying 5 Pythons; per-target should be smaller. |
| Cold start (`--version`) | < 1 s post-extraction; < 6 s first-run | Report B measured 0.37 s warm / 5.13 s cold on macOS arm64. |
| Real API end-to-end | `whoami` + `repos list` + `push --dry-run` succeed | Run from one target, not all eight — that's smoke. |
| TLS connects to api.cloudsmith.io | No `SSL_CERT_FILE` override needed | `certifi` bundled. |
| Keyring round-trip | Pass on each OS with native backend, graceful disable via `CLOUDSMITH_NO_KEYRING=1` in headless | Adds keyring-specific job if first PoC passes. |
| SBOM published per artifact | Yes | `cyclonedx-py` clean run. |
| Sigstore attestation per artifact | Optional in PoC | Add when promoting to release workflow. |

### 8.5 Failure reporting template (for agents)

```markdown
## PoC Failure: <target> / <test>

- Target: <linux-x86_64 | linux-aarch64 | linux-x86_64-musl | linux-aarch64-musl | macos-x86_64 | macos-aarch64 | windows-x86_64 | windows-aarch64>
- Runner: <ubuntu-latest | ubuntu-24.04-arm | macos-13 | macos-latest | windows-latest | windows-11-arm>
- Job step: <build | smoke-linux-* | smoke-macos | smoke-windows | e2e-api>
- Artifact SHA256: <hex>
- Command: <exact command from workflow>
- Expected: <what should happen>
- Actual: <stderr / exit code / hang / segfault / signature mismatch / etc.>
- PEX / PBS versions: pex==<>, pbs==<>
- Reproducer: <minimal shell snippet>
- Suspected cause: <hidden import | data file | metadata | native-ext ABI | CA bundle | keyring backend | scie cache | other>
- Workaround attempted: <flag changes / hooks / shim>
- Blocking? <yes | no | needs-investigation>
```

### 8.6 What the PoC explicitly does NOT test

- Code signing (macOS Developer ID, Windows Authenticode). Procurement of HSM-backed EV certs and the Apple Developer account is decoupled from the build proof. Add to the release workflow after PoC passes.
- GoReleaser channel publishing (Homebrew/Scoop/Winget). Out of scope for the first PoC.
- Self-update story. Defer; rely on package-manager upgrades.
- 32-bit Linux, ppc64le, s390x, riscv64. Cloudsmith CLI does not currently support these; PEX scie does, so adding them later is a flag change.

---

## 9. Risks and known unknowns (final pass)

These are the items where the latest-release validation **didn't** fully close the gap. Each is something the PoC must explicitly answer.

1. **PEX scie + PBS-dynamic-musl + pydantic-core on Alpine aarch64.** All three pieces individually work as of May 2026, but the composition has not been smoke-tested in this repo. The PoC `smoke-linux-aarch64-musl` job is the direct test. Probability of success: high. Probability of needing one extra flag tweak: medium.
2. **Windows ARM64 scie + keyring (pywin32-ctypes).** `pywin32-ctypes` ships pure-Python wheels — no ABI risk — but the credential-manager P/Invoke surface has never been exercised in our CI on `windows-11-arm`. PoC includes `--help` and stdio handshake; add a keyring round-trip job before promoting to release.
3. **`anyio` on Windows under PEX scie.** PEX scie does **not** transform the source the way Nuitka does, so the Nuitka #3691 breakage is irrelevant in theory. The PoC `e2e-api` job verifies the stdio handshake; treat any failure as a P0.
4. **Scie cache location in restricted CI environments.** `~/.cache/nce` requires writable home. Confirm `PEX_SCIE_CACHE_DIR` or `SCIE_BASE` env var is respected and document the override.
5. **Binary signing throughput.** macOS notarization can take 5–15 minutes for the first submission; releases will need parallelism or async submission with stapling on a second pass.
6. **`cloudsmith_api` 16 MB swagger client dominates the binary.** Out of scope for the packaging change, but a near-term ticket. Either prune unused models or move to a lazier import shape.

---

## 10. Recommended next steps (concrete, ordered)

1. **Pre-PoC hygiene (half a day, one engineer):**
   - Patch `cli/commands/mcp.py:285-312` for `_is_frozen()` detection (§7).
   - Generate `requirements-runtime.txt` from `setup.py install_requires` only.
   - Exclude nested test packages from the wheel.
   - Add real API + `mcp serve` smoke tests to `.github/workflows/test.yml`.
2. **Run the PoC workflow on a forked repo (2 days, one engineer + agents):**
   - Land `.github/workflows/poc-pex-scie.yml` on a `poc/pex-scie` branch in the fork.
   - Trigger via `workflow_dispatch`; let agents read run logs.
   - Capture failures with the §8.5 template.
3. **Verdict on PoC results (half a day):**
   - 8/8 green ⇒ proceed to release workflow integration.
   - Any cell red ⇒ try PyInstaller 6.20 onedir for that specific target (fallback path); only commit to a hybrid if PEX-scie can't be made to work after one round of flag tweaks.
4. **Production rollout (after PoC green) — additive, not replacing:**
   - Keep `.pyz` for 2–3 release cycles.
   - Add scie targets to `release.yml`.
   - Wire `cloudsmith-cli-action` to prefer native binary, fall back to `.pyz`.
   - Cut `Dockerfile` over to `alpine:latest` + Linux musl scie (image-size win).
   - Add SBOM + SLSA attestation + Sigstore signing.
5. **Channel expansion (parallel work):**
   - Homebrew tap (formula + bottles).
   - Scoop bucket / Winget manifest.
   - Cloudsmith Debian/RPM wrappers (`fpm` over the Linux binaries).
   - `install.sh` shell installer.
6. **Operational cadence post-launch:**
   - Monthly scheduled rebuild matching PBS release cadence.
   - Security-patch rebuild trigger on advisories for any embedded package.
   - Quarterly review of `--scie-platform` coverage as the project adds targets.

---

## 11. Where each input report contributed

| Report | Unique contributions kept in this final | Where it was wrong / superseded |
|---|---|---|
| Report A (desk research) | Full file:line citation map; `.platforms/*.json` reuse plan; license analysis of Nuitka; downstream-consumer migration plan; security/signing matrix; thorough option survey | Claimed PBS-dynamic-musl as if validated locally — this final pass independently verified via PR #541 closing 2025-03-11. |
| Report B (local POC) | Live PEX scie build + run on macOS arm64 (35 MB, 0.37 s warm); live `cloudsmith-cli-action` evidence (Windows `.bat` → `python <pyz>`); duplicated-deps catch in `requirements.in`; nested-test-packages catch | Treated musl as "Unknown" because no Alpine build was run locally — final pass closes this from upstream evidence. |

---

## 12. Appendix: validation commands used in this pass

```bash
# Latest-release lookups
gh api repos/pex-tool/pex/releases/latest --jq '.tag_name, .published_at, .body' | head -40
gh api repos/astral-sh/python-build-standalone/issues/86 --jq '.state, .state_reason, .closed_at'
gh api repos/pyinstaller/pyinstaller/releases/latest --jq '.tag_name, .published_at'
gh api repos/a-scie/jump/releases/latest --jq '.tag_name, .published_at'
gh api repos/cloudsmith-io/cloudsmith-cli-action/contents/src/download-cli.js --jq '.content' | base64 -d
gh api repos/cloudsmith-io/cloudsmith-cli-action/contents/action.yml --jq '.content' | base64 -d

# Confirm scie platform enum directly from source
curl -fsSL https://raw.githubusercontent.com/pex-tool/pex/main/pex/scie/model.py | grep -E 'LINUX_|MACOS_|WINDOWS_|MUSL_'

# Confirm PBS asset shape
curl -fsSL https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest \
  | jq -r '.assets[].name' | grep -E 'aarch64.*musl|aarch64.*windows' | head
```

---

## 13. Appendix: sources verified during this final pass

- [PEX 2.95.2 release](https://github.com/pex-tool/pex/releases) (latest, 2026-05-18)
- [PEX `pex/scie/model.py` source — supported scie platform enum](https://github.com/pex-tool/pex/blob/main/pex/scie/model.py)
- [PEX 2.72.0 — foreign musl scies](https://github.com/pex-tool/pex/releases/tag/v2.72.0)
- [PEX scie documentation](https://docs.pex-tool.org/scie.html)
- [PEX scie discussion #2516](https://github.com/pex-tool/pex/discussions/2516)
- [python-build-standalone latest release 20260510](https://github.com/astral-sh/python-build-standalone/releases)
- [PBS issue #86 — dynamic musl dlopen, CLOSED 2025-03-12](https://github.com/astral-sh/python-build-standalone/issues/86)
- [PBS PR #541 — dynamic musl implementation, merged 2025-03-11](https://github.com/astral-sh/python-build-standalone/pull/541)
- [scie-jump 1.11.2 release](https://github.com/a-scie/jump/releases)
- [PyInstaller 6.20.0 changelog](https://pyinstaller.org/en/stable/CHANGES.html)
- [PyInstaller PyPI wheels (musllinux + win_arm64 confirmed)](https://pypi.org/project/pyinstaller/)
- [Nuitka issue #3691 — anyio breakage on Windows](https://github.com/Nuitka/Nuitka/issues/3691)
- [GitHub-hosted runners reference (ARM64 GA labels)](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [GitHub ARM64 runners GA announcement](https://github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available/)
- [`cloudsmith-cli-action/src/download-cli.js`](https://github.com/cloudsmith-io/cloudsmith-cli-action/blob/master/src/download-cli.js)
- [`cloudsmith-cli-action/action.yml`](https://github.com/cloudsmith-io/cloudsmith-cli-action/blob/master/action.yml)
