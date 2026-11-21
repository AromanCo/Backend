# M6-A28I-P8 — Provisional Backend lock candidates

**PROVISIONAL — NOT APPROVED. Production remains NO-GO.** This Stage A work
does not constitute authoritative lock acceptance, independent human review,
CI or Docker adoption, or production approval. The 13 controls remain
UNVERIFIED and D1–D12 remain OPEN.

## Authorization and target

The Backend owner authorized Stage A candidate implementation in the comment
on [FrontEnd PR #61](https://github.com/AromanCo/FrontEnd/pull/61#issuecomment-6640654462).
It is bounded to Backend revision
`0be24c4597bd693e70348243c26e550a20a8ad0e`, Ubuntu 24.04.5 x86_64,
CPython 3.12.3, pip 26.3, pip-tools 7.6.2, setuptools 84.2.1,
pyproject-hooks 1.3.3, build 1.6.1, wheel 0.48.0, click 8.5.0, and
packaging 26.3. Only retained hash-verified P5/R1 wheels were used. No registry
access, package acquisition, or global installation was used.

The candidate files are in
`requirements/locks/provisional-ubuntu-24.04.5-x86_64-cp312/`:

| File | Experimental closure |
|---|---:|
| `runtime.txt` | 27 packages |
| `dev.txt` | 40 packages, including the runtime closure |
| `build.txt` | 1 static PEP 517 backend package |
| `bootstrap.txt` | 8 bootstrap/build-frontend packages |

Each file carries exact versions, `--only-binary :all:`, and SHA-256 hashes.
The matching inputs are under `requirements/lock-inputs/`. All are candidate
artifacts; candidate versions and retained wheel hashes remain unapproved.

## Generation and verification

Use `scripts/generate_provisional_locks.sh` with the retained P5/R1 tooling
environment and wheelhouses. It asserts Python 3.12.3, pip 26.3, and
pip-tools 7.6.2; invokes pip-compile with `--no-index`; and requires an
evidence directory outside both repositories. `scripts/verify_provisional_wheels.py`
checks all lock package/version/hash entries against the retained P5/R1
manifest and recalculates the digest of every retained wheel.

`scripts/verify_provisional_dependency_locks.sh` installs each scope into a
disposable `venv --without-pip` using candidate pip 26.3,
`--no-index --only-binary=:all: --require-hashes`, and only the corresponding
retained wheelhouse. It compares the complete installed package/version
inventory to the lock and runs `pip check`. Use a new external evidence
directory for each run.

`scripts/test_provisional_backend_wheel.sh` accepts no source revision override. It
exports only the P8-authorized source revision into the external evidence
directory, records its tree and archive SHA-256 plus the `pyproject.toml`
digest, derives `SOURCE_DATE_EPOCH` from the commit, captures the PEP 517
hook, and checks static and dynamic build closure against the candidate build
lock. It builds twice with `--no-isolation`, retains exact commands,
environment and exit codes, compares wheel bytes and ZIP members, then
installs run 1 into the tested runtime with `--no-deps` and no index. It checks
the 28-entry runtime-plus-application inventory, imports the installed wheel,
and runs `pip check`.

All shell tools validate absolute evidence paths before writes, reject paths
that overlap either repository lexically or after symlink resolution, and
require a fresh evidence directory. They redact inherited `PIP_*` setting
values, remove those variables from pip processes, set `PIP_CONFIG_FILE` to
the null device, and disable indexes and caches. The wheel verifier checks
every retained wheel before generation or install.

P8 run logs, commands, exit codes, environment, inventories, wheel hashes, and
reproducibility comparisons are retained outside the repositories at
`/home/mrq/aroman-evidence/m6-a28i-p8/`. P5 and P5-R1 evidence remain in their
original external directories and are not modified by this change.
H1 remediation logs and the consolidated run report are retained at
`/home/mrq/aroman-evidence/m6-a28i-p8-h1-report/`, with generation,
installation, and build evidence in the sibling `m6-a28i-p8-h1-generation-final`,
`m6-a28i-p8-h1-offline-verified`, and `m6-a28i-p8-h1-build-final2` directories.

## Experimental results

- Two offline lock-generation runs produced byte-identical lock files for all
  four scopes. This establishes repeatability for these fixed inputs, retained
  wheelhouses, candidate toolchain, and observed host; it does not establish
  reproducibility from mutable project ranges or an immutable builder.
- All 76 per-scope retained wheel files matched their P5/R1 SHA-256 manifest
  entries. Every candidate lock package/version/hash map matched its
  corresponding manifest exactly.
- The retained P5/R1 aggregate evidence manifests have a limited integrity
  caveat: all non-Python-symlink entries matched, but the 15 Python executable
  symlink entries in each 14,914-entry P5 manifest and 36 entries in the
  30,718-entry R1 manifest resolve now to `/usr/bin/python3.12`, whose digest
  differs from the recorded digest. The current interpreter reports 3.12.3;
  this does not establish its immutable identity. Retained wheel bytes were
  independently checked against the wheel manifest as noted above.
- Offline installed inventories matched exactly: runtime 27/27, dev 40/40,
  build 1/1, bootstrap 8/8. All four `pip check` commands passed.
- The PEP 517 hook returned static `setuptools>=75` and no dynamic
  requirements. Candidate build closure `setuptools==84.2.1` satisfies the
  static requirement. Candidate bootstrap closure contains `build==1.6.1`
  and `pyproject-hooks==1.3.3`; the wheel build used `--no-isolation`.
- The P8 Backend wheel installed offline with `--no-deps`. Its runtime
  inventory matched exactly at 28/28, package imports resolved from the
  disposable environment's `site-packages`, and `pip check` passed.
- Earlier builds without `SOURCE_DATE_EPOCH` differed only in ZIP timestamps
  on five `.dist-info` members. The hardened build derives the epoch from the
  authorized commit and produced byte-identical run 1/run 2 wheels with
  SHA-256 `7fcb99592ed19628e9911b9b38a69d8520b1b2ddcca37bf76ea2cd8fb805ea80`.
  This supports repeatability for this source, toolchain, and host; it does not
  establish immutable builder identity or authoritative artifact provenance.
- Local Backend tests completed: 219 passed, 6 skipped, with 1 deprecation
  warning. PostgreSQL/Docker gated suites were skipped because no disposable
  test service was provisioned.

## Stage B blockers

These candidates are not ready for authoritative acceptance. The owner must
still approve the exact toolchain, immutable builder, complete supported
target matrix, source and artifact provenance/retention chain, vulnerability
and license policy and review evidence, independent human review, and separate
acceptance authorization. The observed host is not an immutable builder, and
the P5/R1 wheel manifest proves byte equality with retained files but not their
trusted upstream provenance. The P5/R1 evidence explicitly records no
vulnerability or license scan. Candidate locks must not be adopted by CI,
Docker, release, or production until the separate Stage B requirements are
completed.

## F9 Stage B evidence inventory — 2026-11-21

This review covers the lock files at `a4b73e0d78932ca0f3037751e4bc6af862bdf6cf`
and the F9 restricted catalog source pin
`0be24c4597bd693e70348243c26e550a20a8ad0e`. It used public registry
metadata. The retained wheelhouse was unavailable in the review workspace.

| Scope | Locked entries | Matches to published PyPI wheel SHA-256 | Yanked matches |
| --- | ---: | ---: | ---: |
| Runtime | 27 | 27 | 0 |
| Static build | 1 | 1 | 0 |
| Bootstrap | 8 | 8 | 0 |
| Development | 40 | 40 | 0 |

- The [OSV batch API](https://google.github.io/osv.dev/post-v1-querybatch/)
  returned no advisories for the 46 distinct PyPI package/version pairs
  across these scopes and supplied no further page tokens. This point-in-time
  check covers Python lock pins. The base OS and bundled native libraries
  still need their own review against the selected build and runtime images.
- For the exact runtime wheels, the [PyPI Integrity API](https://docs.pypi.org/api/integrity/)
  returned nonempty attestation bundles for 15 of 27 wheels. The endpoint
  returned HTTP 404 for the other 12: alembic, annotated-doc,
  annotated-types, fastapi, h11, mako, opentelemetry-api, psycopg,
  psycopg-binary, pydantic-core, pyyaml, and watchfiles.
  Cryptographic verification of the 15 returned bundles and an approved
  alternate provenance record for the others are pending.
- PyPI runtime release JSON reported 22 SPDX expressions and four
  classifier-only entries. The [python-dotenv 1.2.4 file metadata page](https://pypi.org/project/python-dotenv/1.2.4/)
  supplies BSD-3-Clause for the remaining entry. PyPI reports LGPL-3.0-only
  for psycopg and psycopg-binary 3.3.8. The image review should verify
  distribution notices and bundled library licenses from the retained wheels.

To advance the restricted Backend image, identify the immutable Linux/amd64
builder and runtime images and verify their Python ABI, libc, and wheel tag
compatibility with the retained P5/R1 wheelhouse. Run the existing
`scripts/verify_provisional_wheels.py` against the retained
`baseline-p5/wheel-hashes.csv` and its wheel files. Record separately the
builder identity, verified wheel provenance, native-package audit, license
review, and reviewer disposition. The F9 catalog API Dockerfile still resolves
dependency ranges and an image built through that path would not establish
reproducibility from this lock and wheelhouse. Stage B acceptance and target
validation remain pending.

### Candidate Linux/amd64 platform

The candidate parent for both environments is the [Docker Official Ubuntu image](https://hub.docker.com/_/ubuntu)
at the platform manifest digest
`docker.io/library/ubuntu@sha256:9a04f13b3f80ef056361e30868593b1cfd2279fe19e4081cb93a90bf56819d6a`.
The manifest, config and root filesystem layer bytes matched their descriptor
digests. The root filesystem identifies itself as Ubuntu 24.04.5 LTS, has
`libc6 2.39-0ubuntu8.9`, and contains no Python 3 package. This records a
candidate parent. Derived builder and runtime image digests are still pending.

The [Ubuntu archive snapshot](https://snapshot.ubuntu.com/) at
`20261121T120000Z` was checked using the Ubuntu archive keyring in that
digest-pinned parent. All three `InRelease` signatures and their signed
amd64 main package-index hashes verified. Both updated and security indexes
listed `python3.12` at `3.12.3-1ubuntu0.17` with package SHA-256
`6745c9463432e619d7402b117ad4ac86c31dcd3999ba20daa9e395f6f9909d86`.
They also listed the matching minimal and standard-library packages and
`libc6 2.39-0ubuntu8.12`.

The proposed derived images should take their OS package closure from this
snapshot. Before accepting them, record the full package inventory and
resulting digests and verify the Python version, SOABI and glibc in the actual
images. The next verification needs the retained `baseline-p5` manifest and
its four wheel directories for the offline install. The registry and snapshot
checks did not resolve or install the closure or run an image.
