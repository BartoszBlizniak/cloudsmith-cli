#!/usr/bin/env sh
# Smoketest the Cloudsmith single-file binary.
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

echo "== binary: $BIN (mode=$MODE) =="
ls -lh "$BIN" 2>/dev/null || true

run_offline() {
  echo "== --version =="
  "$BIN" --version || fail "--version exited nonzero"

  echo "== --help =="
  "$BIN" --help >/dev/null || fail "--help exited nonzero"

  echo "== mcp --help =="
  "$BIN" mcp --help >/dev/null || fail "mcp --help failed"

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

  echo "== whoami (online) =="
  OUT=$("$BIN" whoami 2>&1) || {
    if printf '%s' "$OUT" | grep -Eq '429|rate limit|Too Many Requests'; then
      echo "WARN: rate-limited (429) on whoami; shared org throttling, not a binary failure" >&2
      return 0
    fi
    printf '%s\n' "$OUT"; fail "online whoami failed"
  }
  no_dep_error "$OUT" "whoami online"
  printf '%s\n' "$OUT" | head -15

  if [ -n "${CLOUDSMITH_NAMESPACE:-}" ]; then
    echo "== list repos $CLOUDSMITH_NAMESPACE (read-only) =="
    OUT=$("$BIN" list repos "$CLOUDSMITH_NAMESPACE" 2>&1) || {
      if printf '%s' "$OUT" | grep -Eq '429|rate limit|Too Many Requests'; then
        echo "WARN: rate-limited (429); not a binary failure" >&2
        return 0
      fi
      printf '%s\n' "$OUT"; fail "online list repos failed"
    }
    no_dep_error "$OUT" "list repos online"
    printf '%s\n' "$OUT" | head -20
  fi
}

case "$MODE" in
  offline) run_offline ;;
  online)  run_online ;;
  *)       fail "unknown mode: $MODE" ;;
esac

echo "ALL SMOKETESTS PASSED ($MODE)"
