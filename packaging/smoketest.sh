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
BIN="$(cd "$(dirname "$BIN")" && pwd)/$(basename "$BIN")"

fail() { echo "SMOKETEST FAIL: $1" >&2; exit 1; }

# Flag a missing native wheel / uncollected import. Not a generic traceback
# check: frozen stdio servers emit a benign "closed file" message at teardown.
no_dep_error() {
  if printf '%s' "$1" | grep -Eq 'ModuleNotFoundError|ImportError|No module named|cannot import name|DLL load failed|failed to map segment|GLIBC_'; then
    printf '%s\n' "$1" >&2
    fail "import/dep error during: $2"
  fi
}

# Print only the exception/error lines of a failed command (enough to diagnose
# e.g. a TLS or import failure) rather than the whole output, which can carry
# response bodies. The API key is masked in case anything echoed it.
error_summary() {
  printf '%s\n' "$1" \
    | grep -E '(Error|Exception|error)([:( ]|$)' \
    | tail -n 5 \
    | awk '{
        k = ENVIRON["CLOUDSMITH_API_KEY"]
        if (k != "") {
          while ((i = index($0, k)) > 0) {
            $0 = substr($0, 1, i - 1) "***" substr($0, i + length(k))
          }
        }
        print "  | " $0
      }' >&2
}

# Show why an online command failed: its error lines, or all of it with
# SMOKETEST_DEBUG=1.
failed_output() {
  if [ "${SMOKETEST_DEBUG:-0}" = "1" ]; then
    printf '%s\n' "$1" >&2
  else
    error_summary "$1"
  fi
}

# A 429 reaching the smoketest means the CLI's own 429 retries (which honour
# Retry-After) ran out. online_call waits and reruns the command until this
# many seconds have passed since the first 429 of the run, then fails: a run
# that is throttled throughout has validated nothing, so it must not pass.
RATE_LIMIT_BUDGET="${SMOKETEST_RATE_LIMIT_BUDGET:-180}"
RATE_LIMIT_BACKOFF=20
RATE_LIMIT_MAX_WAIT=60
RATE_LIMIT_DEADLINE=""

# The CLI's final error once its 429 retries are spent: urllib3's RetryError on
# the requests path, the HTTP reason phrase on the httpx (mcp) path. The
# "Request was throttled (429): Retrying" notice alone does not count, as the
# retried request can still end in a different error.
is_rate_limited() {
  printf '%s' "$1" | grep -Eq 'too many 429 error responses|Too Many Requests'
}

# Seconds to wait before a rerun: the last Retry-After the CLI reported, but at
# least RATE_LIMIT_BACKOFF (the CLI has already waited out that Retry-After)
# and at most RATE_LIMIT_MAX_WAIT.
rate_limit_wait() {
  _hint=$(printf '%s\n' "$1" \
    | sed -n 's/.*Retrying after [^0-9]*\([0-9][0-9]*\).*/\1/p' | tail -n 1)
  _wait=$RATE_LIMIT_BACKOFF
  if [ -n "$_hint" ] && [ "$_hint" -gt "$_wait" ]; then
    _wait=$_hint
  fi
  [ "$_wait" -le "$RATE_LIMIT_MAX_WAIT" ] || _wait=$RATE_LIMIT_MAX_WAIT
  echo "$_wait"
}

# Run a read-only online command; reruns it on a 429 (see RATE_LIMIT_BUDGET).
# Asserts success without printing the raw response (PII / repo names). The
# dep-error detector still sees the full output; SMOKETEST_DEBUG=1 prints it.
online_call() {
  _label="$1"; shift
  _attempt=1
  while :; do
    _rc=0
    _out=$("$BIN" "$@" 2>&1) || _rc=$?
    # An import/dep error is never retried, whatever else the output says.
    no_dep_error "$_out" "$_label"
    [ "$_rc" -ne 0 ] || break
    if ! is_rate_limited "$_out"; then
      failed_output "$_out"
      fail "online ${_label} failed (set SMOKETEST_DEBUG=1 for full output)"
    fi
    _now=$(date +%s)
    [ -n "$RATE_LIMIT_DEADLINE" ] || RATE_LIMIT_DEADLINE=$((_now + RATE_LIMIT_BUDGET))
    _left=$((RATE_LIMIT_DEADLINE - _now))
    if [ "$_left" -le 0 ]; then
      failed_output "$_out"
      fail "online ${_label} rate-limited (429), could not validate: still throttled after the ${RATE_LIMIT_BUDGET}s retry budget"
    fi
    _wait=$(rate_limit_wait "$_out")
    [ "$_wait" -le "$_left" ] || _wait=$_left
    echo "WARN: rate-limited (429) on ${_label} (attempt ${_attempt}); retrying in ${_wait}s, ${_left}s of retry budget left" >&2
    sleep "$_wait"
    _attempt=$((_attempt + 1))
  done
  if [ "${SMOKETEST_DEBUG:-0}" = "1" ]; then
    printf '%s\n' "$_out" | head -15
  elif [ "$_attempt" -gt 1 ]; then
    echo "${_label}: OK (after ${_attempt} attempts)"
  else
    echo "${_label}: OK"
  fi
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
  echo "== self-import sweep (every bundled cloudsmith_cli module loads) =="
  # Runtime proof the freeze is complete: import every bundled module. Catches
  # an uncollected module deterministically, replacing the static warn-file
  # gate. Functional data/metadata/dynamic paths are covered by the steps below.
  SWEEP=$( (
    unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null
    CLOUDSMITH_SELFTEST=1 PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      "$BIN" 2>&1
  ) || true )
  no_dep_error "$SWEEP" "self-import sweep"
  printf '%s\n' "$SWEEP" | tail -1
  printf '%s\n' "$SWEEP" | grep -q "SELFTEST: OK" \
    || fail "self-import sweep reported missing modules: $SWEEP"

  echo "== --version =="
  VERSION_OUT=$("$BIN" --version) || fail "--version exited nonzero"
  printf '%s\n' "$VERSION_OUT"
  if [ -n "${EXPECTED_VERSION:-}" ]; then
    printf '%s\n' "$VERSION_OUT" | grep -Fq "CLI Package Version: ${EXPECTED_VERSION}" \
      || fail "--version did not report ${EXPECTED_VERSION}"
  fi

  echo "== --help =="
  "$BIN" --help >/dev/null || fail "--help exited nonzero"

  echo "== mcp --help =="
  "$BIN" mcp --help >/dev/null || fail "mcp --help failed"

  echo "== per-command --help sweep (forces every command module to import) =="
  # Parse top-level command names from --help (first alias before any '|') and
  # run --help on each. Catches a command whose module / option construction
  # pulls an import PyInstaller did not collect.
  # Stop at the blank line ending the Commands block so a wrapped epilog line
  # (e.g. a docs URL) can never be parsed as a bogus command name.
  CMDS=$("$BIN" --help 2>/dev/null | awk '/^Commands:/{f=1; next} f && /^[[:space:]]*$/{f=0} f && /^[[:space:]]+[a-z]/{print $1}' | cut -d'|' -f1)
  [ -n "$CMDS" ] || fail "could not parse command list from --help"
  for c in $CMDS; do
    "$BIN" "$c" --help >/dev/null 2>&1 || fail "${c} --help failed"
  done
  echo "swept $(printf '%s\n' "$CMDS" | wc -l | tr -d ' ') commands"

  echo "== whoami (keyring/auth path) =="
  # The API host is unreachable on purpose, so don't retry.
  RC=0
  OUT=$( (
    unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null
    CLOUDSMITH_API_HOST=http://127.0.0.1:9 \
    CLOUDSMITH_OIDC_DISCOVERY_DISABLED=true \
    PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      "$BIN" whoami --error-retry-max 0 2>&1
  ) ) || RC=$?
  no_dep_error "$OUT" "whoami"
  [ "$RC" -ne 0 ] || fail "whoami against unreachable API must exit nonzero"
  printf '%s\n' "$OUT" | head -5

  echo "== AWS OIDC dependency load =="
  OUT=$( (
    unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null
    AWS_ACCESS_KEY_ID=smoketest \
    AWS_SECRET_ACCESS_KEY=smoketest \
    AWS_EC2_METADATA_DISABLED=true \
    AWS_ENDPOINT_URL_STS=http://127.0.0.1:9 \
    AWS_MAX_ATTEMPTS=1 \
    CLOUDSMITH_API_HOST=http://127.0.0.1:9 \
    PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      "$BIN" whoami --error-retry-max 0 2>&1
  ) || true )
  no_dep_error "$OUT" "AWS OIDC dependency load"

  echo "== credential-helper docker (offline) =="
  OUT=$( (
    unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null
    printf 'docker.cloudsmith.io' | CLOUDSMITH_OIDC_DISCOVERY_DISABLED=true \
      PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      "$BIN" credential-helper docker 2>&1
  ) || true )
  no_dep_error "$OUT" "credential-helper docker"
  printf '%s\n' "$OUT" | grep -q "Unable to retrieve credentials" \
    || fail "credential-helper did not emit expected message; got: $OUT"

  echo "== credential-helper install docker (frozen launcher self-references binary) =="
  # A standalone binary is not guaranteed to be on PATH as `cloudsmith`, so the
  # frozen install must point the docker-credential launcher at the absolute
  # executable. Prove it by running the launcher with an empty PATH: a bare
  # `cloudsmith` lookup would fail, so reaching the CLI proves the self-reference.
  INSTALL_TMP="$(mktemp -d 2>/dev/null || echo /tmp/cloudsmith-credhelper-install)"
  mkdir -p "$INSTALL_TMP/bin" "$INSTALL_TMP/docker"
  OUT=$( (
    unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null
    DOCKER_CONFIG="$INSTALL_TMP/docker" \
    CLOUDSMITH_OIDC_DISCOVERY_DISABLED=true \
    PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      "$BIN" credential-helper install docker \
        --bin-dir "$INSTALL_TMP/bin" --no-discover 2>&1
  ) || true )
  no_dep_error "$OUT" "credential-helper install docker"
  case "$BIN" in
    *.exe)
      LAUNCHER="$INSTALL_TMP/bin/docker-credential-cloudsmith.cmd"
      [ -f "$LAUNCHER" ] || fail "install did not write a launcher; got: $OUT"
      grep -Eq '"[^"]*cloudsmith\.exe"' "$LAUNCHER" \
        || fail "frozen launcher must forward to the executable; got: $(cat "$LAUNCHER")"
      ;;
    *)
      LAUNCHER="$INSTALL_TMP/bin/docker-credential-cloudsmith"
      [ -f "$LAUNCHER" ] || fail "install did not write a launcher; got: $OUT"
      LOUT=$( (
        unset CLOUDSMITH_API_KEY CLOUDSMITH_API_TOKEN 2>/dev/null
        printf 'docker.cloudsmith.io' | PATH= \
          CLOUDSMITH_OIDC_DISCOVERY_DISABLED=true \
          PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
          "$LAUNCHER" 2>&1
      ) || true )
      no_dep_error "$LOUT" "frozen docker-credential launcher exec"
      printf '%s' "$LOUT" | grep -q "Unable to retrieve credentials" \
        || fail "frozen launcher did not reach the CLI (bare cloudsmith off PATH?); got: $LOUT"
      ;;
  esac

  echo "== frozen mcp configure command =="
  CONFIG_TMP="$(mktemp -d 2>/dev/null || echo /tmp/cloudsmith-mcp-config)"
  mkdir -p "$CONFIG_TMP"
  (
    cd "$CONFIG_TMP"
    HOME="$CONFIG_TMP" "$BIN" mcp configure --client cursor --local >/dev/null
  ) || fail "mcp configure failed"
  CONFIG="$CONFIG_TMP/.cursor/mcp.json"
  [ -f "$CONFIG" ] || fail "mcp configure did not create cursor config"
  case "$BIN" in
    *.exe)
      grep -Eq '"command":[[:space:]]*"[^"]*cloudsmith\.exe"' "$CONFIG" \
        || fail "frozen mcp config did not use the executable directly"
      ;;
    *)
      grep -Fq "\"command\": \"$BIN\"" "$CONFIG" \
        || fail "frozen mcp config did not use the executable directly"
      ;;
  esac
  if grep -Fq '"-m"' "$CONFIG"; then
    fail "frozen mcp config contains an invalid Python -m invocation"
  fi

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

  # Fetches the OpenAPI spec over httpx2 and builds pydantic tool models:
  # exercises pydantic-core (deeper than the initialize handshake) plus the
  # native jsonschema/rpds-py validation path and httpx2 TLS (certifi bundle).
  echo "== mcp list_tools (pydantic-core + jsonschema/rpds-py + httpx2 TLS) =="
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
