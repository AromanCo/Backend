#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET='provisional-ubuntu-24.04.5-x86_64-cp312'
LOCK_DIR="$ROOT/requirements/locks/$TARGET"
EVIDENCE_DIR="${AROMAN_EVIDENCE_DIR:?Set evidence directory outside both repositories}"
PYTHON="${AROMAN_PYTHON:?Set retained candidate Python 3.12.3}"
PIP="${AROMAN_PIP:?Set retained candidate pip 26.3}"
SOURCE_REV="${AROMAN_SOURCE_REV:-0be24c4597bd693e70348243c26e550a20a8ad0e}"
BOOTSTRAP="$EVIDENCE_DIR/venvs/bootstrap"
RUNTIME="$EVIDENCE_DIR/venvs/runtime"
[[ "$EVIDENCE_DIR" != "$ROOT"/* && "$EVIDENCE_DIR" != *'/FrontEnd/'* ]] || { echo 'evidence must be outside both repositories' >&2; exit 2; }
mkdir -p "$EVIDENCE_DIR/source-backend" "$EVIDENCE_DIR/wheels/backend"
printf 'source_revision=%s\n' "$SOURCE_REV" > "$EVIDENCE_DIR/logs/backend-wheel-build-command.txt"
git -C "$ROOT" archive --format=tar "$SOURCE_REV" | tar -xf - -C "$EVIDENCE_DIR/source-backend"
printf 'pyproject_sha256=' >> "$EVIDENCE_DIR/logs/backend-wheel-build-command.txt"
sha256sum "$EVIDENCE_DIR/source-backend/pyproject.toml" >> "$EVIDENCE_DIR/logs/backend-wheel-build-command.txt"

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
printf '%s\n' "$?" > "$EVIDENCE_DIR/logs/pep517-hook.exit"

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

printf '%q ' "$BOOTSTRAP/bin/python" -m build --no-isolation --wheel --outdir "$EVIDENCE_DIR/wheels/backend" "$EVIDENCE_DIR/source-backend" > "$EVIDENCE_DIR/logs/backend-wheel-build-command.txt"
printf '\n' >> "$EVIDENCE_DIR/logs/backend-wheel-build-command.txt"
set +e
PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 \
  "$BOOTSTRAP/bin/python" -m build --no-isolation --wheel --outdir "$EVIDENCE_DIR/wheels/backend" "$EVIDENCE_DIR/source-backend" > "$EVIDENCE_DIR/logs/backend-wheel-build.log" 2>&1
rc=$?
set -e
echo "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-build.exit"
(( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/backend-wheel-build.log" >&2; exit "$rc"; }
wheel=("$EVIDENCE_DIR"/wheels/backend/*.whl)
(( ${#wheel[@]} == 1 )) || { echo 'expected exactly one Backend wheel' >&2; exit 3; }
sha256sum "${wheel[0]}" > "$EVIDENCE_DIR/logs/backend-wheel.sha256"

printf '%q ' "$PIP" --python "$RUNTIME" install --no-index --no-deps --no-build-isolation "${wheel[0]}" > "$EVIDENCE_DIR/logs/backend-wheel-install-command.txt"
printf '\n' >> "$EVIDENCE_DIR/logs/backend-wheel-install-command.txt"
set +e
PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 "$PIP" --python "$RUNTIME" install --no-index --no-deps --no-build-isolation "${wheel[0]}" > "$EVIDENCE_DIR/logs/backend-wheel-install.log" 2>&1
rc=$?
set -e
echo "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-install.exit"
(( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/backend-wheel-install.log" >&2; exit "$rc"; }

set +e
"$PIP" --python "$RUNTIME" check > "$EVIDENCE_DIR/logs/backend-wheel-pip-check.log" 2>&1
rc=$?
set -e
echo "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-pip-check.exit"
(( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/backend-wheel-pip-check.log" >&2; exit "$rc"; }

set +e
DATABASE_URL='postgresql+psycopg://offline:offline@127.0.0.1:5432/offline' \
OTP_PEPPER=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa SESSION_PEPPER=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  "$RUNTIME/bin/python" -I -c 'import pathlib, aroman, aroman.main, aroman.models, aroman.seed; p=pathlib.Path(aroman.__file__).resolve(); assert "site-packages" in p.parts, p; print("aroman_import_origin="+str(p)); print("imports=PASS aroman, aroman.main, aroman.models, aroman.seed")' > "$EVIDENCE_DIR/logs/backend-wheel-imports.log" 2>&1
rc=$?
set -e
echo "$rc" > "$EVIDENCE_DIR/logs/backend-wheel-imports.exit"
(( rc == 0 )) || { cat "$EVIDENCE_DIR/logs/backend-wheel-imports.log" >&2; exit "$rc"; }

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
