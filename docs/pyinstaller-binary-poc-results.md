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

## Platform-specific caveats (CRUCIAL — must be addressed before public release)

Every modern OS gates "unknown" binaries somehow. The PoC artifacts are unsigned, un-notarized, and have no reputation, so each platform's gating mechanism fires on first download. This is not a PyInstaller problem — any unsigned native binary downloaded via browser hits the same warnings.

### macOS — Gatekeeper + quarantine

**Symptom on first run:**

> "cloudsmith-macos-arm64 Not Opened — Apple could not verify "cloudsmith-macos-arm64" is free of malware that may harm your Mac or compromise your privacy."

**Why:** browser adds `com.apple.quarantine` xattr on download; macOS spots it, looks for an Apple Developer ID signature + notarization ticket, finds none, refuses to run. The message text means "I can't check who built this," **not** "I scanned it and found malware."

**User workarounds (single-use, for the PoC artifact):**

```bash
# Strip the quarantine xattr.
xattr -d com.apple.quarantine ~/Downloads/cloudsmith-macos-arm64
chmod +x ~/Downloads/cloudsmith-macos-arm64
~/Downloads/cloudsmith-macos-arm64 --version

# OR: Finder → right-click → Open → Open (one-time bypass).
# OR: System Settings → Privacy & Security → "Open Anyway" after the block.
```

**Permanent fix (release path):**

1. Apple Developer Program account ($99/year).
2. Issue a Developer ID Application certificate.
3. In the macOS CI job (both `arm64` + `amd64`):
   ```bash
   codesign --options runtime --timestamp --sign "Developer ID Application: …" cloudsmith
   ```
4. Notarize:
   ```bash
   xcrun notarytool submit cloudsmith.zip --apple-id … --team-id … --password … --wait
   ```
5. Notarization tickets cannot be stapled to a raw CLI binary (stapling is for `.app`/`.dmg`/`.pkg` only). macOS fetches the ticket online from Apple on first launch. Air-gapped Macs would see a delay/timeout — document `xcrun stapler validate` on the ZIP wrapper as a workaround if needed.

**macOS-specific knock-on effect for Cloudsmith:** macOS Keychain access is scoped by signing identity. An unsigned binary cannot read keychain entries written by a different identity (e.g. the pip-installed `cloudsmith`), so `keyring` will silently fall through to the file backend. After signing, keychain access works again — but the signing identity becomes part of the keychain ACL, so re-signing with a different identity in the future will invalidate stored tokens. Plan one signing identity per published artifact name and keep it stable.

### Windows — SmartScreen + MOTW + Defender

**Symptom on first run (browser-downloaded):**

> "Windows protected your PC. Microsoft Defender SmartScreen prevented an unrecognized app from starting."

User must click "More info" → "Run anyway". Edge sometimes hides this behind two extra clicks.

**Three separate mechanisms can fire here:**

1. **Mark-of-the-Web (MOTW)**: NTFS Alternate Data Stream `Zone.Identifier` added by browser. Equivalent to macOS quarantine xattr. Strip via:
   ```powershell
   Unblock-File -Path .\cloudsmith-windows-amd64.exe
   ```
2. **SmartScreen reputation**: low-download / unsigned binaries are blocked. EV Code Signing certs give instant reputation; OV certs ramp over weeks/downloads.
3. **Defender heuristics**: PyInstaller onefile binaries extract to `%TEMP%` on every launch. Some scanners flag this as packer/dropper behavior. Known false-positive territory for Python CLIs (b2-cli, mitmproxy, others have hit this).

**Permanent fix:**

1. Authenticode certificate. EV ≈ $300-700/yr (instant SmartScreen reputation, hardware token required). OV ≈ $80-200/yr (reputation ramps over time + downloads).
2. In the Windows CI job:
   ```powershell
   signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /a cloudsmith-windows-amd64.exe
   ```
3. UPX must stay off (already disabled in the `.spec`). UPX-packed binaries hit AV heuristics far more often.
4. If Defender still flags, submit to Microsoft's false-positive portal (https://www.microsoft.com/en-us/wdsi/filesubmission). Repeat for Bitdefender, Kaspersky, Sophos, ESET, McAfee, Symantec — each AV vendor has its own portal, no shared whitelist.

### Linux — no Gatekeeper, but four gotchas

**1. `chmod +x` required after download**

Browsers don't preserve POSIX exec bits. Docs must call this out:

```bash
chmod +x cloudsmith-linux-amd64-glibc
./cloudsmith-linux-amd64-glibc --version
```

**2. glibc baseline mismatch**

PoC built on `ubuntu-latest` → Ubuntu 24.04 → glibc 2.39. The binary will refuse to start on:

| Distro | glibc | Will the PoC binary run? |
|---|---:|---|
| Ubuntu 24.04 | 2.39 | yes (built here) |
| Ubuntu 22.04 | 2.35 | likely no |
| Ubuntu 20.04 | 2.31 | no |
| Debian 12 | 2.36 | likely no |
| RHEL/Rocky 9 | 2.34 | no |
| RHEL/Rocky 8 | 2.28 | no |
| Amazon Linux 2 | 2.26 | no |
| Amazon Linux 2023 | 2.34 | no |

Failure looks like:

```
./cloudsmith: /lib64/libc.so.6: version `GLIBC_2.34' not found
```

**Release fix:** build the glibc artifacts inside `quay.io/pypa/manylinux2014_x86_64` (glibc 2.17, covers basically everything) or `manylinux_2_28` (glibc 2.28, covers RHEL 8+, Amazon Linux 2023, Ubuntu 20.04+). PyInstaller works fine in either; just swap the runner from `ubuntu-latest` to `container: quay.io/pypa/manylinux2014_x86_64`. Drop ARM64 into `manylinux2014_aarch64`.

**3. musl is a separate world**

Already split into its own artifact. Running the glibc artifact on Alpine fails immediately with the same `GLIBC_…` error. The Alpine artifact (`cloudsmith-linux-*-musl`) is the only one that works on Alpine, Wolfi, Chainguard, Distroless-static, etc.

**4. SELinux / AppArmor on hardened distros**

RHEL/Rocky/Fedora with `targeted` policy can block execution from `~/Downloads`. Symptom:

```
Permission denied
# or in audit.log:
SELinux is preventing /home/user/Downloads/cloudsmith from execute access on the file
```

User workaround:

```bash
chcon -t bin_t ~/Downloads/cloudsmith-linux-amd64-glibc
# or: sudo install -m 755 cloudsmith-linux-amd64-glibc /usr/local/bin/cloudsmith
```

Document this; don't try to fix it from the binary side.

### Browser / Safe Browsing layer (cross-platform)

Chrome + Edge + Firefox can mark the binary as "may harm your computer" based on:
- Low download volume
- Missing signature
- File type (`.exe`, raw ELF) without reputation

The macOS notarization + Windows Authenticode paths above usually clear browser warnings too because reputation services key off the signing certificate chain. Linux artifacts may still need manual reporting via Google Search Console / Microsoft Edge feedback if the warning lingers.

### PyInstaller onefile self-extraction caveats

These bite **any** PyInstaller onefile binary; not Cloudsmith-specific.

1. **`noexec` `/tmp` blocks onefile entirely.** Some hardened Linux servers, container runtimes (gVisor with default config), FIPS-locked machines, and corporate desktops mount `/tmp` with `noexec`. PyInstaller onefile extracts there before exec — fatal. Onedir bundle is the only fix. Worth shipping onedir for at least one Linux target alongside onefile.
2. **First-launch disk space.** Onefile temporarily doubles its on-disk size during extraction (~40-75 MB peak). Small VMs and constrained containers can OOM the filesystem on first run.
3. **Cold start variance.** Onefile pays an extraction cost on every launch. Onedir extracts once at install time. CI numbers in this report measured cold-start onefile; onedir typically halves Windows startup.
4. **Side-effect: leaked `LD_LIBRARY_PATH` / `DYLD_LIBRARY_PATH`.** PyInstaller's bootloader sets these so the bundled libs win the search order. They survive into any child process the CLI spawns. If `cloudsmith` ever shells out to a user-installed tool (`git`, `curl`, etc.), the child sees the bundled libs first and may misbehave. Mitigation: explicitly `unset LD_LIBRARY_PATH DYLD_LIBRARY_PATH` before `subprocess.run(...)` in cloudsmith's own code, OR document that downstream tools may inherit unexpected env. Worth a code audit before this becomes the default distribution.

### Corporate networks (real-world Cloudsmith user setting)

1. **MITM proxies / internal root CAs.** Bundled `certifi` won't include internal CAs. Users behind Zscaler, Netskope, Forcepoint, or homegrown MITM proxies will hit `SSLError: CERTIFICATE_VERIFY_FAILED`. Document:
   ```bash
   export SSL_CERT_FILE=/path/to/corp-roots.pem        # urllib/requests honour this
   export REQUESTS_CA_BUNDLE=/path/to/corp-roots.pem   # belt + braces
   ```
2. **Air-gapped environments.** Binary distribution via GitHub release won't work. Mirror artifacts to an internal Cloudsmith raw repo (the existing `.pyz` path already does this) and document the same flow for the new binaries.
3. **Outbound CIDR allowlists.** `api.cloudsmith.io` only. PyInstaller binary has no telemetry / phone-home; certifi CA bundle is local; nothing else dials out. Worth stating explicitly in release notes — corp security teams will ask.

### Locale, encoding, CPU instructions

1. **Locale / encoding.** PyInstaller bundles a Python with default encodings only. Non-UTF-8 Windows codepages (`cp1252`, Japanese `cp932`, etc.) can corrupt `click` output containing non-ASCII repo/package names. Set `PYTHONIOENCODING=utf-8` at install time, or document.
2. **Onefile CPU instructions.** `pydantic-core` (Rust) ships per-architecture wheels with CPU intrinsics. Built on modern CI runners with AVX2-capable CPUs. Should still run on pre-2013 Sandy Bridge and older low-end VMs because pydantic-core publishes baseline ISA variants, but explicitly test on at least one older CPU before declaring "runs everywhere".

### Distribution + lifecycle

1. **No self-update.** `.pyz` users can `pip install -U`. Binary users cannot. Options:
   - Add a `cloudsmith self-update` command that downloads the latest matching artifact + SHA-verifies + atomic-replaces the running binary. Tricky on Windows (can't overwrite a running `.exe`; common pattern is rename-then-replace-on-restart).
   - Ship through OS package managers: Homebrew formula / tap, Chocolatey, winget, apt repo, yum repo, Snap, Flatpak. Each has its own signing + manifest requirements but shifts the update problem onto well-understood tooling.
   - Recommendation: Homebrew formula + winget manifest cover ~80% of macOS + Windows users with minimal extra work; binary self-update can come later or never.
2. **`cloudsmith mcp configure` writes absolute binary paths.** Files like `~/.cursor/mcp.json`, `~/Library/Application Support/Claude/claude_desktop_config.json` will pin the path of the binary at configure time. Reinstall to a different location → MCP client silently fails to start the server. Mitigation: document the path explicitly, or have `cloudsmith mcp configure --refresh` re-run with the current `sys.executable`.
3. **PATH collisions with `pip install cloudsmith-cli`.** Existing users may have a `cloudsmith` already on PATH from pip/pipx. Install docs need an unambiguous which-takes-precedence story (`which cloudsmith` / `Get-Command cloudsmith`) and a recommendation to uninstall the pip version before switching to the binary, or use a different install location.

### Supply chain + reproducibility

1. **PyInstaller builds are not bit-reproducible.** Random temp-archive offsets + timestamps mean two clean builds of the same git SHA produce different SHA256s. SHA256SUMS is fine for verifying "the file the CI uploaded matches the file you downloaded," but not for "anyone can verify the binary corresponds to this source." Mitigation: `actions/attest-build-provenance` (SLSA Level 3 provenance) certifies the build pipeline, source SHA, and runner identity instead. Combine with `gh attestation verify`.
2. **License audit.** PyInstaller statically bundles every dependency, so license obligations of transitive deps follow the binary. Run `pip-licenses` against the runtime requirements and `syft scan` against the built binary; export an SBOM (`sbom-<version>.cdx.json`) alongside the release. Already in the plan, but flagged here because it's load-bearing for legal/compliance review at enterprise customers.
3. **CVE response.** Binary bakes in pinned versions of `certifi`, `urllib3`, `cryptography`, `pydantic-core`, etc. When one of those gets a CVE, the binary has to be rebuilt + re-released, even if no Cloudsmith code changed. Trigger: scheduled rebuilds (weekly?) or `dependabot` PRs that bump pins and re-run the release workflow.

### Architecture / emulation

| Host | Native binary preferred | Emulated fallback works? |
|---|---|---|
| Windows ARM64 | `cloudsmith-windows-arm64.exe` | yes — `cloudsmith-windows-amd64.exe` runs via Prism emulation |
| macOS Apple Silicon | `cloudsmith-macos-arm64` | yes — `cloudsmith-macos-amd64` runs via Rosetta 2 (slower) |
| Linux ARM64 + x86 emulation (rare) | `cloudsmith-linux-arm64-*` | no — don't bother |

The `cloudsmith-cli-action` resolution layer should prefer native and fall back to emulated only when the native variant is missing (e.g. Windows ARM64 binary download fails for some reason).

### Summary table

| Platform | Gating mechanism | Required fix | Cost | Required for public release? |
|---|---|---|---:|---|
| macOS | Gatekeeper + quarantine xattr | Apple Developer ID + notarization | $99/yr | Yes |
| Windows | SmartScreen + MOTW + Defender heuristics | Authenticode signing (EV strongly preferred) | $80–700/yr | Yes |
| Linux (glibc) | glibc version pin | Build in `manylinux2014` or `manylinux_2_28` | $0 | Yes for broad distro support |
| Linux (musl) | Separate ABI | Already covered by Alpine job | $0 | Yes if Alpine is supported |
| Linux (SELinux) | Type enforcement on `~/Downloads` | Document `chcon` / install to `/usr/local/bin` | $0 | Document only |
| Browser Safe Browsing | Reputation | Falls out of macOS notarization + Windows Authenticode | (included) | Bonus |
| Corporate proxy / MITM | Bundled certifi excludes internal roots | Document `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` | $0 | Document |
| PyInstaller onefile on `noexec /tmp` | Self-extraction blocked | Ship onedir bundle alongside onefile | $0 | Yes, at least for Linux |
| AV beyond Defender | Heuristics | Per-vendor false-positive submissions | $0 | Reactive |
| SBOM / SLSA / CVE | Bundled deps need tracking | Syft + `actions/attest-build-provenance` + scheduled rebuilds | $0 | Yes for enterprise |
| Self-update | None built in | Homebrew / winget / `cloudsmith self-update` | dev time | Yes |

## Verdict against the plan

PyInstaller 6.20.0 is the right pick. The execution confirmed all of `research_2.md`'s assumptions, with one workflow-only correction (ARM64 Alpine container limitation) and no fallbacks needed for the artifact mode. The PoC artifacts are now sitting under run 26239197986 in `BartoszBlizniak/cloudsmith-cli`, ready to be promoted into the upstream release workflow alongside the existing `cloudsmith.pyz` and Docker pipelines — **but read the platform-specific caveats section before shipping anything externally**. Every macOS user will see a "malware" dialog on first download until the artifacts are notarized; every Windows user will see SmartScreen until the artifacts are Authenticode-signed; every Linux user on a non-bleeding-edge distro will see `GLIBC_…` errors until the glibc artifacts are built on `manylinux`. None of these are PyInstaller bugs, but all three must be addressed before the binary becomes the default distribution channel.
