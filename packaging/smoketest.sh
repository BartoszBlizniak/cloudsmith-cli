#!/usr/bin/env sh
# Smoketest the standalone Cloudsmith binary.
#   smoketest.sh <binary> [offline|online]
# offline: no network, runs in a clean no-Python environment.
# online:  read-only API checks; needs CLOUDSMITH_API_KEY (+ CLOUDSMITH_NAMESPACE).
# Pass = exit 0 + expected output + no import/dep errors.

set -eu

BIN="${1:?usage: smoketest.sh <binary> [offline|online]}"
MODE="${2:-offline}"

case "$BIN" in
  */*) : ;;
  *) BIN="./$BIN" ;;
esac

fail() { echo "SMOKETEST FAIL: $1" >&2; exit 1; }

# Flag a missing native wheel / uncollected import. Not a generic traceback
# check: frozen stdio servers emit a benign "closed file" message at teardown.
no_dep_error() {
  if printf '%s' "$1" | grep -Eq 'ModuleNotFoundError|ImportError|No module named|cannot import name|DLL load failed|failed to map segment|GLIBC_'; then
    printf '%s\n' "$1" >&2
    fail "import/dep error during: $2"
  fi
}

# Run a read-only online command; a 429 is the shared org throttling, not a
# binary failure, so warn and pass.
online_call() {
  _label="$1"; shift
  _out=$("$BIN" "$@" 2>&1) || {
    if printf '%s' "$_out" | grep -Eq '429|rate limit|Too Many Requests'; then
      echo "WARN: rate-limited (429) on ${_label}; shared org throttling, not a binary failure" >&2
      return 0
    fi
    printf '%s\n' "$_out"; fail "online ${_label} failed"
  }
  no_dep_error "$_out" "$_label"
  printf '%s\n' "$_out" | head -15
}

echo "== binary: $BIN (mode=$MODE) =="
ls -lh "$BIN" 2>/dev/null || true

# Negative test: prove the import/dep detector actually fires, so a real
# missing-wheel error can never slip past it silently.
if ( no_dep_error "ModuleNotFoundError: No module named 'sanitycheck'" "gate-selftest" ) 2>/dev/null; then
  fail "no_dep_error gate did not catch a planted import error (detector broken)"
fi
echo "== gate self-test OK (import/dep detector fires) =="

run_offline() {
  echo "== --version =="
  "$BIN" --version || fail "--version exited nonzero"

  echo "== --help =="
  "$BIN" --help >/dev/null || fail "--help exited nonzero"

  echo "== mcp --help =="
  "$BIN" mcp --help >/dev/null || fail "mcp --help failed"

  echo "== per-command --help sweep (forces every command module to import) =="
  # Parse top-level command names from --help (first alias before any '|') and
  # run --help on each. Catches a command whose module / option construction
  # pulls an import PyInstaller did not collect.
  CMDS=$("$BIN" --help 2>/dev/null | awk '/^Commands:/{f=1; next} f && /^[[:space:]]+[a-z]/{print $1}' | cut -d'|' -f1)
  [ -n "$CMDS" ] || fail "could not parse command list from --help"
  for c in $CMDS; do
    "$BIN" "$c" --help >/dev/null 2>&1 || fail "${c} --help failed"
  done
  echo "swept $(printf '%s\n' "$CMDS" | wc -l | tr -d ' ') commands"

  echo "== whoami (keyring/auth path) =="
  OUT=$( (unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null; "$BIN" whoami 2>&1) || true )
  no_dep_error "$OUT" "whoami"
  printf '%s\n' "$OUT" | head -5

  echo "== credential-helper docker (offline) =="
  OUT=$( (unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null; printf 'docker.cloudsmith.io' | "$BIN" credential-helper docker 2>&1) || true )
  no_dep_error "$OUT" "credential-helper docker"
  printf '%s\n' "$OUT" | grep -q "Unable to retrieve credentials" \
    || fail "credential-helper did not emit expected message; got: $OUT"

  echo "== mcp stdio initialize (loads pydantic-core) =="
  "$BIN" --version >/dev/null 2>&1 || true
  INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
  OUTF="$(mktemp 2>/dev/null || echo /tmp/mcp.out)"
  ERRF="$(mktemp 2>/dev/null || echo /tmp/mcp.err)"
  printf '%s\n' "$INIT" | "$BIN" mcp start >"$OUTF" 2>"$ERRF" || true
  OUT=$(head -1 "$OUTF" 2>/dev/null || true)
  no_dep_error "$(cat "$ERRF" 2>/dev/null || true)" "mcp start"
  printf '%s' "$OUT" | grep -q '"jsonrpc":"2.0"' \
    || fail "mcp initialize produced no jsonrpc envelope"
}

run_online() {
  [ -n "${CLOUDSMITH_API_KEY:-}" ] || fail "online mode but CLOUDSMITH_API_KEY is empty"

  # Auth + cloudsmith_api model deserialization.
  echo "== whoami (online auth) =="
  online_call "whoami" whoami

  # Read-only listing — broader cloudsmith_api coverage.
  if [ -n "${CLOUDSMITH_NAMESPACE:-}" ]; then
    echo "== list repos $CLOUDSMITH_NAMESPACE (read-only) =="
    online_call "list repos" list repos "$CLOUDSMITH_NAMESPACE"
  fi

  # Fetches the OpenAPI spec over httpx and builds pydantic tool models:
  # exercises pydantic-core (deeper than the initialize handshake) plus the
  # native jsonschema/rpds-py validation path and httpx TLS.
  echo "== mcp list_tools (pydantic-core + jsonschema/rpds-py + httpx TLS) =="
  online_call "mcp list_tools" mcp list_tools

  # requests/urllib3 + certifi CA bundle + the semver version-compare path.
  echo "== check service (requests/urllib3/certifi TLS + semver) =="
  online_call "check service" check service
}

case "$MODE" in
  offline) run_offline ;;
  online)  run_online ;;
  *)       fail "unknown mode: $MODE" ;;
esac

echo "ALL SMOKETESTS PASSED ($MODE)"
