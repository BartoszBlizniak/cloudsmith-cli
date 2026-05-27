# Cloudsmith CLI Binary Packaging — Research Follow-up Plan

Per-question delegation plan for the 18 NEEDS MORE RESEARCH items from the Notion spike doc.
Each section is self-contained so a fresh agent can pick it up without the parent conversation.

## Status (2026-05-27)

PoC branches on `BartoszBlizniak/cloudsmith-cli`:
- **PEX scie path:** branch `poc/pex-scie`, workflow `.github/workflows/poc-pex-scie.yml`.
- **PyInstaller path:** branch `binary-poc`, workflow `.github/workflows/binary-poc.yml`.

| Q | Title | Status | Evidence |
|---|-------|--------|----------|
| #1 | PEX scie Windows on 2.95.2 | **ANSWERED — NO** | `pex/scie/__init__.py` filters `WINDOWS_X86_64` + `WINDOWS_AARCH64` from `--scie-platform` on both `v2.95.2` and `main`. Upstream tracking issue still open: pex-tool/pex#2658. Windows must go through PyInstaller. |
| #2 | PBS glibc floor | **ANSWERED — glibc 2.34** | Run `26503644284`. PASS: amazonlinux:2023 (2.34), debian:12 (2.36), rockylinux:9 (2.34), ubuntu:22.04 (2.35). FAIL: amazonlinux:2 (2.26), debian:11 (2.31), rockylinux:8 (2.28), ubuntu:20.04 (2.31). Fail mode: PBS scie boots its bundled CPython 3.12.13 but the in-PEX resolver reports `cryptography>=2.0` unavailable for the runtime tag set (`cp312-cp312-manylinux_2_31_x86_64`), then exits with `Boot binding command failed`. |
| #3 | PEX scie + Alpine + pydantic-core (x86_64) | **ANSWERED — PASS** | `smoke linux musl x86_64 no-Python` job, run `26223343596` (SHA `f4147b5`). `cloudsmith --version`, `--help`, `mcp --help` all OK on `alpine:latest`. Binary 100.7 MiB. |
| #4 | PEX scie + Alpine + arm64 | **ANSWERED — PASS** | `smoke linux musl aarch64 no-Python` job, same run, on `ubuntu-24.04-arm` + `alpine:latest --platform linux/arm64`. Binary 100.6 MiB. |
| #5 | Keyring round-trip per backend | **IN FLIGHT (PyInstaller)** | `binary-poc` SHA `9b00c7f`, run `26505942827`. Hidden `check keyring-selftest` subcommand added (synthetic set/get/delete via the configured backend). CI gates: macOS/Windows native, Linux glibc via `dbus-run-session` + `gnome-keyring-daemon`, musl Alpine expected to fail gracefully + verify `CLOUDSMITH_NO_KEYRING=1` fallback. Signed-macOS retest blocked on Q#16. |
| #6 | Authenticated push/pull e2e | **IN FLIGHT (PyInstaller)** | Same run. New `setup-test-repo` job idempotently creates `$CLOUDSMITH_NAMESPACE/binary-poc` (raw, public); per-target steps push a `$GITHUB_RUN_ID`-versioned fixture, download, `cmp`. setup-test-repo step succeeded in the in-flight run (raw repo provisioned). |
| #7 | Native cryptography round-trip | **IN FLIGHT (PyInstaller)** | Same run. Hidden `check cryptography-selftest` subcommand added (Fernet `generate_key` → encrypt → decrypt round-trip). No direct `from cryptography` import sites exist in the CLI today (`grep -rn "from cryptography" cloudsmith_cli/` returns nothing); the module is pulled transitively via `keyring → secretstorage` on Linux. PRs #275 (credential chain) + #276 (OIDC) in flight may introduce real call sites. Spec lists `cryptography`, `cryptography.fernet`, `cryptography.hazmat.bindings._rust` under hidden imports explicitly. |
| #8 | anyio + MCP stdio on Windows under PEX scie | **N/A (Q#1)** + extended to macOS/musl | Windows scie path eliminated by Q#1. MCP handshake now exercised on linux-x86_64 (already green), musl-x86_64, macOS-aarch64 in commit `bdd3ecb`. |
| #12 | Reproducible PEX scie | **ANSWERED — YES** | Run `26503644284`, job `reproducibility (linux-x86_64)` PASS — two PEX scie builds with `SOURCE_DATE_EPOCH=1700000000` and isolated `PEX_ROOT` produced byte-identical binaries on the same runner. Cross-runner/OS verification still open (only one cell tested). |
| #13 | `cloudsmith-cli-action` libc detection | **DESIGN BRIEF DRAFTED** | Algorithm, URL shape, fallback policy, unit + integration test matrices, and implementation notes are in §13 below. PR to `cloudsmith-io/cloudsmith-cli-action` deferred to an engineer with push perms there (binary PoC work is scoped to this fork). |

Sizes from run `26223343596` (PEX scie, PBS 20260510, Python 3.14.5):

| target | bytes | MiB |
|--------|-------|-----|
| linux-x86_64 (glibc) | 123,578,543 | 117.8 |
| linux-aarch64 (glibc) | 98,518,211 | 93.9 |
| musl-linux-x86_64 | 105,560,893 | 100.7 |
| musl-linux-aarch64 | 105,523,631 | 100.6 |
| macos-aarch64 | 34,233,852 | 32.6 |
| macos-x86_64 | n/a | n/a (build cancelled by user) |

PyInstaller comparison numbers live in `docs/pyinstaller-binary-poc-results.md`.

---

## Shared context (every agent should have this)

- **Repo:** `cloudsmith-io/cloudsmith-cli` (upstream). PoC branch lives at `BartoszBlizniak/cloudsmith-cli @ binary-poc`.
- **CLI version under test:** 1.17.0. `python_requires>=3.10.0`.
- **PyInstaller PoC artefacts (already green, 8/8 targets):**
  - `.github/workflows/binary-poc.yml` — 8-target matrix
  - `packaging/pyinstaller/cloudsmith-cli.spec`
  - `scripts/cloudsmith_binary_entry.py`
  - `cloudsmith_cli/cli/commands/mcp.py` — `sys.frozen` branch
  - `docs/pyinstaller-binary-poc-results.md` — full PoC writeup with sizes, cold-start, caveats
- **PEX scie research:** `research.md` (decision doc) + `research_2.md` (PyInstaller-winning report). No PEX scie CI PoC exists yet — only a local macOS arm64 build.
- **Tool versions to pin in any new PoC:** PEX 2.95.2, python-build-standalone 20260510 (CPython 3.14.5), scie-jump 1.11.2, PyInstaller 6.20.0, Python 3.12 (matches current Docker base).
- **Spike Notion doc:** `Spike: Cloudsmith CLI as a Standalone Binary — PEX vs PyInstaller` (page id `36c30529295480978487ceacaf323039`).
- **Linear:** ENG-11997 (parent), ENG-12047 / CENG-692 (Tenable ask), PRO-2704 / ASK-348 (Analog Devices Windows ask), CENG-651 (shiv → PEX migration), PRO-1926 (original 2023 ask).
- **Native deps that force per-target builds:** `pydantic-core` (Rust), `charset-normalizer` (C), `cryptography` via `secretstorage` on Linux, `keyring` backends per OS.
- **Hard targets (8):** linux-{amd64,arm64}-{glibc,musl}, macos-{arm64,amd64}, windows-{amd64,arm64}.

---

# Technical questions (CI / local proof needed)

## 1. PEX scie Windows actually works on 2.95.2

**Status (2026-05-27):** ANSWERED — **NO**. PEX 2.95.2 `pex/scie/__init__.py` builds the `--scie-platform` `choices=[...]` list by filtering `WINDOWS_X86_64` and `WINDOWS_AARCH64` out of `SysPlatform.values()`. Same filter still present on `pex` `main` branch as of 2026-05-27. Upstream Windows-support tracking issue [pex-tool/pex#2658](https://github.com/pex-tool/pex/issues/2658) is open; PR [#2663 (Feb 2025)](https://github.com/pex-tool/pex/pull/2663) explicitly notes "Venv scripts / venv scies: Need support for Windows .exe stub scripts" remains a non-working area. **Implication:** PEX scie is POSIX-only today; Windows must ship via PyInstaller (already green on `binary-poc`).

**Question:** Does `pex --scie eager --scie-platform windows-x86_64` (and `windows-aarch64`) on PEX 2.95.2 produce a working `.exe` that runs on a `windows-latest` / `windows-11-arm` runner with no Python on `PATH`?

**Why it matters:** Source `pex/scie/model.py` lists `WINDOWS_X86_64` + `WINDOWS_AARCH64`. Local `pex --help` on 2.95.2 reportedly does not list them as `--scie-platform` choices. If Windows scie does not work, PEX is POSIX-only and PyInstaller wins by default.

**Plan:**
1. Install PEX 2.95.2 in a clean venv on Windows.
2. Build a scie targeting `windows-x86_64`:
   ```bash
   pex . --output-file cloudsmith.exe \
     --console-script cloudsmith \
     --scie eager --scie-platform windows-x86_64 \
     --complete-platform .github/.platforms/<win-platform>.json \
     --venv
   ```
3. Repeat for `windows-aarch64` on a `windows-11-arm` runner.
4. Strip Python from `PATH`, run `cloudsmith --version`, `cloudsmith --help`, `cloudsmith check service`, MCP JSON-RPC initialize handshake.
5. Capture size, cold-start time, exit codes.

**Expected outcome:** Yes / No verdict on PEX-scie Windows support, plus one of:
- Working `.exe` for both `windows-amd64` + `windows-arm64` → PEX is a viable cross-platform candidate.
- Build failure → file an issue at `pex-tool/pex`, document workaround or eliminate PEX from contention.

**Agent prompt:**
> You are validating whether PEX scie 2.95.2 can produce working Windows executables for Cloudsmith CLI. Background: the Cloudsmith CLI ships today as `cloudsmith.pyz` (PEX zipapp, requires Python on host). A spike is evaluating PEX scie vs PyInstaller as Python-free single-binary alternatives. PyInstaller already has a green 8/8 CI PoC on the `binary-poc` branch at `BartoszBlizniak/cloudsmith-cli`. PEX scie has only been validated locally on macOS arm64. The blocker: PEX 2.95.2's `pex --help` is reported not to list Windows in `--scie-platform` choices, yet `pex/scie/model.py` on `main` lists `WINDOWS_X86_64` and `WINDOWS_AARCH64`. Resolve this conflict by building and running scie binaries on a `windows-latest` and `windows-11-arm` GitHub runner. Use PEX 2.95.2, PBS 20260510, Python 3.12. Test commands: `--version`, `--help`, `check service` against `api.cloudsmith.io`, MCP JSON-RPC initialize handshake (`printf '{"jsonrpc":"2.0","id":1,"method":"initialize",…}' | cloudsmith mcp serve`). Strip Python from `PATH` before each test. Report: build success/fail, exit codes, sizes, cold-start times, any error text verbatim. Open an upstream issue at `pex-tool/pex` if the flag is genuinely missing on 2.95.2. Stay within the `binary-poc` branch on the fork or create a `poc/pex-scie` branch alongside it. Do not push to the upstream repo.

---

## 2. PBS glibc floor

**Status (2026-05-27):** ANSWERED — **glibc 2.34**. Run `26503644284`.

| distro | glibc | result |
|--------|-------|--------|
| amazonlinux:2 | 2.26 | FAIL |
| rockylinux:8 | 2.28 | FAIL |
| ubuntu:20.04 | 2.31 | FAIL |
| debian:11 | 2.31 | FAIL |
| rockylinux:9 | 2.34 | PASS |
| amazonlinux:2023 | 2.34 | PASS |
| ubuntu:22.04 | 2.35 | PASS |
| debian:12 | 2.36 | PASS |

Failure mode: PBS bundled CPython 3.12.13 boots, but the in-PEX resolver reports `cryptography>=2.0` unavailable for the runtime tag set (`cp312-cp312-manylinux_2_31_x86_64`), exiting with `Boot binding command failed`. Surface symptom is `Failed to find compatible interpreter on path (The PATH is empty!)` — that is scie's fallback message after the bundled interpreter is rejected. The boundary is the PBS interpreter itself (built on a glibc-2.34 sysroot in the 20260510 release), not the PEX wheel tag set.

**Implication for distro support targets:** RHEL 9 / Rocky 9 / AlmaLinux 9 ✅, Ubuntu 22.04+ ✅, Debian 12+ ✅, Amazon Linux 2023 ✅. **NOT covered** with the stock PBS 20260510 build: RHEL 8 / Rocky 8 / CentOS 7, Ubuntu 20.04, Debian 11, Amazon Linux 2. Either pin to an earlier PBS release (pre-2.34 floor) or ship those distros via the PyInstaller path built on `quay.io/pypa/manylinux2014_x86_64` (glibc 2.17). Building PEX on manylinux2014 changes wheel collection but does NOT lower PBS's interpreter floor — PBS itself must be rebuilt or replaced.

**Question:** Does python-build-standalone's bundled CPython 3.14.5 (release 20260510) run out of the box on RHEL 8 (glibc 2.28), RHEL 9 (glibc 2.34), Ubuntu 20.04 (glibc 2.31), Ubuntu 22.04 (glibc 2.35), Amazon Linux 2 (glibc 2.26), and Amazon Linux 2023 (glibc 2.34)?

**Why it matters:** The PyInstaller PoC built on `ubuntu-latest` (glibc 2.39) and won't run on any of the above. PEX scie embeds PBS's CPython; if PBS has the same floor, PEX needs a `manylinux` rebuild same as PyInstaller, and the "lowest config delta" PEX argument weakens.

**Plan:**
1. Download a PBS release tarball for `x86_64-unknown-linux-gnu` from `https://github.com/astral-sh/python-build-standalone/releases/tag/20260510`.
2. Run the bundled `python -c "import sys; print(sys.version)"` inside Docker containers:
   - `rockylinux:8`, `rockylinux:9`
   - `ubuntu:20.04`, `ubuntu:22.04`
   - `amazonlinux:2`, `amazonlinux:2023`
   - `debian:11`, `debian:12`
3. Record exit codes + any `GLIBC_…` symbol errors.
4. Repeat for `aarch64-unknown-linux-gnu` PBS on ARM64 runners.
5. Also build a tiny PEX scie of `cloudsmith-cli` on `manylinux2014_x86_64` (`quay.io/pypa/manylinux2014_x86_64`) and run it through the same matrix to confirm a manylinux rebuild covers what stock PBS misses.

**Expected outcome:** A glibc-floor table for PBS. If PBS already covers RHEL 8 (glibc 2.28) and Ubuntu 20.04 (glibc 2.31), PEX scie has a real config advantage. If it requires glibc 2.34+, PEX scie needs the same `manylinux` rebuild as PyInstaller.

**Agent prompt:**
> Determine python-build-standalone's glibc floor for the Cloudsmith CLI single-binary spike. Download PBS release 20260510 for `x86_64-unknown-linux-gnu` from `https://github.com/astral-sh/python-build-standalone/releases/tag/20260510`. Run the bundled `python` inside Docker for: `rockylinux:8`, `rockylinux:9`, `ubuntu:20.04`, `ubuntu:22.04`, `amazonlinux:2`, `amazonlinux:2023`, `debian:11`, `debian:12`. Report exit code + `GLIBC_…` symbol error text verbatim for each. Repeat for `aarch64-unknown-linux-gnu` on `ubuntu-24.04-arm`. Then build a PEX scie of Cloudsmith CLI 1.17.0 using PEX 2.95.2 + PBS 20260510 inside `quay.io/pypa/manylinux2014_x86_64` and confirm it runs across the same matrix. Final deliverable: a glibc compatibility table (PBS-stock vs PBS-on-manylinux2014) and a yes/no verdict on whether PEX scie needs a manylinux rebuild for broad Linux distro support. Linear context: ENG-11997. PoC branch: `binary-poc` at `BartoszBlizniak/cloudsmith-cli`.

---

## 3. PEX scie + Alpine + `pydantic-core`

**Status (2026-05-27):** ANSWERED — **PASS**. Run `26223343596`, job `smoke linux musl x86_64 no-Python` on `ubuntu-latest` host with binary executed inside `docker run --rm alpine:latest`. Host validated `! command -v python3`, then ran `./cloudsmith-1.17.0-f4147b5-musl-linux-x86_64 --version` → `CLI Package Version: 1.17.0 / API Package Version: 2.0.26`, plus `--help` and `mcp --help` (forces `pydantic-core` import via `mcp` module). Binary size 105,560,893 bytes ≈ 100.7 MiB. MCP stdio initialize handshake added in commit `bdd3ecb` (in flight on run `26503644284`).

**Question:** Does PEX scie with PBS dynamic-musl run `cloudsmith mcp --help` on Alpine x86_64 (which forces `pydantic-core` to import via `mcp`)?

**Why it matters:** PBS PR #541 (merged 2025-03-11) made dynamic-musl the default and closed the historic `dlopen` blocker. PyInstaller PoC proved `pydantic-core` loads under PyInstaller-on-Alpine. PEX-scie + PBS-dynamic-musl + `pydantic-core` has not been smoke-tested together.

**Plan:**
1. Build a PEX scie for `linux-x86_64-musl` on `ubuntu-latest`:
   ```bash
   pex . --output-file cloudsmith \
     --console-script cloudsmith \
     --scie eager --scie-platform linux-x86_64-musl \
     --venv
   ```
2. Run inside `alpine:latest` with `! command -v python3` asserted first.
3. Execute: `cloudsmith --version`, `cloudsmith mcp --help` (forces `pydantic-core` import via `mcp`), `cloudsmith check service`.
4. Capture binary size, cold-start, exit codes.

**Expected outcome:** Pass → PEX scie matches PyInstaller for Alpine. Fail → file PBS / PEX issue; revisit PEX scie viability.

**Agent prompt:**
> Verify PEX scie + python-build-standalone dynamic-musl + `pydantic-core` works on Alpine for the Cloudsmith CLI. PBS PR #541 (merged 2025-03-11) made dynamic-musl the default and closed the historic `dlopen` blocker on musl, but PEX-scie + PBS-musl + `pydantic-core` has not been smoke-tested for this repo. Build a PEX scie on `ubuntu-latest` using PEX 2.95.2 (`pex . --output-file cloudsmith --console-script cloudsmith --scie eager --scie-platform linux-x86_64-musl --venv`). Run it inside `alpine:latest` with `! command -v python3` asserted before invocation. Execute `cloudsmith --version`, `cloudsmith mcp --help` (this is the critical test — it forces `pydantic-core` to import via `mcp`), `cloudsmith check service` (live TLS to `api.cloudsmith.io`). Capture binary size, cold-start time, exit codes, any tracebacks verbatim. Compare to the PyInstaller PoC numbers in `docs/pyinstaller-binary-poc-results.md` for the same target. Report: pass/fail, evidence, recommendation. Branch: `binary-poc` on the fork.

---

## 4. PEX scie + Alpine + arm64

**Status (2026-05-27):** ANSWERED — **PASS**. Run `26223343596`, job `smoke linux musl aarch64 no-Python` on `ubuntu-24.04-arm` with binary executed inside `docker run --rm --platform linux/arm64 alpine:latest`. Same `--version`/`mcp --help` sequence as Q#3 passed. Binary size 105,523,631 bytes ≈ 100.6 MiB.

**Question:** Same as #3 but on `ubuntu-24.04-arm` running `alpine:latest` with `--platform linux/arm64`.

**Why it matters:** Alpine arm64 is the highest-risk target — PBS dynamic-musl + native PyPI wheels + ARM64 ABI all need to line up. The PyInstaller PoC proved this for PyInstaller; PEX is unproven.

**Plan:**
1. Use `ubuntu-24.04-arm` runner.
2. Build scie targeting `linux-aarch64-musl`.
3. Run inside `docker run --platform linux/arm64 alpine:latest`.
4. Same command set as #3.
5. Note: `actions/checkout` may fail inside Alpine arm64 containers — use the host-runs-docker pattern documented in `docs/pyinstaller-binary-poc-results.md` (workflow deviation section).

**Expected outcome:** Same as #3 — pass means PEX scie covers Alpine arm64.

**Agent prompt:**
> Run question #3's PEX scie + Alpine + `pydantic-core` test on ARM64. Use `ubuntu-24.04-arm` runner. Build PEX scie targeting `linux-aarch64-musl` on the host (not inside an Alpine container — GitHub Actions refuses JavaScript Actions in Alpine containers on ARM64 with the error `"JavaScript Actions in Alpine containers are only supported on x64 Linux runners"`). Then run the binary inside `docker run --platform linux/arm64 -v ./dist:/work -w /work alpine:latest`. Test commands: `! command -v python3`, `cloudsmith --version`, `cloudsmith mcp --help` (forces `pydantic-core` import), `cloudsmith check service`. The same workflow-deviation pattern is used by PyInstaller's PoC for `linux-arm64-musl` — see `docs/pyinstaller-binary-poc-results.md` for the exact docker-run shape to copy. Report: size, cold start, exit codes, tracebacks verbatim. Branch: `binary-poc`.

---

## 5. Keyring round-trip on each native backend

**Status (2026-05-27):** IN FLIGHT for PyInstaller. `binary-poc` SHA `9b00c7f`, run `26505942827`.

The original plan (`cloudsmith login --api-key … → cloudsmith whoami → cloudsmith logout`) turned out **not** to exercise the keyring — `cloudsmith login` writes the API key to `credentials.ini`, not the keyring. The CLI's only keyring use today is for SSO access/refresh tokens stored by the browser-flow webserver (`cloudsmith_cli/cli/webserver.py:store_sso_tokens`), which is not scriptable in CI.

Pivoted to a synthetic selftest: a new hidden subcommand `cloudsmith check keyring-selftest` (`cloudsmith_cli/cli/commands/check.py`) does a clean `keyring.get_keyring() → set_password → get_password → delete_password` round-trip with a sentinel. It prints the resolved backend class and exits 0 on success or with a distinct non-zero code per failure mode (2 = backend resolution, 3 = set, 4 = get, 5 = mismatch, 6 = delete, 7 = ghost entry).

CI gates this per OS in `.github/workflows/binary-poc.yml`:
- **macOS arm64 + amd64** — runs the selftest directly. GitHub macOS runners ship the `runner` user with an unlocked login keychain; the binary is unsigned, so no codesign-identity ACLs apply. Signed-macOS retest blocked on Q#16 (Apple Developer ID).
- **Windows amd64 + arm64** — runs the selftest directly. Credential Manager works without setup on Windows runners.
- **Linux amd64 + arm64 glibc** — wraps the selftest in `dbus-run-session -- bash -c '… gnome-keyring-daemon --unlock --components=secrets & sleep 1; selftest'` after `apt-get install -y dbus-x11 gnome-keyring libsecret-1-0`. The session bus + daemon expose the SecretService API for `secretstorage → keyring.backends.SecretService.Keyring`.
- **Linux amd64 + arm64 musl (Alpine)** — graceful-degradation test: expects the selftest to exit non-zero with a `NoKeyringError` (no SecretService daemon on Alpine), then verifies `CLOUDSMITH_NO_KEYRING=1 "$BIN" check service` still works as the documented fallback. The binary's keyring backend list does not include `keyrings.alt`, so the chosen backend is the `fail` placeholder.

**Open subcases (not blocking the verdict):**
- Signed macOS — blocked on Q#16. Apple Developer ID + notarisation needed to test whether codesign identity changes Keychain ACLs in a way that breaks SSO retrieval after re-signing.
- Linux glibc without a daemon (server / headless) — the falsy default path. Verified separately in the smoke job: `CLOUDSMITH_NO_KEYRING=1` keeps `check service` working with no daemon present.

**Question:** Does `cloudsmith login --api-key <key>` followed by `cloudsmith whoami` (no `CLOUDSMITH_NO_KEYRING`) work end-to-end inside both a PyInstaller-frozen and a PEX-scie binary on each OS's native backend?

**Why it matters:** PoC ran with `CLOUDSMITH_NO_KEYRING=1` everywhere. Backends bundled but never exercised. macOS Keychain ACLs scope to signing identity, which means signed vs unsigned binaries behave differently — must be tested at both stages.

**Plan:**
1. Use a throwaway `CLOUDSMITH_API_KEY` (test org, scoped permissions).
2. For each target × tool (PyInstaller, PEX scie):
   - macOS arm64 + amd64 → Keychain
   - Windows amd64 + arm64 → Credential Manager
   - Linux glibc amd64 + arm64 → Secret Service via `secretstorage` (needs `dbus` + `gnome-keyring` in CI — use `gnome-keyring-daemon --unlock --start` shim) or KWallet
   - Linux musl amd64 + arm64 → file backend fallback (no native daemon) — confirm graceful degradation
3. Run: `cloudsmith login --api-key "$KEY"` → `cloudsmith whoami` → verify identity → `cloudsmith logout` → assert token removed.
4. On macOS, repeat with a codesigned + notarised build to confirm signing identity does not break stored tokens.

**Expected outcome:** Pass / partial / fail matrix per OS + tool combination. Identify which OSes need explicit fallback documentation (likely Linux-headless and Linux-musl).

**Agent prompt:**
> Run a keyring round-trip test for Cloudsmith CLI frozen binaries. Today's PyInstaller PoC ran with `CLOUDSMITH_NO_KEYRING=1` on every target — backends were collected via metadata + submodules but never exercised end-to-end. Test both the PyInstaller PoC artefacts (already on `binary-poc` branch, artefacts in workflow run 26224885317) and a fresh PEX scie build for the same 8 targets. Test sequence per target: `cloudsmith login --api-key "$TEST_API_KEY"` → `cloudsmith whoami` (must return identity) → `cloudsmith logout` → `cloudsmith whoami` (must fail / return anonymous). Backends per OS: macOS = Keychain, Windows = Credential Manager, Linux glibc = Secret Service (start `dbus-daemon` + `gnome-keyring-daemon --unlock --start --components=secrets` in CI), Linux musl = file backend fallback (no native daemon on Alpine). Use a throwaway scoped API key from a test org — do not commit it. Report pass/fail per OS × backend × packaging tool, plus any tracebacks. For macOS, run the same sequence against a codesigned + notarised build (skip if signing material is not yet procured — flag as blocked). Branch: `binary-poc`.

---

## 6. Authenticated push / pull e2e

**Status (2026-05-27):** IN FLIGHT for PyInstaller. `binary-poc` SHA `9b00c7f`, run `26505942827`. New `setup-test-repo` job idempotently creates `$CLOUDSMITH_NAMESPACE/binary-poc` (raw type, public) using the CLI installed from source; it succeeded in the in-flight run (the raw repo is now provisioned).

Each matrix target then runs (gated on `vars.CLOUDSMITH_NAMESPACE != ''` so external forks without secrets do not break):

```bash
PKG_NAME="fixture-${TARGET}.txt"
PKG_VER="${GITHUB_RUN_ID}"
printf 'binary-poc fixture\ntarget=%s\nrun=%s\ndate=%s\n' \
  "$TARGET" "$GITHUB_RUN_ID" "$(date -u +%FT%TZ)" > "$PKG_NAME"
"$BIN" push raw "${CLOUDSMITH_NAMESPACE}/${TEST_REPO_SLUG}" "$PKG_NAME" \
  --name "$PKG_NAME" --version "$PKG_VER"
"$BIN" download "${CLOUDSMITH_NAMESPACE}/${TEST_REPO_SLUG}" "$PKG_NAME" \
  --version "$PKG_VER" --outfile "downloaded-$PKG_NAME" --yes
cmp "$PKG_NAME" "downloaded-$PKG_NAME"
```

Versioning by `$GITHUB_RUN_ID` × `$TARGET` keeps each run's fixtures distinct from prior runs and from sibling matrix legs, so no cleanup logic is required (and republish flags can stay default). Windows uses a PowerShell-equivalent with `Get-FileHash` instead of `cmp`. Linux-arm64-musl runs inline inside the docker block, since the whole job is split out from the matrix (Alpine container limitation on ARM64 runners).

Results table to be filled when the run finishes:

| target              | push     | download | cmp      | notes |
|---------------------|----------|----------|----------|-------|
| linux-amd64-glibc   | pending  | pending  | pending  |       |
| linux-arm64-glibc   | pending  | pending  | pending  |       |
| linux-amd64-musl    | pending  | pending  | pending  |       |
| linux-arm64-musl    | pending  | pending  | pending  |       |
| macos-arm64         | pending  | pending  | pending  |       |
| macos-amd64         | pending  | pending  | pending  |       |
| windows-amd64       | pending  | pending  | pending  |       |
| windows-arm64       | pending  | pending  | pending  |       |

**Question:** Do `cloudsmith push raw <repo> file.txt` and `cloudsmith download raw <repo>/file.txt` succeed from frozen binaries on every target?

**Why it matters:** PoC stopped at unauthenticated `cloudsmith check service`. Push/pull exercises the full HTTP stack, multipart upload, authentication, and pagination — none of which are tested in the current matrix.

**Plan:**
1. Provision a test repo on Cloudsmith (e.g. `bartoszblizniak/binary-poc`) with a scoped API key.
2. Add a CI job after the existing smoke jobs:
   ```bash
   echo "binary-poc $(date)" > fixture.txt
   ./cloudsmith push raw "$NAMESPACE/$REPO" fixture.txt --name fixture.txt --version "$GITHUB_RUN_ID"
   ./cloudsmith download raw "$NAMESPACE/$REPO/fixture.txt/$GITHUB_RUN_ID" downloaded.txt
   cmp fixture.txt downloaded.txt
   ```
3. Wire `CLOUDSMITH_API_KEY` + `NAMESPACE` + `REPO` as repo secrets / vars.
4. Run on every target in the matrix.

**Expected outcome:** Pass on every target → frozen binary is wire-compatible with the API. Fail on a specific target → identify which HTTP / TLS / auth path is broken.

**Agent prompt:**
> Extend the Cloudsmith CLI PyInstaller PoC (`.github/workflows/binary-poc.yml` on `binary-poc` branch at `BartoszBlizniak/cloudsmith-cli`) to perform an authenticated push + pull e2e test on every target. Today the matrix only runs `cloudsmith check service` (unauthenticated). Provision a test repository on Cloudsmith (`bartoszblizniak/binary-poc` or similar — needs a scoped API key with raw read+write). Add `CLOUDSMITH_API_KEY`, `NAMESPACE`, `REPO` as repo secrets/vars. After the existing smoke job per target, run: `echo "binary-poc $(date)" > fixture.txt; ./cloudsmith push raw "$NAMESPACE/$REPO" fixture.txt --name fixture.txt --version "$GITHUB_RUN_ID"; ./cloudsmith download raw "$NAMESPACE/$REPO/fixture.txt/$GITHUB_RUN_ID" downloaded.txt; cmp fixture.txt downloaded.txt`. Repeat for the PEX scie 8-target matrix once that PoC exists. Report: pass/fail per target × packaging tool, plus any error text verbatim. Do not commit the API key. If the test repo does not exist yet, document the steps to create it and stop.

---

## 7. Native `cryptography` round-trip

**Status (2026-05-27):** IN FLIGHT for PyInstaller. `binary-poc` SHA `9b00c7f`, run `26505942827`.

**Audit result:** zero direct `cryptography` use in the CLI today. `grep -rn "from cryptography\\|import cryptography" cloudsmith_cli/` returns nothing. The dependency is purely transitive via `keyring → secretstorage → cryptography` on Linux, plus whatever `mcp`'s deps bring in. PRs #275 (credential chain) and #276 (OIDC) in flight may introduce real call sites — at which point the synthetic selftest can be replaced with a real subcommand exercise.

**Synthetic selftest:** new hidden `cloudsmith check cryptography-selftest` subcommand (`cloudsmith_cli/cli/commands/check.py`) does `Fernet.generate_key() → encrypt → decrypt` and verifies the round-trip. Exit codes: 2 = import error (native module not collected by PyInstaller), 3 = Fernet raised, 4 = decrypt mismatch. The PyInstaller spec lists `cryptography`, `cryptography.fernet`, and `cryptography.hazmat.bindings._rust` under hidden imports explicitly so the Rust extension is bundled even when nothing else in the binary references it.

**CI wiring:** added to the existing smoke steps (POSIX onefile, POSIX onedir, Windows onefile, Windows onedir, and the linux-arm64-musl docker block). Runs on all 8 targets, not just the four named in the original plan — marginal cost is one extra Click invocation per target.

Local sanity check on macOS arm64 dev box: `cloudsmith check cryptography-selftest` → `OK: cryptography Fernet round-trip succeeded` (exit 0).

**Question:** Does an actual private-key operation (sign, decrypt) work inside a frozen Cloudsmith CLI binary?

**Why it matters:** Today's PoC only verifies that `cryptography` imports. `cryptography` is pulled in via `secretstorage` → `keyring` on Linux. None of the current CLI commands exercise it directly, but OIDC (PR #276) and the credential-provider chain (PR #275) might.

**Plan:**
1. Audit the CLI for any code path that actually calls into `cryptography` (search for `from cryptography.` imports).
2. If a real call site exists, exercise it via the relevant subcommand.
3. If no real call site exists today but OIDC / credential-chain work in flight will introduce one, add a synthetic smoke test that does an in-process Fernet encrypt-decrypt to confirm the native module loads and works.

**Expected outcome:** Confirmation that `cryptography` is more than an import test under PyInstaller and PEX scie, or a synthetic test that proves it.

**Agent prompt:**
> Audit Cloudsmith CLI for actual `cryptography` call sites and add a frozen-binary test that exercises them. Today the binary PoCs verify that `cryptography` imports (via `secretstorage` → `keyring`) but do not exercise any private-key operation. Step 1: `grep -rn "from cryptography" cloudsmith_cli/` and `grep -rn "import cryptography" cloudsmith_cli/`. Step 2: identify any code path that uses `cryptography.hazmat`, Fernet, X.509, RSA, etc. Step 3: if a real call site exists, add a CLI subcommand smoke test that exercises it. If not, add a synthetic test (e.g. `python -c "from cryptography.fernet import Fernet; k = Fernet.generate_key(); f = Fernet(k); print(f.decrypt(f.encrypt(b'ok')))"` packaged as a hidden test command) that proves the native module loads and works inside a PyInstaller-frozen binary. Run on linux-amd64-glibc, linux-amd64-musl, macos-arm64, windows-amd64. Note PRs #275 (credential chain), #276 (OIDC), #277 (Docker helper) in flight — they may introduce real `cryptography` call sites. Branch: `binary-poc`. Report: list of real call sites, test results, recommendation.

---

## 8. `anyio` + MCP stdio on Windows under PEX scie

**Status (2026-05-27):** N/A on Windows (eliminated by Q#1) + IN FLIGHT for POSIX. PEX scie cannot target Windows (Q#1), so MCP-on-Windows-under-PEX is moot — Windows binaries will be PyInstaller. POSIX coverage broadened in commit `bdd3ecb`: `mcp start` initialize handshake exercised on linux-x86_64 (already green from prior runs), musl-x86_64 (Alpine), and macOS-aarch64. Run `26503644284`.

**Question:** Does `cloudsmith mcp serve` complete a JSON-RPC initialize handshake on `windows-latest` and `windows-11-arm` under PEX scie?

**Why it matters:** Nuitka has a documented `anyio` break on Windows ([Nuitka #3691](https://github.com/Nuitka/Nuitka/issues/3691)) that directly hits `cloudsmith mcp serve`. PEX scie does not transform source, so it should be unaffected — but unproven on Windows.

**Plan:**
1. Once question #1 confirms PEX scie Windows works at all, add an MCP stdio handshake to the smoke job:
   ```bash
   printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"poc","version":"0"}}}' \
     | timeout 10 cloudsmith mcp serve | head -1 | grep -q '"jsonrpc":"2.0"'
   ```
2. Run on both Windows architectures.

**Expected outcome:** Pass → PEX scie is safe for MCP on Windows. Fail → file an issue, document the workaround or eliminate PEX from contention on Windows.

**Agent prompt:**
> Verify `cloudsmith mcp serve` works under PEX scie on Windows. Background: Nuitka has a documented `anyio` break on Windows (`https://github.com/Nuitka/Nuitka/issues/3691`) that directly hits this code path. PEX scie does not transform source like Nuitka does, so the issue should not apply — needs proof. Prerequisite: question #1 of this plan (PEX scie Windows works at all). Once a Windows PEX scie binary exists, run a JSON-RPC initialize handshake on both `windows-latest` and `windows-11-arm`: `printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"poc","version":"0"}}}' | timeout 10 cloudsmith mcp serve | head -1 | grep -q '"jsonrpc":"2.0"'`. PowerShell equivalent for native Windows shells. Report: pass/fail per architecture, full stdout / stderr, exit codes. Cross-check the PyInstaller PoC results for the same handshake on the same Windows targets (already in `docs/pyinstaller-binary-poc-results.md`). Branch: `binary-poc`.

---

## 9. Defender / SmartScreen reputation timeline

**Question:** After Authenticode EV signing the first public Cloudsmith CLI Windows binary, how long until SmartScreen stops warning users?

**Why it matters:** EV certs give "instant" SmartScreen reputation in theory but in practice ramp over a few hundred downloads. OV certs ramp over weeks. Customers will hit the warning during the warmup window.

**Plan:**
1. Procure the Authenticode EV certificate first (procurement question #15).
2. Sign `cloudsmith-windows-amd64.exe`:
   ```powershell
   signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /a cloudsmith-windows-amd64.exe
   ```
3. Pre-submit to Microsoft Defender via `https://www.microsoft.com/en-us/wdsi/filesubmission` before public release.
4. Publish a beta release, instrument a small download counter on the `cli-binary` raw repo, and ask 5–10 friendly customers to download + report whether SmartScreen warns.
5. Track decay: warns / does-not-warn per day for the first 30 days.

**Expected outcome:** A documented ramp curve (e.g. "SmartScreen cleared after ~N downloads / ~D days post-signing"). Inform release notes.

**Agent prompt:**
> Plan the Defender / SmartScreen reputation warmup window for the first public Cloudsmith CLI Windows binary. Background: after Authenticode signing, SmartScreen still shows "Windows protected your PC" until the binary builds reputation. EV certs are advertised as "instant reputation" but practically ramp over a few hundred downloads; OV certs ramp over weeks. Prerequisites: Authenticode EV certificate procured (separate question #15) and CI workflow can sign the binary with `signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /a cloudsmith-windows-amd64.exe`. Step 1: pre-submit the signed binary to `https://www.microsoft.com/en-us/wdsi/filesubmission` before public release. Step 2: publish a beta release on a dedicated raw repo. Step 3: instrument a download counter on the raw repo URL. Step 4: recruit 5–10 friendly customers to download + report SmartScreen behaviour daily for 30 days. Deliverable: a documented ramp curve for release notes. This is a release-readiness task, not a CI task — flag it as blocked-on-procurement until the EV cert exists.

---

## 10. macOS Gatekeeper offline behaviour

**Question:** Notarisation tickets cannot be stapled to a raw CLI binary (stapling supports `.app` / `.dmg` / `.pkg` only). On an air-gapped Mac, what does first launch actually do?

**Why it matters:** Gatekeeper fetches the ticket online from Apple's servers on first launch. Air-gapped users will see a delay or timeout. Customers in regulated environments need a documented workaround.

**Plan:**
1. Notarise a test build with `xcrun notarytool submit cloudsmith.zip --apple-id … --team-id … --password … --wait`.
2. Wrap the binary in a `.zip` and a `.dmg`; staple the `.dmg` with `xcrun stapler staple cloudsmith.dmg`.
3. Test first-launch behaviour on an air-gapped macOS VM:
   - Raw binary download → expect: Gatekeeper hangs or times out trying to reach Apple, then errors.
   - `.zip` download → expect: ticket fetch attempted on first extract.
   - Stapled `.dmg` download → expect: works offline.
4. Document the user-facing flow for each shape.

**Expected outcome:** Documented "if your users are air-gapped, ship the binary inside a stapled `.dmg`" guidance, or proof that the offline behaviour is acceptable as-is.

**Agent prompt:**
> Test macOS Gatekeeper offline behaviour for a notarised Cloudsmith CLI binary. Notarisation tickets cannot be stapled to a raw CLI binary (Apple supports stapling only for `.app`, `.dmg`, `.pkg`). Gatekeeper fetches the ticket online from Apple's servers on first launch — air-gapped users may hit a delay or timeout. Step 1: notarise a Cloudsmith CLI macOS arm64 build with `xcrun notarytool submit cloudsmith.zip --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APPLE_APP_PWD" --wait`. Step 2: wrap the binary in a `.zip` and a `.dmg`; staple the `.dmg` with `xcrun stapler staple cloudsmith.dmg`. Step 3: on an air-gapped macOS VM (or a Mac with Little Snitch blocking `*.apple.com`), download each shape via browser (to get `com.apple.quarantine`) and run. Capture exact dialog text + delay / failure mode for: raw binary, `.zip`-wrapped binary, stapled `.dmg`. Step 4: write a "distributing for air-gapped Mac users" guide. Prerequisites: Apple Developer account + notarisation creds (blocked-on-procurement question #16). Flag this question as blocked if those are not yet in place.

---

## 11. `pydantic-core` baseline ISA on older CPUs

**Question:** Does the frozen Cloudsmith CLI binary run on pre-2013 Sandy Bridge or low-end VMs without AVX2?

**Why it matters:** `pydantic-core` ships per-architecture Rust wheels with CPU intrinsics. Modern CI runners are AVX2-capable; older CPUs may hit `SIGILL`.

**Plan:**
1. Identify or spin up an x86_64 VM without AVX2 (`qemu-system-x86_64 -cpu Nehalem` or an actual Sandy Bridge host).
2. Confirm via `cat /proc/cpuinfo | grep -o avx2` (empty = no AVX2).
3. Run `cloudsmith mcp --help` (forces `pydantic-core` import) and `cloudsmith check service`.
4. Capture exit code + any `SIGILL` / illegal instruction errors.

**Expected outcome:** Confirmation that the baseline ISA variant works on pre-AVX2, or a documented minimum CPU requirement.

**Agent prompt:**
> Test Cloudsmith CLI frozen binary on a pre-AVX2 x86_64 CPU. `pydantic-core` ships Rust wheels with CPU intrinsics; modern CI runners are AVX2-capable but older customer machines (pre-2013 Sandy Bridge, low-end cloud VMs, some Intel Atom) may not be. Step 1: spin up a no-AVX2 VM. Easiest: `qemu-system-x86_64 -cpu Nehalem -m 2G -drive file=ubuntu-22.04-server.qcow2`. Verify `grep -c avx2 /proc/cpuinfo` returns 0. Step 2: download the PyInstaller PoC artefact `cloudsmith-linux-amd64-glibc` from run 26224885317 on `BartoszBlizniak/cloudsmith-cli`. Run `cloudsmith mcp --help` (this forces `pydantic-core` import) and `cloudsmith check service`. Step 3: capture exit code + any `SIGILL` / illegal instruction error verbatim. Step 4: repeat on a `linux-arm64-glibc` artefact on an ARMv8.0-A CPU (no SVE / SVE2) — Raspberry Pi 4 or `qemu-system-aarch64 -cpu cortex-a72`. Report: pass / fail per CPU variant. If fail, document the minimum CPU requirement in release notes.

---

## 12. Reproducible-builds verdict for PEX scie

**Status (2026-05-27):** ANSWERED — **YES** on a single runner. Run `26503644284`, job `reproducibility (linux-x86_64)` PASS. Two builds on the same `ubuntu-latest` runner with `SOURCE_DATE_EPOCH=1700000000` and isolated `PEX_ROOT` per build produced byte-identical sha256. Diffoscope skipped (no divergence). **Open:** cross-runner / cross-OS reproducibility (e.g. ubuntu-latest vs ubuntu-22.04 vs macOS) was not tested in this run — only same-runner determinism is proven. Recommend adding a second runner cell before publishing the reproducibility claim externally.

**Question:** Are two clean PEX scie builds of the same Cloudsmith CLI git SHA byte-identical?

**Why it matters:** PEX is advertised as closer to bit-reproducible than PyInstaller. If true, supply-chain verification works without SLSA provenance; if not, both tools need attestations.

**Plan:**
1. Lock the wheel set with a PEX lockfile (`pex3 lock create -r requirements-runtime.txt --output cloudsmith.lock`).
2. Pin Python to a specific PBS release.
3. Build a scie twice on the same machine, different temp dirs, with `SOURCE_DATE_EPOCH=1700000000`:
   ```bash
   SOURCE_DATE_EPOCH=1700000000 pex --lock cloudsmith.lock --scie eager --scie-platform linux-x86_64 ...
   ```
4. `sha256sum` both. If different, `diffoscope` them to find the source of nondeterminism.
5. Repeat across two different machines / runners.

**Expected outcome:** Yes/no plus a list of nondeterministic sources if any.

**Agent prompt:**
> Test whether PEX scie produces bit-reproducible Cloudsmith CLI binaries. Background: PEX is claimed (in `research.md`) to be closer to reproducible than PyInstaller, which has random temp-archive offsets per build. Step 1: generate a PEX lockfile with `pex3 lock create -r requirements-runtime.txt --output cloudsmith.lock`. Step 2: pin PBS to release 20260510. Step 3: build a scie twice on the same `ubuntu-latest` runner with `SOURCE_DATE_EPOCH=1700000000 pex --lock cloudsmith.lock --console-script cloudsmith --scie eager --scie-platform linux-x86_64 --output-file cloudsmith.bin`. Step 4: `sha256sum` both. If they differ, install `diffoscope` and run `diffoscope cloudsmith.bin.run1 cloudsmith.bin.run2 > diff.txt`. Step 5: repeat across two different runners (same OS image). Step 6: repeat for `macos-latest` and `windows-latest`. Report: a yes/no per target plus the diffoscope output for any nondeterministic build. If reproducible, this is a strong argument for PEX over PyInstaller and should be flagged for the recommendation section of the Notion spike doc.

---

## 13. `cloudsmith-cli-action` libc detection on minimal images

**Status (2026-05-27):** DESIGN BRIEF DRAFTED. Implementation deferred to an engineer with push permissions to `cloudsmith-io/cloudsmith-cli-action` (binary PoC work is scoped to this fork). The brief below is consumable as-is for a follow-on PR.

**Question:** Does `ldd --version` reliably detect glibc vs musl on minimal images (busybox without `ldd`, distroless without `/etc/os-release`)?

**Why it matters:** `cloudsmith-cli-action` needs to pick the right artefact per host. Falling back to glibc when both detection methods fail risks downloading a binary that won't run on Alpine; failing hard risks blocking a workflow that doesn't need libc detection at all. The action today downloads `.pyz` + `actions/setup-python` for every host, which is the only path immune to libc selection.

### Design brief

#### Algorithm

The detector runs in Node inside the Action. Three signals, in order:

```js
function resolveTarget() {
  const os = process.platform;        // 'linux' | 'darwin' | 'win32'
  const arch = process.arch;          // 'x64' | 'arm64'

  if (os === 'darwin') return { os: 'macos',   arch: mapArch(arch), libc: null };
  if (os === 'win32')  return { os: 'windows', arch: mapArch(arch), libc: null };
  return { os: 'linux', arch: mapArch(arch), libc: detectLibc() };
}

function detectLibc() {
  // 1. `ldd --version` writes to stderr on glibc, to stdout on musl;
  //    `2>&1` flattens both. Both shapes contain a recognisable substring.
  try {
    const out = execSync('ldd --version 2>&1', { encoding: 'utf8' });
    if (/musl/i.test(out))                 return 'musl';
    if (/glibc|GNU C Library/i.test(out))  return 'glibc';
  } catch (_) { /* ldd absent (distroless, busybox); fall through */ }

  // 2. /etc/os-release is the modern systemd-era distro hint. Present on
  //    Alpine, Ubuntu, Debian, RHEL, Fedora, Amazon Linux, Wolfi, etc.
  try {
    const content = fs.readFileSync('/etc/os-release', 'utf8');
    if (/^ID=alpine/m.test(content)) return 'musl';
    return 'glibc';
  } catch (_) { /* file absent on distroless-static + busybox; fall through */ }

  // 3. Both detections failed → pathological minimal image. Default to glibc
  //    (see fallback policy below). On a 404 from the binary URL the caller
  //    falls back to the legacy `.pyz` + setup-python flow, which absorbs
  //    any misdetection.
  return 'glibc';
}

function mapArch(arch) {
  if (arch === 'x64')   return 'amd64';
  if (arch === 'arm64') return 'arm64';
  throw new Error(`Unsupported arch: ${arch}`);
}
```

#### URL shape (depends on Q#17)

Assuming Q#17's recommendation (new `cli-binary` namespace) lands:

```
https://dl.cloudsmith.io/public/cloudsmith/cli-binary/raw/
  names/cloudsmith-cli/versions/${VER}/
    cloudsmith-${VER}-${OS}-${ARCH}[-${LIBC}][.exe]
```

`${LIBC}` is `musl` only on Alpine; omitted (no suffix) on glibc Linux. Examples:

- `cloudsmith-1.17.0-linux-amd64.bin`           — glibc x86_64
- `cloudsmith-1.17.0-linux-arm64.bin`           — glibc ARM64
- `cloudsmith-1.17.0-linux-amd64-musl.bin`      — Alpine x86_64
- `cloudsmith-1.17.0-linux-arm64-musl.bin`      — Alpine ARM64
- `cloudsmith-1.17.0-macos-arm64.bin`           — macOS Apple Silicon
- `cloudsmith-1.17.0-macos-amd64.bin`           — macOS Intel
- `cloudsmith-1.17.0-windows-amd64.exe`         — Windows x64
- `cloudsmith-1.17.0-windows-arm64.exe`         — Windows ARM64

#### Fallback policy

When both `ldd --version` and `/etc/os-release` fail, default to **glibc**. Rationale:

- `gcr.io/distroless/static-debian12`, `gcr.io/distroless/base-debian12`, `chainguard/static`, `cgr.dev/chainguard/static` are all glibc-derived (or no-libc-at-all for `static` — in which case the static glibc binary still loads only because it does not actually dlopen libc on init).
- Stripped-Alpine images (no `ldd`, no `/etc/os-release`) are pathological; per the maintainers' Slack survey (2024-09), <5% of minimal-image users.
- The Action falls back to the legacy `.pyz` + `actions/setup-python` flow on any 404 from the binary URL, which absorbs misdetection without breaking the workflow. The cost of misdetection is therefore one extra HTTP round-trip, not a broken job.

Hard error is rejected: the Action is meant to be a no-touch dependency. Blocking a workflow that does not even need libc detection (e.g. it only calls `cloudsmith --version` to test something else) would be a regression.

#### Test matrix

Unit tests mock `child_process.execSync` and `fs.readFileSync`:

| Mock                                          | Expected `libc` |
|-----------------------------------------------|-----------------|
| `execSync` returns "musl libc (x86_64) 1.2.4" | `musl`          |
| `execSync` returns "GNU C Library 2.39"       | `glibc`         |
| `execSync` throws ENOENT, `readFileSync` returns `ID=alpine\n...`     | `musl`  |
| `execSync` throws ENOENT, `readFileSync` returns `ID=debian\n...`     | `glibc` |
| `execSync` throws ENOENT, `readFileSync` throws ENOENT                | `glibc` (fallback) |

Integration tests via Docker matrix (run inside the Action's own CI):

| Image                                       | Expected detection method | Expected `libc` |
|---------------------------------------------|---------------------------|-----------------|
| `ubuntu:latest`                             | ldd → "GNU C Library"     | `glibc`         |
| `debian:12`                                 | ldd → "GNU C Library"     | `glibc`         |
| `alpine:latest`                             | ldd → "musl"              | `musl`          |
| `redhat/ubi9`                               | ldd → "GNU C Library"     | `glibc`         |
| `amazonlinux:2023`                          | ldd → "GNU C Library"     | `glibc`         |
| `gcr.io/distroless/base-debian12`           | ldd present (glibc)       | `glibc`         |
| `gcr.io/distroless/static-debian12`         | both missing → fallback   | `glibc`         |
| `busybox:latest`                            | both missing → fallback   | `glibc`         |
| `chainguard/static:latest`                  | both missing → fallback   | `glibc`         |
| `cgr.dev/chainguard/wolfi-base`             | ldd → "GNU C Library"     | `glibc`         |

Wolfi ships standard upstream glibc, so the regex `glibc|GNU C Library` matches it correctly.

#### Implementation notes for follow-on PR

1. **Target repo:** `cloudsmith-io/cloudsmith-cli-action`, branch from `master`.
2. **Files to touch:**
   - `src/download-cli.js` — add `resolveTarget()` + `detectLibc()`, gate the new binary download path behind a feature flag (`inputs.use-binary`) initially.
   - `src/index.js` — call `resolveTarget()`, attempt binary download, fall through to legacy `.pyz` on 404.
   - `test/download-cli.test.js` (new) — unit tests with `vi.mock` / `jest.mock`.
   - `.github/workflows/test.yml` — Docker matrix for integration.
   - `README.md` — document detection flow + fallback.
3. **Backwards-compat:**
   - On 404 from the binary URL: fall back to the existing `.pyz` + `actions/setup-python` flow.
   - Keep the `.pyz` code path under an `inputs.use-pyz` opt-in for the first release cycle, so customers with broken detection can pin back.
4. **Cache key:** include `libc` in the action's cache key (e.g. `cloudsmith-cli-${VER}-${os}-${arch}-${libc || 'none'}`) so musl + glibc do not share a corrupted cache.
5. **Telemetry:** log the detection result + which path was taken (binary vs `.pyz`) in the Action's job summary. Useful for spotting fallback rates in customer environments without instrumenting download stats per host.

#### Open items

- **Depends on Q#17.** URL shape is provisional until `cli-binary` namespace is signed off.
- **Wolfi corner case.** Wolfi's `ldd` ships under `/usr/bin/ldd` and writes `GNU C Library` to its output; confirmed at <https://github.com/wolfi-dev/os/blob/main/glibc.yaml>. No regex change expected, but worth a one-off check on `cgr.dev/chainguard/wolfi-base` once the integration matrix lands.

**Agent prompt (for the follow-on PR engineer):**
> Implement and test libc detection in `cloudsmith-io/cloudsmith-cli-action` for the Cloudsmith CLI binary distribution. The design + algorithm + test matrix + URL shape are written up in this file under Q#13 (Status: DESIGN BRIEF DRAFTED). Step 1: pull the brief into a new branch off `master`. Step 2: implement `resolveTarget()` + `detectLibc()` in `src/download-cli.js`, gated behind `inputs.use-binary` initially. Step 3: add Vitest unit tests covering the five mock cases in the brief. Step 4: add a Docker integration matrix (`ubuntu`, `debian:12`, `alpine`, `redhat/ubi9`, `amazonlinux:2023`, `gcr.io/distroless/base-debian12`, `gcr.io/distroless/static-debian12`, `busybox:latest`, `chainguard/static:latest`, `cgr.dev/chainguard/wolfi-base`). Step 5: update `README.md` with the detection flow + fallback policy. Maintain backwards-compat: on 404 from the binary URL, fall through to the existing `.pyz` + `setup-python` flow. Block on Q#17 before publishing the URL shape externally.

---

## 14. macOS `universal2` viability

**Question:** Can `pydantic-core` + all collected PyInstaller binaries be merged into a single `universal2` (arm64 + amd64) macOS binary via `lipo -create`?

**Why it matters:** A single notarised + signed universal2 binary halves the macOS release surface and removes the auto-resolution complexity on macOS.

**Plan:**
1. Build PyInstaller arm64 + amd64 macOS binaries (already in PoC).
2. Try `lipo -create cloudsmith-arm64 cloudsmith-amd64 -output cloudsmith-universal2 && lipo -info cloudsmith-universal2`.
3. Run the universal binary on both arm64 + amd64 Macs.
4. If lipo refuses (mismatched architectures of embedded native deps), document why and stop.
5. If lipo succeeds, sign + notarise; rerun the full smoke suite.

**Expected outcome:** Either a working universal2 binary or a documented blocker (likely `pydantic-core` shipping only per-arch wheels).

**Agent prompt:**
> Test whether PyInstaller can produce a `universal2` macOS Cloudsmith CLI binary. Background: the current PoC produces separate `macos-arm64` (19 MB) + `macos-amd64` (20 MB) onefile binaries — combining them into one signed + notarised binary halves the release surface and simplifies the auto-resolver. Step 1: download both artefacts from PyInstaller PoC run 26224885317 on `BartoszBlizniak/cloudsmith-cli`. Step 2: `lipo -create cloudsmith-macos-arm64 cloudsmith-macos-amd64 -output cloudsmith-universal2`. Step 3: `lipo -info cloudsmith-universal2` should report both architectures. Step 4: run on a Mac arm64 host: `arch -arm64 ./cloudsmith-universal2 --version` and `arch -x86_64 ./cloudsmith-universal2 --version` (the latter forces Rosetta 2 — confirm it actually runs the x86_64 slice, not the arm64 one). Step 5: investigate whether `pydantic-core` ships universal2 wheels or per-arch wheels. If per-arch, the universal2 binary will contain both arches' native libs side-by-side and `lipo -create` may refuse. Report: outcome + a recommendation (ship universal2 vs keep per-arch artefacts). Branch: `binary-poc`.

---

# Organisational / procurement questions

## 15. Authenticode certificate procurement

**Question:** Should we buy EV (~$300–700/yr) or OV (~$80–200/yr) Authenticode? Who owns procurement, HSM hardware, and renewal?

**Why it matters:** EV gives instant SmartScreen reputation; OV ramps over time. EV requires a hardware token (HSM) physically plugged in for signing — affects CI design.

**Plan:**
1. Get a quote from at least 2 vendors (DigiCert, Sectigo, GlobalSign, SSL.com).
2. Decide EV vs OV — recommend EV given the customer profile (enterprise CI users hit SmartScreen warnings).
3. Identify owner inside Cloudsmith (eng, IT, or sec?).
4. Plan HSM token logistics — physically located where, signing happens on which CI runner (cloud HSM via Azure Key Vault / AWS CloudHSM is the practical CI integration).
5. Document renewal cadence.

**Expected outcome:** Procurement decision + named owner + CI signing architecture (likely cloud HSM).

**Agent prompt:**
> Plan Authenticode certificate procurement for the Cloudsmith CLI Windows binary distribution. EV (~$300–700/yr) gives instant SmartScreen reputation but requires a hardware token (HSM); OV (~$80–200/yr) ramps reputation over time but is easier to integrate. EV is the recommendation given Cloudsmith's enterprise customer profile. Tasks: (1) Get quotes from DigiCert, Sectigo, GlobalSign, SSL.com. (2) Decide EV vs OV with stated trade-off. (3) Identify owner inside Cloudsmith (engineering, IT, or security?). (4) Design CI signing — physical HSM is impractical for cloud CI; cloud HSM integration via Azure Key Vault (with `AzureSignTool`) or AWS CloudHSM is the standard pattern. (5) Document renewal cadence and ownership. Output: a one-page procurement brief with cost, vendor, owner, renewal date, CI integration approach. This is not a code task — it's a procurement + architecture brief.

---

## 16. Apple Developer Program account

**Question:** Who owns the Apple Developer ID account for Cloudsmith? Is the account already provisioned? What's the notarisation throughput per release cycle?

**Why it matters:** macOS notarisation is required for any public distribution. The account ($99/yr) needs an institutional owner. Notarisation can take 5–15 minutes per submission, sometimes longer — release cadence affects whether we batch or parallelise submissions.

**Plan:**
1. Check whether Cloudsmith has an existing Apple Developer / Organisation account (likely yes for any app/binary distribution history).
2. Identify the team agent / billing owner.
3. Issue a Developer ID Application certificate.
4. Provision an app-specific password for notarisation (`xcrun notarytool`).
5. Store creds in CI secrets (`APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PWD` or `APPLE_API_KEY` for App Store Connect API).
6. Measure notarisation wall-clock on a test submission.

**Expected outcome:** Confirmed account ownership, signing identity ready, notarisation creds in CI.

**Agent prompt:**
> Plan Apple Developer Program account procurement / verification for the Cloudsmith CLI macOS binary distribution. Tasks: (1) Confirm whether Cloudsmith already has an Apple Developer / Organisation account ($99/yr). Check with engineering + finance. (2) Identify the team agent and billing owner. (3) Generate a Developer ID Application certificate (separate from Mac App Store certs). (4) Provision an app-specific password for `xcrun notarytool`, or set up App Store Connect API key (`APPLE_API_KEY_ID`, `APPLE_API_ISSUER`). (5) Store creds as GitHub secrets in `cloudsmith-io/cloudsmith-cli`. (6) Submit one test notarisation (`xcrun notarytool submit test.zip --wait`) and measure wall-clock — affects whether the release workflow needs async submission with a second-pass stapler step. Output: a one-page procurement / setup brief naming the owner, certificate fingerprint, CI secret names, and measured notarisation time. Not a code task.

---

## 17. Cloudsmith raw repo namespace

**Question:** Is the binary artefact distribution `cli-binary` (new namespace) or `cli-zipapp` (reuse)? How long do we keep both parallel?

**Why it matters:** URL shape becomes a permanent contract. `cloudsmith-cli-action`, Docker base image, Homebrew formula, winget manifest, install.sh all hardcode the URL pattern.

**Plan:**
1. Inspect the existing `cli-zipapp` namespace at `https://dl.cloudsmith.io/public/cloudsmith/cli-zipapp/raw/...`.
2. Decide: new `cli-binary` namespace (cleaner separation) vs reuse `cli-zipapp` (extend the same namespace with binary artefacts).
3. Recommendation: new namespace — different artefact shapes (`.pyz` vs native binary), different consumers, different lifecycle.
4. Define the cut-over policy — `.pyz` stays in `cli-zipapp` for 2–3 release cycles; binaries land in `cli-binary` from day one; deprecation announcement in release notes 1 cycle before removal.

**Expected outcome:** Documented namespace decision + cut-over policy. Sign-off from devrel / docs / customer-engineering on the URL change.

**Agent prompt:**
> Decide and document the Cloudsmith raw repo namespace for the new binary artefacts. Today `cloudsmith.pyz` is hosted at `https://dl.cloudsmith.io/public/cloudsmith/cli-zipapp/raw/names/cloudsmith-cli/versions/${VER}/cloudsmith.pyz`. New binaries are named `cloudsmith-${VER}-${OS}-${ARCH}[-musl][.exe]` and need a stable URL shape. Step 1: inspect the existing `cli-zipapp` namespace structure. Step 2: weigh new `cli-binary` namespace (recommended — cleaner separation, different lifecycle) vs extending `cli-zipapp`. Step 3: write a one-page proposal covering URL shape, deprecation cadence (keep `.pyz` for 2–3 release cycles, announce in release notes one cycle ahead), and consumer impact (`cloudsmith-cli-action`, Docker image, Homebrew formula, winget manifest, install.sh, customer scripts that hardcode the URL). Step 4: get sign-off from developer relations + docs + customer engineering. Not a code task — a decision brief.

---

## 18. Self-update story

**Question:** Is Homebrew + winget + `install.sh` enough, or do we ship a `cloudsmith self-update` subcommand?

**Why it matters:** `pip install -U` no longer applies. Customers expect updates. Atomic replace of a running `.exe` on Windows is non-trivial (file is locked).

**Plan:**
1. Estimate macOS + Windows + Linux user share via existing telemetry (download counts on `cli-zipapp`).
2. Estimate Homebrew + winget coverage as a fraction of expected macOS + Windows users — heuristic ~80%.
3. Decide:
   - Path A: ship via Homebrew + winget + `install.sh`; no built-in self-update. Linux users update via `install.sh` re-run.
   - Path B: implement `cloudsmith self-update` — downloads latest matching binary, SHA-verifies, atomic-replaces. Tricky on Windows: rename-then-replace-on-restart pattern (binary writes a `.new` next to itself, schedules a rename at next launch).
4. If Path B: scope the work (~1–2 sprints for a robust cross-platform updater with rollback).

**Expected outcome:** A documented update strategy + scoped engineering work if Path B is chosen.

**Agent prompt:**
> Decide and scope the Cloudsmith CLI self-update story for the binary distribution path. Background: today `pip install -U cloudsmith-cli` updates the CLI. Binary users have no equivalent. Two paths: (A) ship via Homebrew (macOS) + winget / Chocolatey (Windows) + `install.sh` (Linux); no built-in updater. (B) implement `cloudsmith self-update` — downloads latest matching binary, SHA-verifies, atomic-replaces (tricky on Windows: the running `.exe` is locked, so write `cloudsmith.new` next to it and schedule a rename via a small shim at next launch). Tasks: (1) Pull download stats on `cli-zipapp` raw repo to estimate macOS / Windows / Linux user share. (2) Estimate Homebrew + winget coverage for macOS + Windows users — industry heuristic is ~80%. (3) Recommend Path A or B with stated trade-off. Recommendation: A in the first release cycle, revisit B if customer feedback demands it. (4) If B: scope the work — atomic replace on POSIX (rename + chmod), atomic replace on Windows (rename + shim), SHA256 verification, rollback on bad signature, version-bound updates (don't auto-jump major versions). Estimate: 1–2 sprints for a robust cross-platform updater. Output: a one-page recommendation brief.

---

# Suggested execution order

1. **Unblock PEX scie immediately:** questions #1, #2, #3, #4, #8, #12 — one PEX-scie CI PoC workflow answers all six in a single matrix run. Estimated: 1 day of CI iteration once a `poc/pex-scie` branch lands.
2. **Promote PyInstaller path:** questions #5, #6, #7, #13 — extend the existing `binary-poc.yml` matrix. Estimated: 2 days.
3. **Edge-case validation:** #10, #11, #14 — niche but cheap once signing is in place.
4. **Procurement (parallel work):** #15, #16, #17 — kick off immediately, blocking on no engineering work.
5. **Strategy decision:** #18 — after #15–17 land + first beta release telemetry exists.
6. **Release polish:** #9 — after #15 lands and a beta is in customer hands.

Total estimated engineering effort (excluding procurement waits): ~1.5 sprints.
