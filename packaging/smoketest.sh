#!/usr/bin/env sh
#
# Shared smoketest for the Cloudsmith single-binary spike.
#
# This script is IDENTICAL on binary-pex and binary-pyinstaller so the two
# packagers are compared against the same bar. It forces the native deps to
# load and the key code paths to execute -- `--help` alone proves nothing.
#
# Usage:   smoketest.sh <path-to-cloudsmith-binary> [offline|online]
#
# Modes:
#   offline  (default) no network. Runs in a clean, no-Python environment.
#   online   read-only Cloudsmith API checks. Needs CLOUDSMITH_API_KEY (and
#            optionally CLOUDSMITH_NAMESPACE). Must be run serially and never
#            for both branches at once -- it hits a shared org.
#
# Pass = exit 0 + expected output + NO dep/import errors.

set -eu

BIN="${1:?usage: smoketest.sh <binary> [offline|online]}"
MODE="${2:-offline}"

# A bare filename (no slash) would be resolved via PATH, not the cwd. Normalize
# so "smoketest.sh mybin" runs ./mybin like callers expect.
case "$BIN" in
  */*) : ;;
  *) BIN="./$BIN" ;;
esac

fail() { echo "SMOKETEST FAIL: $1" >&2; exit 1; }

# Assert a captured blob carries no Python import/dep failure -- the failure
# mode that matters for a frozen binary (a missing native wheel or an
# uncollected dynamic import surfaces exactly these strings). We intentionally
# do NOT flag every "Traceback": stdio servers (mcp/anyio) can emit a benign
# "I/O operation on closed file" while tearing down after stdin EOF, which is
# shutdown noise, not a packaging defect. Functional success is asserted
# separately (exit codes + expected output + the jsonrpc envelope).
no_dep_error() {
  if printf '%s' "$1" | grep -Eq 'ModuleNotFoundError|ImportError|No module named|cannot import name|DLL load failed|failed to map segment|GLIBC_'; then
    echo "----- offending output -----" >&2
    printf '%s\n' "$1" >&2
    fail "python import/dep error during: $2"
  fi
}

echo "== binary under test: $BIN (mode=$MODE) =="
ls -lh "$BIN" 2>/dev/null || true

run_offline() {
  echo "== offline: --version =="
  "$BIN" --version || fail "--version exited nonzero"

  echo "== offline: --help =="
  "$BIN" --help >/dev/null || fail "--help exited nonzero"

  echo "== offline: mcp --help (mcp command subtree loads) =="
  "$BIN" mcp --help >/dev/null || fail "mcp --help failed"

  echo "== offline: keyring/auth path via whoami (no creds; must not import-fail) =="
  # No credentials: command may exit nonzero, but it must load core.keyring
  # and the credential provider chain without an import/dep error.
  OUT=$( (unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null; "$BIN" whoami 2>&1) || true )
  no_dep_error "$OUT" "whoami offline"
  printf '%s\n' "$OUT" | head -5

  echo "== offline: credential-helper docker (baseline helper; initializes offline) =="
  # With no creds, get_credentials() returns None before any network call:
  # exit 1 + a specific message. Proves the helper is compiled in and
  # initializes offline.
  OUT=$( (unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null; printf 'docker.cloudsmith.io' | "$BIN" credential-helper docker 2>&1) || true )
  no_dep_error "$OUT" "credential-helper docker offline"
  printf '%s\n' "$OUT" | grep -q "Unable to retrieve credentials" \
    || fail "credential-helper offline did not emit expected message; got: $OUT"
  echo "credential-helper docker offline OK"

  echo "== offline: mcp stdio initialize handshake (forces pydantic-core load) =="
  # Warm any one-time extraction so the handshake is not racing a cold start.
  "$BIN" --version >/dev/null 2>&1 || true
  INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
  OUTF="$(mktemp 2>/dev/null || echo /tmp/mcp.out)"
  ERRF="$(mktemp 2>/dev/null || echo /tmp/mcp.err)"
  # Capture to files (not a live pipe): closing the pipe with `head` would
  # SIGPIPE the server mid-write and produce benign "closed file" shutdown
  # noise. stdin closes after the request (EOF), so the stdio server exits on
  # its own -- no `timeout` wrapper (absent on macOS, and a different command
  # entirely on Windows); the job-level timeout-minutes is the hang guard.
  printf '%s\n' "$INIT" | "$BIN" mcp start >"$OUTF" 2>"$ERRF" || true
  OUT=$(head -1 "$OUTF" 2>/dev/null || true)
  echo "mcp stdout: $OUT"
  echo "mcp stderr (head):"; head -20 "$ERRF" 2>/dev/null || true
  no_dep_error "$(cat "$ERRF" 2>/dev/null || true)" "mcp start"
  printf '%s' "$OUT" | grep -q '"jsonrpc":"2.0"' \
    || fail "mcp initialize handshake produced no jsonrpc envelope"
  echo "mcp stdio handshake OK (pydantic-core loaded)"
}

run_online() {
  [ -n "${CLOUDSMITH_API_KEY:-}" ] || fail "online mode but CLOUDSMITH_API_KEY is empty"

  echo "== online: whoami (read-only auth check) =="
  OUT=$("$BIN" whoami 2>&1) || { printf '%s\n' "$OUT"; fail "online whoami failed"; }
  no_dep_error "$OUT" "whoami online"
  printf '%s\n' "$OUT" | head -15

  if [ -n "${CLOUDSMITH_NAMESPACE:-}" ]; then
    echo "== online: list repos $CLOUDSMITH_NAMESPACE (read-only) =="
    OUT=$("$BIN" list repos "$CLOUDSMITH_NAMESPACE" 2>&1) || {
      # A 429 here is the shared org throttling us, not a binary failure.
      if printf '%s' "$OUT" | grep -Eq '429|rate limit|Too Many Requests'; then
        echo "WARN: rate-limited by shared org (429); not a binary failure" >&2
        printf '%s\n' "$OUT" | head -10
        return 0
      fi
      printf '%s\n' "$OUT"; fail "online list repos failed"
    }
    no_dep_error "$OUT" "list repos online"
    printf '%s\n' "$OUT" | head -20
  else
    echo "CLOUDSMITH_NAMESPACE unset; skipping read-only list"
  fi
}

case "$MODE" in
  offline) run_offline ;;
  online)  run_online ;;
  *)       fail "unknown mode: $MODE (expected offline|online)" ;;
esac

echo "ALL SMOKETESTS PASSED ($MODE)"
