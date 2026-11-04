#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET='provisional-ubuntu-24.04.5-x86_64-cp312'
LOCK_DIR="$ROOT/requirements/locks/$TARGET"
EVIDENCE_DIR="${AROMAN_EVIDENCE_DIR:?Set to a new evidence directory outside both repositories}"
WHEELHOUSE_ROOT="${AROMAN_P5_WHEELHOUSE_ROOT:?Set to retained P5/R1 wheelhouse root}"
PIP="${AROMAN_PIP:?Set to retained candidate pip 26.3 executable}"
PYTHON="${AROMAN_PYTHON:?Set to Python 3.12.3 executable}"
mkdir -p "$EVIDENCE_DIR"/{venvs,logs,inventories,wheels,source}
[[ "$EVIDENCE_DIR" != "$ROOT"/* && "$EVIDENCE_DIR" != *'/FrontEnd/'* ]] || { echo 'evidence must be outside both repositories' >&2; exit 2; }
"$PYTHON" --version | tee "$EVIDENCE_DIR/logs/python-version.txt"
"$PIP" --version | tee "$EVIDENCE_DIR/logs/pip-version.txt"
grep -F 'pip 26.3 ' "$EVIDENCE_DIR/logs/pip-version.txt" >/dev/null
python_cmd="$PYTHON"

for scope in runtime dev build bootstrap; do
  envdir="$EVIDENCE_DIR/venvs/$scope"
  "$python_cmd" -m venv --without-pip "$envdir" >"$EVIDENCE_DIR/logs/venv-$scope.log" 2>&1
  printf '%q ' "$PIP" --python "$envdir" install --no-index --find-links "$WHEELHOUSE_ROOT/wheelhouse-$scope" --only-binary=:all: --require-hashes -r "$LOCK_DIR/$scope.txt" >"$EVIDENCE_DIR/logs/install-command-$scope.txt"
  set +e
  "$PIP" --python "$envdir" install --no-index --find-links "$WHEELHOUSE_ROOT/wheelhouse-$scope" --only-binary=:all: --require-hashes -r "$LOCK_DIR/$scope.txt" >"$EVIDENCE_DIR/logs/install-$scope.log" 2>&1
  rc=$?
  set -e
  echo "$rc" >"$EVIDENCE_DIR/logs/install-$scope.exit"
  (( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/install-$scope.log" >&2; exit "$rc"; }
  set +e
  "$PIP" --python "$envdir" check >"$EVIDENCE_DIR/logs/pip-check-$scope.log" 2>&1
  rc=$?
  set -e
  echo "$rc" >"$EVIDENCE_DIR/logs/pip-check-$scope.exit"
  (( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/pip-check-$scope.log" >&2; exit "$rc"; }
  "$envdir/bin/python" - "$LOCK_DIR/$scope.txt" "$EVIDENCE_DIR/inventories/$scope.json" <<'PY'
from importlib import metadata
import json, re, sys
from pathlib import Path
lock, output = map(Path, sys.argv[1:])
expected = {}
for line in lock.read_text().splitlines():
    s=line.strip()
    if not s or s.startswith('#') or s.startswith('--') or '==' not in s: continue
    spec=s.split()[0].rstrip('\\')
    name,version=spec.split('==',1)
    key=re.sub(r'[-_.]+','-',name.split('[',1)[0]).lower()
    expected[key]=version
actual={re.sub(r'[-_.]+','-',d.metadata['Name']).lower():d.version for d in metadata.distributions() if d.metadata.get('Name')}
result={'scope':lock.stem,'expected_count':len(expected),'actual_count':len(actual),'missing_or_wrong':sorted(f'{k}=={v} (installed {actual.get(k)})' for k,v in expected.items() if actual.get(k)!=v),'unexpected':sorted(f'{k}=={v}' for k,v in actual.items() if expected.get(k)!=v)}
result['match']=not result['missing_or_wrong'] and not result['unexpected']
output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(0 if result['match'] else 1)
PY
 done

"$PYTHON" "$ROOT/scripts/verify_provisional_wheels.py" --manifest "$WHEELHOUSE_ROOT/wheel-hashes.csv" --wheelhouse-root "$WHEELHOUSE_ROOT" --locks "$LOCK_DIR" --output "$EVIDENCE_DIR/wheel-lock-verification.json" >"$EVIDENCE_DIR/logs/wheel-lock-verification.log" 2>&1
