#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET='provisional-ubuntu-24.04.5-x86_64-cp312'
LOCK_DIR="$ROOT/requirements/locks/$TARGET"
EVIDENCE_DIR="${AROMAN_EVIDENCE_DIR:?Set to a new evidence directory outside both repositories}"
WHEELHOUSE_ROOT="${AROMAN_P5_WHEELHOUSE_ROOT:?Set to retained P5/R1 wheelhouse root}"
PIP_COMPILE_TOOL="${AROMAN_PIP_COMPILE:?Set to retained candidate pip-compile executable}"
PYTHON="${AROMAN_PYTHON:?Set to the Python executable backing the retained candidate tools}"
cd "$ROOT"
EVIDENCE_DIR="$(python3 "$ROOT/scripts/provisional_safety.py" --evidence "$EVIDENCE_DIR" --wheelhouse "$WHEELHOUSE_ROOT")"
mkdir -p "$LOCK_DIR" "$EVIDENCE_DIR/generation"
env | awk -F= '/^PIP_/ {print $1 "=<redacted>"}' | sort > "$EVIDENCE_DIR/generation/inherited-pip-settings.txt"
while IFS= read -r name; do unset "$name"; done < <(export -p | sed -n 's/^declare -x \(PIP_[A-Za-z0-9_]*\)=.*/\1/p')
export PIP_CONFIG_FILE=/dev/null PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
"$PYTHON" "$ROOT/scripts/verify_provisional_wheels.py" \
  --manifest "$WHEELHOUSE_ROOT/wheel-hashes.csv" --wheelhouse-root "$WHEELHOUSE_ROOT" \
  --locks "$LOCK_DIR" --output "$EVIDENCE_DIR/generation/pre-generation-wheel-check.json" \
  >"$EVIDENCE_DIR/generation/pre-generation-wheel-check.log" 2>&1
"$PYTHON" -c 'import sys; assert sys.version_info[:3] == (3,12,3), sys.version'
"$PYTHON" -m pip --version | tee "$EVIDENCE_DIR/generation/pip-version.txt"
grep -F 'pip 26.3 ' "$EVIDENCE_DIR/generation/pip-version.txt" >/dev/null
"$PIP_COMPILE_TOOL" --version | tee "$EVIDENCE_DIR/generation/pip-tools-version.txt"
grep -F 'pip-compile, version 7.6.2' "$EVIDENCE_DIR/generation/pip-tools-version.txt" >/dev/null

for scope in runtime dev build bootstrap; do
  input="requirements/lock-inputs/$scope.in"
  wheelhouse="$WHEELHOUSE_ROOT/wheelhouse-$scope"
  output="requirements/locks/$TARGET/$scope.txt"
  raw="$EVIDENCE_DIR/generation/$scope.raw.txt"
  log="$EVIDENCE_DIR/generation/$scope.log"
  cmd=("$PIP_COMPILE_TOOL" --no-index --find-links "$wheelhouse" --no-emit-find-links --no-emit-index-url --generate-hashes --allow-unsafe --resolver=backtracking --output-file "$raw" "$input")
  {
    printf 'scope=%s\ncommand=' "$scope"
    printf '%q ' "${cmd[@]}"
    printf '\n'
  } | tee -a "$EVIDENCE_DIR/generation/commands.log"
  set +e
  PIP_ONLY_BINARY=:all: "${cmd[@]}" >"$log" 2>&1
  rc=$?
  set -e
  printf '%s\n' "$rc" > "$EVIDENCE_DIR/generation/$scope.exit"
  if (( rc != 0 )); then cat "$log" >&2; exit "$rc"; fi
  "$PYTHON" - "$raw" "$output" <<'PY'
from pathlib import Path
import sys
raw, output = map(Path, sys.argv[1:])
lines = raw.read_text().splitlines()
marker = next(i for i, line in enumerate(lines) if line.strip() == '--only-binary :all:')
body = '\n'.join(lines[marker:]).rstrip() + '\n'
header = ('# PROVISIONAL — NOT APPROVED\n'
          '# Candidate lock generated from retained P5/R1 wheels only.\n'
          '# Target: Ubuntu 24.04.5 x86_64, CPython 3.12.3.\n\n')
output.write_text(header + body)
PY
done
