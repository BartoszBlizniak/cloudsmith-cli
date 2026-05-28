# PEX-scie + pex.rc Binary PoC — Results

**Branch:** `binary-poc` on `BartoszBlizniak/cloudsmith-cli`
**Workflow:** `.github/workflows/binary-poc-pex.yml`
**Final run:** [#26587200483](https://github.com/BartoszBlizniak/cloudsmith-cli/actions/runs/26587200483) (2026-05-28)
**Versions:** PEX **2.95.2**, python-build-standalone **20260510** (CPython 3.10.20), scie-jump **1.11.2**, pex.rc **0.13.2**, Python pin **3.10**.

Trigger for this PoC: jsirois's 2026-05-26 reply on [pex-tool/pex#2658](https://github.com/pex-tool/pex/issues/2658#issuecomment-4548571344) stating that `pex --rc` (via `pex.rc`) is the path forward for Windows. This PoC tests that claim against the same criteria the PyInstaller PoC was held to.

---

## 1. Headline result

**PEX is a strong candidate for POSIX, but it does not yet have a way to ship a no-Python binary on Windows.**

| Target                       | PEX scie build | No-Python run | Smoke + MCP + e2e | Verdict                          |
|------------------------------|:--------------:|:-------------:|:-----------------:|----------------------------------|
| linux-amd64-glibc            | OK             | OK            | OK                | Production-ready                 |
| linux-arm64-glibc            | OK             | OK            | OK                | Production-ready                 |
| linux-amd64-musl (Alpine)    | OK             | n/a           | FAIL              | Blocker — pydantic\_core runtime |
| linux-arm64-musl (Alpine)    | OK             | n/a           | FAIL              | Blocker — pydantic\_core runtime |
| macos-arm64                  | OK             | OK            | OK                | Production-ready                 |
| macos-amd64                  | OK             | OK            | OK                | Production-ready                 |
| windows-amd64 (`--scie`)     | **REJECTED**   | n/a           | n/a               | Not supported by PEX 2.95.2      |
| windows-amd64 (`--rc`)       | OK (build)     | **NO**        | n/a (zipapp)      | Requires Python on Windows host  |
| windows-arm64                | not attempted  | —             | —                 | Same Pex flag-set gap; deferred  |

**Production-readiness for Cloudsmith CLI's "no Python required" goal: 4 / 8 targets.**

Compare to the PyInstaller PoC (`binary-poc.yml`) which had **8 / 8** targets green on its reference run.

---

## 2. What jsirois's `pex.rc` answer actually unlocks

The 2026-05-26 comment was responding to *"just being able to **run** a PEX file on Windows"*. The PoC confirms:

- `pex --rc` is a flag on PEX 2.95.2 — it builds.
- It downloads the `pex.rc` runtime bootstrap and injects it into the PEX.
- The resulting **artifact is a zipapp starting with `#!/usr/bin/env python3`** (run output captured the first 4 bytes as `0x23 0x21 0x2F 0x75`, i.e. `#!/u`).
- On a fresh `windows-2025-vs2026` runner with `PATH` stripped of Python, the artifact fails to launch (`The specified executable is not a valid application for this OS platform`).
- So `pex.rc` answers "can a PEX run on Windows" with **yes — if Python is on the host**. It does not embed a Python runtime.

This is **different** from the Cloudsmith requirement, which is to distribute the CLI to users who do **not** have Python installed. `pex.rc` alone does not solve that.

To get a no-Python binary out of PEX you would still need `--scie eager --scie-platform windows-*`. PEX 2.95.2's CLI parser explicitly rejects that:

```
pex: error: argument --scie-platform: invalid choice: 'windows-x86_64'
(choose from 'linux-aarch64', 'musl-linux-aarch64', 'linux-armv7l',
 'linux-powerpc64', 'linux-riscv64', 'linux-s390x', 'linux-x86_64',
 'musl-linux-x86_64', 'macos-aarch64', 'macos-x86_64')
```

The Pex source enum has `WINDOWS_X86_64` / `WINDOWS_AARCH64` but the CLI does not yet expose them. Until that lands in a Pex release, **PEX is POSIX-only** for the no-Python use case.

---

## 3. Per-target build results

All POSIX builds use a native runner with `pex . cryptography --scie eager --scie-platform <triple> --complete-platform <repo file> --venv`. Cryptography is appended as an additional req because it is not in `requirements.txt`. The repo's existing `.github/.platforms/*-py310.json` complete-platform files are reused to keep wheel tag resolution explicit (especially important on musl).

| Target              | Runner               | Artifact size | Cold `--version`† | Notes                                              |
|---------------------|----------------------|---------------|-------------------|----------------------------------------------------|
| linux-amd64-glibc   | `ubuntu-latest`      | **58 MB**     | ~5.3 s            | All checks green incl. keyring + e2e               |
| linux-arm64-glibc   | `ubuntu-24.04-arm`   | **58 MB**     | ~4.7 s            | All checks green incl. keyring + e2e               |
| macos-arm64         | `macos-latest`       | **43 MB**     | ~3.7 s            | All checks green incl. keyring                     |
| macos-amd64         | `macos-15-intel`     | **43 MB**     | ~13.9 s           | All checks green; slow first-run extraction        |
| linux-amd64-musl    | `python:3.10-alpine` | n/a           | n/a               | Build green, runtime FAIL (see §4)                 |
| linux-arm64-musl    | Alpine in docker     | n/a           | n/a               | Build green, runtime FAIL (see §4)                 |
| windows-amd64-scie  | n/a                  | n/a           | n/a               | Pex rejects `--scie-platform windows-x86_64`       |
| windows-amd64-rc    | `ubuntu-latest` (X)  | **~70 MB**    | n/a               | Zipapp w/ unix shebang; needs Python on Windows    |

† Cold = first invocation after wiping `~/.cache/nce` (the PBS extraction dir).

### Sample warm-start timing (linux-amd64-glibc)

After first run, repeated `--version` invocations land sub-second on Linux x86_64 (the scie cache is hot, PEX venv already materialized). macOS x86_64 was the slowest cold start at ~14 s; this is the PBS extraction cost on a slower runner CPU.

---

## 4. Open blockers

### 4.1 `pydantic_core._pydantic_core` missing on musl

Both Alpine targets passed the PEX build phase but fail at runtime:

```
ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'
```

What we tried:

1. `--scie eager --scie-platform musl-linux-x86_64` alone → resolver picked sdist, runtime missing `.so`.
2. Added `--no-build` to force wheel-only → cryptography wheel not found (PEX-derived musl tags too narrow).
3. Added `--complete-platform .github/.platforms/linux-x86_64-musl-py310.json` (which encodes `musllinux_1_0/1_1/1_2` tags) → build succeeds again, but the runtime venv still does not contain `_pydantic_core.*.so`.

Hypothesis: PEX scie + PBS-musl is not extracting the native `.so` from the pydantic-core wheel into the materialized venv on first run. This is a deeper interaction issue between the scie launcher, the PBS musl distribution, and PEX's venv extraction path. Needs an upstream issue against `pex-tool/pex` (or `astral-sh/python-build-standalone`) with a minimal reproducer.

Note: PBS's musl `dlopen` blocker (PBS [#86](https://github.com/astral-sh/python-build-standalone/issues/86)) is closed since 2025-03-11, so this is **not** the historic compatibility problem — it is a more recent and narrower bug in the PEX-scie + musl + pydantic-core combination.

### 4.2 Windows scie targets not exposed by Pex 2.95.2

Source has the enum. CLI rejects the value. Until a Pex release flips this, **no PEX path gives a no-Python Windows binary**. Tracking item, not a Cloudsmith-side fix.

### 4.3 macOS GitHub API rate-limit on `science lift`

The scie launcher build calls `https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest`. Unauthenticated CI runners are shared and routinely hit 403. Fix: set `SCIENCE_AUTH_API_GITHUB_COM_BEARER=${{ secrets.GITHUB_TOKEN }}` on the build step. Added to the PoC workflow after the first run; subsequent runs were stable.

### 4.4 windows-arm64 deferred

PEX 2.95.2 has no `--scie-platform windows-aarch64` choice (same flag-set gap as windows-x86_64). The repo also lacks a `.github/.platforms/windows-aarch64-py310.json` complete-platform file — generating one needs an interactive `pex3 interpreter inspect --markers --tags` on a `windows-11-arm` host. Both gaps need to close before windows-arm64 can be revisited.

---

## 5. What a production-ready PEX release pipeline would look like (for the green targets)

Concrete shape, derived from the PoC, assuming we ship POSIX via PEX scie and Windows via PyInstaller in the interim:

```
.github/workflows/release.yml
├── matrix:
│   ├── linux-amd64-glibc       ubuntu-latest        --scie eager --scie-platform linux-x86_64
│   ├── linux-arm64-glibc       ubuntu-24.04-arm     --scie eager --scie-platform linux-aarch64
│   ├── macos-arm64             macos-latest         --scie eager --scie-platform macos-aarch64
│   └── macos-amd64             macos-15-intel       --scie eager --scie-platform macos-x86_64
├── env:
│   SCIENCE_AUTH_API_GITHUB_COM_BEARER: ${{ secrets.GITHUB_TOKEN }}
├── steps:
│   1. checkout
│   2. setup-python 3.10
│   3. pip install -r requirements.txt && pip install -e . && pip install pex==2.95.2
│   4. pex . cryptography
│         --output-file out/cloudsmith-${TARGET}
│         --console-script cloudsmith
│         --scie eager
│         --scie-platform ${SCIE_PLATFORM}
│         --complete-platform .github/.platforms/${PLATFORM_FILE}
│         --venv
│   5. smoke: --version, --help, mcp --help, check service, check cryptography-selftest
│   6. no-Python validation (docker run --rm <slim image> / env -i PATH=… on macOS)
│   7. MCP stdio init handshake
│   8. keyring round-trip
│   9. push/pull e2e
│  10. SBOM (cyclonedx-py environment > sbom.cdx.json)
│  11. SLSA attestation (actions/attest-build-provenance)
│  12. Code signing
│         macOS:  codesign --options=runtime --timestamp + xcrun notarytool submit
│         Windows: signtool /sha1 <thumbprint> /tr <timestamp> /td sha256 /fd sha256
│  13. Upload to Cloudsmith raw repo + GitHub release assets
└── outputs:
    cloudsmith-${VERSION}-linux-x86_64
    cloudsmith-${VERSION}-linux-aarch64
    cloudsmith-${VERSION}-macos-aarch64
    cloudsmith-${VERSION}-macos-x86_64
    SHA256SUMS, sbom.cdx.json, *.into.jsonl
```

For Windows + musl in this interim, use the PyInstaller pipeline already proven by `binary-poc.yml` (8 / 8 green there) and add a resolver layer in `cloudsmith-cli-action` to pick the right artifact per OS / arch / libc.

---

## 6. Comparison with the PyInstaller PoC

| Criterion                                | PEX scie + pex.rc                     | PyInstaller 6.20.0                            |
|------------------------------------------|---------------------------------------|-----------------------------------------------|
| Targets covered today (no-Python)        | **4 / 8** (linux glibc x2, macOS x2)  | **8 / 8** (incl. musl + Windows x2)           |
| Lines of release config delta            | Flag change + `--complete-platform`   | New `.spec` + per-target hidden imports       |
| Per-build wall time                      | seconds                               | seconds — ~2 min on Windows                   |
| Per-launch self-extraction               | First run only (PBS to `~/.cache/nce`) | Every launch (onefile) or first only (onedir) |
| Native cryptography handling             | Wheels untouched (good)               | Bundled, audit hidden imports                 |
| MCP / `anyio`                            | No source transform — works           | Works after `collect_submodules('mcp')`       |
| Reproducibility                          | Closer to yes (PBS + lockfile)        | No — random temp-archive offsets              |
| License                                  | Apache-2.0 (PEX) + PSF (PBS)          | GPL-2.0 with bootloader exception             |
| Build artifact size                      | 43 MB (macOS) / 58 MB (Linux glibc)   | 19 MB (macOS) / 38 MB (Linux glibc)           |

PEX scie produces a **larger** binary than PyInstaller (it ships the full PBS CPython + standard library) but it does not self-extract every run, so warm-start latency on POSIX is better.

---

## 7. Recommendation

1. **Ship PyInstaller as the primary path now** — it is the only PoC that covers all 8 Cloudsmith targets today. Production-readiness for that path is already established in [`docs/pyinstaller-binary-poc-results.md`](./pyinstaller-binary-poc-results.md).
2. **Hold PEX scie as the strategic POSIX path** — once the musl + pydantic-core runtime gap is resolved upstream, PEX scie is materially smaller config delta from the current release pipeline, and reproducibility / SBOM / source transparency are all better than PyInstaller. Worth a follow-up spike when Pex releases ship `--scie-platform windows-*`.
3. **File two upstream issues** with minimal reproducers:
   - `pex-tool/pex`: `--scie eager --scie-platform musl-linux-x86_64` + `pydantic-core` runtime ModuleNotFoundError on `_pydantic_core`.
   - `pex-tool/pex`: expose `WINDOWS_X86_64` / `WINDOWS_AARCH64` in the CLI `--scie-platform` choice list (the source enum already supports them; the parser does not).
4. **Re-evaluate when Pex ships Windows scie support** — at that point a hybrid (PEX scie for POSIX, PEX scie for Windows, PyInstaller dropped) becomes the simplest single-tool release pipeline.

---

## 8. Reference run log

- Workflow file: [`.github/workflows/binary-poc-pex.yml`](../.github/workflows/binary-poc-pex.yml)
- Final run: <https://github.com/BartoszBlizniak/cloudsmith-cli/actions/runs/26587200483>
- Earlier iterations and what each one taught us:
  - [26585254245](https://github.com/BartoszBlizniak/cloudsmith-cli/actions/runs/26585254245) — `setup-test-repo` 401 blocked all downstream; needs-decoupling fix.
  - [26585355987](https://github.com/BartoszBlizniak/cloudsmith-cli/actions/runs/26585355987) — `--scie-platform windows-x86_64` rejected; `pex --rc` builds; musl `--scie-platform` value naming wrong (`musl-linux-*` not `linux-*-musl`); `cryptography` not bundled.
  - [26585616776](https://github.com/BartoszBlizniak/cloudsmith-cli/actions/runs/26585616776) — Cross-built Windows artifact is a unix-shebang zipapp; `_pydantic_core` missing on musl; macOS `science` hit GH 403.
  - [26585986878](https://github.com/BartoszBlizniak/cloudsmith-cli/actions/runs/26585986878) — `SCIENCE_AUTH_API_GITHUB_COM_BEARER` lifted the 403; musl still broken.
  - [26586860335](https://github.com/BartoszBlizniak/cloudsmith-cli/actions/runs/26586860335) — `--no-build` exposed a separate musl wheel-resolution gap (cryptography "no matching distribution"); reverted.
  - [26587200483](https://github.com/BartoszBlizniak/cloudsmith-cli/actions/runs/26587200483) — Added `--complete-platform` per target; 7 / 9 jobs green; musl still ModuleNotFoundError on `_pydantic_core` at runtime. Stopped iterating.
