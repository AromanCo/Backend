#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET='provisional-ubuntu-24.04.5-x86_64-cp312'
LOCK_DIR="$ROOT/requirements/locks/$TARGET"
EVIDENCE_DIR="${AROMAN_EVIDENCE_DIR:?Set evidence directory outside both repositories}"
PYTHON="${AROMAN_PYTHON:?Set retained candidate Python 3.12.3}"
PIP="${AROMAN_PIP:?Set retained candidate pip 26.3}"
BOOTSTRAP_ENV="${AROMAN_BOOTSTRAP_ENV:?Set retained, offline-verified candidate bootstrap environment}"
RUNTIME_ENV="${AROMAN_RUNTIME_ENV:?Set retained, offline-verified candidate runtime environment}"
SOURCE_REV='0be24c4597bd693e70348243c26e550a20a8ad0e'
if [[ -n "${AROMAN_SOURCE_REV+x}" ]]; then
  echo 'AROMAN_SOURCE_REV override is not supported; source is fixed by P8 authorization' >&2
  exit 2
fi
cd "$ROOT"
EVIDENCE_DIR="$(python3 "$ROOT/scripts/provisional_safety.py" --check-only --evidence "$EVIDENCE_DIR" --source-revision "$SOURCE_REV")"
BOOTSTRAP="$(python3 -c 'from scripts.provisional_safety import validate_external_directory; print(validate_external_directory(__import__("sys").argv[1]))' "$BOOTSTRAP_ENV")"
RUNTIME="$(python3 -c 'from scripts.provisional_safety import validate_external_directory; print(validate_external_directory(__import__("sys").argv[1]))' "$RUNTIME_ENV")"
EVIDENCE_DIR="$(python3 "$ROOT/scripts/provisional_safety.py" --evidence "$EVIDENCE_DIR" --source-revision "$SOURCE_REV")"
mkdir -p "$EVIDENCE_DIR/source-backend" "$EVIDENCE_DIR/wheels/backend/run1" "$EVIDENCE_DIR/wheels/backend/run2" "$EVIDENCE_DIR/logs" "$EVIDENCE_DIR/inventories"
env | awk -F= '/^PIP_/ {print $1 "=<redacted>"}' | sort > "$EVIDENCE_DIR/logs/inherited-pip-settings.txt"
while IFS= read -r name; do unset "$name"; done < <(export -p | sed -n 's/^declare -x \(PIP_[A-Za-z0-9_]*\)=.*/\1/p')
export PIP_CONFIG_FILE=/dev/null PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
ACTUAL_REV="$(git -C "$ROOT" rev-parse "$SOURCE_REV^{commit}")"
[[ "$ACTUAL_REV" == "$SOURCE_REV" ]] || { echo 'authorized source commit unavailable or mismatched' >&2; exit 2; }
TREE_SHA="$(git -C "$ROOT" rev-parse "$SOURCE_REV^{tree}")"
SOURCE_DATE_EPOCH="$(git -C "$ROOT" show -s --format=%ct "$SOURCE_REV")"
export SOURCE_DATE_EPOCH
{
  printf 'authorized_source_revision=%s\nresolved_source_revision=%s\nsource_tree=%s\nsource_date_epoch=%s\n' "$SOURCE_REV" "$ACTUAL_REV" "$TREE_SHA" "$SOURCE_DATE_EPOCH"
} > "$EVIDENCE_DIR/source-metadata.txt"
git -C "$ROOT" archive --format=tar "$SOURCE_REV" | tee "$EVIDENCE_DIR/source-backend.tar" | tar -xf - -C "$EVIDENCE_DIR/source-backend"
sha256sum "$EVIDENCE_DIR/source-backend.tar" > "$EVIDENCE_DIR/source-archive.sha256"
printf 'source_revision=%s\nsource_tree=%s\nsource_date_epoch=%s\n' "$SOURCE_REV" "$TREE_SHA" "$SOURCE_DATE_EPOCH" > "$EVIDENCE_DIR/logs/backend-wheel-build-command.txt"
printf 'pyproject_sha256=' >> "$EVIDENCE_DIR/logs/backend-wheel-build-command.txt"
sha256sum "$EVIDENCE_DIR/source-backend/pyproject.toml" >> "$EVIDENCE_DIR/logs/backend-wheel-build-command.txt"
printf 'source_archive_command=git -C %q archive --format=tar %q | tee %q | tar -xf - -C %q\n' "$ROOT" "$SOURCE_REV" "$EVIDENCE_DIR/source-backend.tar" "$EVIDENCE_DIR/source-backend" >> "$EVIDENCE_DIR/logs/backend-wheel-build-command.txt"
"$PYTHON" -VV > "$EVIDENCE_DIR/environment-python.txt" 2>&1
grep -F '3.12.3' "$EVIDENCE_DIR/environment-python.txt" >/dev/null
"$PIP" --version > "$EVIDENCE_DIR/environment-pip.txt" 2>&1
grep -F 'pip 26.3 ' "$EVIDENCE_DIR/environment-pip.txt" >/dev/null
"$BOOTSTRAP/bin/pip-compile" --version > "$EVIDENCE_DIR/environment-pip-tools.txt" 2>&1
grep -F 'pip-compile, version 7.6.2' "$EVIDENCE_DIR/environment-pip-tools.txt" >/dev/null
"$PYTHON" -c 'import os,platform,sys,sysconfig; print("os="+platform.platform()); print("machine="+platform.machine()); print("python="+sys.version); print("soabi="+str(sysconfig.get_config_var("SOABI"))); print("SOURCE_DATE_EPOCH="+os.environ.get("SOURCE_DATE_EPOCH",""))' > "$EVIDENCE_DIR/environment-target.txt"
cat /etc/os-release > "$EVIDENCE_DIR/environment-os-release.txt"
uname -a > "$EVIDENCE_DIR/environment-uname.txt"
ldd --version 2>&1 | head -n 1 > "$EVIDENCE_DIR/environment-glibc.txt"
cp /home/mrq/aroman-evidence/m6-a28i-p5-r1/wheel-tags.txt "$EVIDENCE_DIR/environment-wheel-tags.txt"
printf 'PIP_CONFIG_FILE=/dev/null\nPIP_NO_INDEX=1\nPIP_NO_CACHE_DIR=1\nPIP_DISABLE_PIP_VERSION_CHECK=1\nPIP_INDEX_URL/PIP_EXTRA_INDEX_URL/PIP_FIND_LINKS/PIP_CACHE_DIR=unset\n' > "$EVIDENCE_DIR/environment-pip-policy.txt"

printf '%q ' "$BOOTSTRAP/bin/python" - "$EVIDENCE_DIR/source-backend" > "$EVIDENCE_DIR/logs/pep517-hook.command"
printf '\n' >> "$EVIDENCE_DIR/logs/pep517-hook.command"
set +e
"$BOOTSTRAP/bin/python" - "$EVIDENCE_DIR/source-backend" > "$EVIDENCE_DIR/logs/pep517-hook-raw.log" 2>&1 <<'PY'
from pathlib import Path
import json, sys, tomllib
from pyproject_hooks import BuildBackendHookCaller
source = Path(sys.argv[1]).resolve()
static = tomllib.loads((source / 'pyproject.toml').read_text())['build-system']['requires']
caller = BuildBackendHookCaller(str(source), 'setuptools.build_meta', python_executable=sys.executable)
dynamic = list(caller.get_requires_for_build_wheel({}))
result = {'backend':'setuptools.build_meta','static_requires':static,
          'hook':'get_requires_for_build_wheel','config_settings':{},'dynamic_requires':dynamic}
print('PEP517_HOOK_RESULT_JSON=' + json.dumps(result, sort_keys=True))
PY
rc=$?
set -e
printf '%s\n' "$rc" > "$EVIDENCE_DIR/logs/pep517-hook.exit"
(( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/pep517-hook-raw.log" >&2; exit "$rc"; }

printf '%q ' "$BOOTSTRAP/bin/python" - "$EVIDENCE_DIR/logs/pep517-hook-raw.log" "$LOCK_DIR/build.txt" "$LOCK_DIR/bootstrap.txt" "$EVIDENCE_DIR/pep517-closure.json" > "$EVIDENCE_DIR/logs/pep517-closure.command"
printf '\n' >> "$EVIDENCE_DIR/logs/pep517-closure.command"
set +e
"$BOOTSTRAP/bin/python" - "$EVIDENCE_DIR/logs/pep517-hook-raw.log" "$LOCK_DIR/build.txt" "$LOCK_DIR/bootstrap.txt" "$EVIDENCE_DIR/pep517-closure.json" <<'PY'
import json, re, sys
from pathlib import Path
from packaging.requirements import Requirement
from packaging.version import Version
raw, build_lock, bootstrap_lock, output = map(Path, sys.argv[1:])
line = next(x for x in raw.read_text().splitlines() if x.startswith('PEP517_HOOK_RESULT_JSON='))
hook = json.loads(line.split('=', 1)[1])
def pins(path):
    found = {}
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith('#') or s.startswith('--') or '==' not in s:
            continue
        name, version = s.split()[0].rstrip('\\').split('==', 1)
        found[re.sub(r'[-_.]+', '-', name.split('[', 1)[0]).lower()] = version
    return found
build = pins(build_lock)
bootstrap = pins(bootstrap_lock)
requirements = hook['static_requires'] + hook['dynamic_requires']
missing = []
for raw_req in requirements:
    req = Requirement(raw_req)
    version = build.get(re.sub(r'[-_.]+', '-', req.name).lower())
    if version is None or Version(version) not in req.specifier:
        missing.append(raw_req)
frontend = {name: bootstrap.get(name) for name in ('build', 'pyproject-hooks')}
complete = frontend == {'build': '1.6.1', 'pyproject-hooks': '1.3.3'}
result = {'hook': hook, 'build_lock': build, 'bootstrap_frontend': frontend,
          'unclosed_build_requirements': missing, 'frontend_complete': complete,
          'closure_pass': not missing and complete}
output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
raise SystemExit(0 if result['closure_pass'] else 1)
PY
rc=$?
set -e
printf '%s\n' "$rc" > "$EVIDENCE_DIR/logs/pep517-closure.exit"
(( rc == 0 )) || exit "$rc"

for run in run1 run2; do
  out="$EVIDENCE_DIR/wheels/backend/$run"
  cmd=("$BOOTSTRAP/bin/python" -m build --no-isolation --wheel --outdir "$out" "$EVIDENCE_DIR/source-backend")
  printf '%q ' "${cmd[@]}" > "$EVIDENCE_DIR/logs/backend-wheel-build-$run.command"
  printf '\n' >> "$EVIDENCE_DIR/logs/backend-wheel-build-$run.command"
  set +e
  "${cmd[@]}" > "$EVIDENCE_DIR/logs/backend-wheel-build-$run.log" 2>&1
  rc=$?
  set -e
  echo "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-build-$run.exit"
  (( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/backend-wheel-build-$run.log" >&2; exit "$rc"; }
  wheel=("$out"/*.whl)
  (( ${#wheel[@]} == 1 )) || { echo "expected exactly one wheel for $run" >&2; exit 3; }
  sha256sum "${wheel[0]}" > "$EVIDENCE_DIR/logs/backend-wheel-$run.sha256"
done
printf '%q ' "$PYTHON" "$ROOT/scripts/compare_provisional_wheels.py" \
  --run1 "$EVIDENCE_DIR/wheels/backend/run1" \
  --run2 "$EVIDENCE_DIR/wheels/backend/run2" \
  --evidence "$EVIDENCE_DIR/logs/backend-wheel-zip-comparison.json" \
  > "$EVIDENCE_DIR/logs/backend-wheel-reproducibility.command"
printf '\n' >> "$EVIDENCE_DIR/logs/backend-wheel-reproducibility.command"
set +e
"$PYTHON" "$ROOT/scripts/compare_provisional_wheels.py" \
  --run1 "$EVIDENCE_DIR/wheels/backend/run1" \
  --run2 "$EVIDENCE_DIR/wheels/backend/run2" \
  --evidence "$EVIDENCE_DIR/logs/backend-wheel-zip-comparison.json" \
  > "$EVIDENCE_DIR/logs/backend-wheel-reproducibility.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-reproducibility.exit"
if (( rc != 0 )); then
  cat "$EVIDENCE_DIR/logs/backend-wheel-reproducibility.log" >&2
  echo 'wheel reproducibility failed; refusing to install or package the wheel' >&2
  exit "$rc"
fi
wheel=("$EVIDENCE_DIR"/wheels/backend/run1/*.whl)
cp "${wheel[0]}" "$EVIDENCE_DIR/wheels/backend/aroman_backend-0.1.0-py3-none-any.whl"
sha256sum "$EVIDENCE_DIR/wheels/backend/aroman_backend-0.1.0-py3-none-any.whl" > "$EVIDENCE_DIR/logs/backend-wheel.sha256"

printf 'PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 ' > "$EVIDENCE_DIR/logs/backend-wheel-install-command.txt"
printf '%q ' "$PIP" --python "$RUNTIME" install --no-index --no-deps --no-build-isolation "${wheel[0]}" >> "$EVIDENCE_DIR/logs/backend-wheel-install-command.txt"
printf '\n' >> "$EVIDENCE_DIR/logs/backend-wheel-install-command.txt"
set +e
PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 "$PIP" --python "$RUNTIME" install --no-index --no-deps --no-build-isolation "${wheel[0]}" > "$EVIDENCE_DIR/logs/backend-wheel-install.log" 2>&1
rc=$?
set -e
echo "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-install.exit"
(( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/backend-wheel-install.log" >&2; exit "$rc"; }

printf '%q ' "$PIP" --python "$RUNTIME" check > "$EVIDENCE_DIR/logs/backend-wheel-pip-check.command"
printf '\n' >> "$EVIDENCE_DIR/logs/backend-wheel-pip-check.command"
set +e
"$PIP" --python "$RUNTIME" check > "$EVIDENCE_DIR/logs/backend-wheel-pip-check.log" 2>&1
rc=$?
set -e
echo "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-pip-check.exit"
(( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/backend-wheel-pip-check.log" >&2; exit "$rc"; }

printf '%q ' env DATABASE_URL='postgresql+psycopg://offline:offline@127.0.0.1:5432/offline' OTP_PEPPER=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa SESSION_PEPPER=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb "$RUNTIME/bin/python" -I -c 'import pathlib, aroman, aroman.main, aroman.models, aroman.seed; p=pathlib.Path(aroman.__file__).resolve(); assert "site-packages" in p.parts, p; print("aroman_import_origin="+str(p)); print("imports=PASS aroman, aroman.main, aroman.models, aroman.seed")' > "$EVIDENCE_DIR/logs/backend-wheel-imports.command"
printf '\n' >> "$EVIDENCE_DIR/logs/backend-wheel-imports.command"
set +e
DATABASE_URL='postgresql+psycopg://offline:offline@127.0.0.1:5432/offline' \
OTP_PEPPER=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa SESSION_PEPPER=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  "$RUNTIME/bin/python" -I -c 'import pathlib, aroman, aroman.main, aroman.models, aroman.seed; p=pathlib.Path(aroman.__file__).resolve(); assert "site-packages" in p.parts, p; print("aroman_import_origin="+str(p)); print("imports=PASS aroman, aroman.main, aroman.models, aroman.seed")' > "$EVIDENCE_DIR/logs/backend-wheel-imports.log" 2>&1
rc=$?
set -e
echo "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-imports.exit"
(( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/backend-wheel-imports.log" >&2; exit "$rc"; }

printf '%q ' "$RUNTIME/bin/python" - "$LOCK_DIR/runtime.txt" "$EVIDENCE_DIR/inventories/runtime-with-backend-wheel.json" > "$EVIDENCE_DIR/logs/backend-wheel-inventory.command"
printf '\n' >> "$EVIDENCE_DIR/logs/backend-wheel-inventory.command"
set +e
"$RUNTIME/bin/python" - "$LOCK_DIR/runtime.txt" "$EVIDENCE_DIR/inventories/runtime-with-backend-wheel.json" <<'PY'
from importlib import metadata
import json, re, sys
from pathlib import Path
lock, output = map(Path, sys.argv[1:])
expected={}
for line in lock.read_text().splitlines():
    s=line.strip()
    if not s or s.startswith('#') or s.startswith('--') or '==' not in s: continue
    name,version=s.split()[0].rstrip('\\').split('==',1)
    expected[re.sub(r'[-_.]+','-',name.split('[',1)[0]).lower()]=version
expected['aroman-backend']='0.1.0'
actual={re.sub(r'[-_.]+','-',d.metadata['Name']).lower():d.version for d in metadata.distributions() if d.metadata.get('Name')}
result={'expected_count':len(expected),'actual_count':len(actual),'missing_or_wrong':sorted(f'{k}=={v} (installed {actual.get(k)})' for k,v in expected.items() if actual.get(k)!=v),'unexpected':sorted(f'{k}=={v}' for k,v in actual.items() if expected.get(k)!=v)}
result['match']=not result['missing_or_wrong'] and not result['unexpected']
output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(0 if result['match'] else 1)
PY
rc=$?
set -e
printf '%s\n' "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-inventory.exit"
(( rc == 0 )) || exit "$rc"
