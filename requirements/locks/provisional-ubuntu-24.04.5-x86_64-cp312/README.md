# PROVISIONAL — NOT APPROVED

This directory contains Stage A candidate locks only. It does not authorize
Backend CI, Docker, release, or production use and has not received independent
review or Stage B acceptance.

## Candidate target and authorization

- Backend source: `0be24c4597bd693e70348243c26e550a20a8ad0e`
- Target: Ubuntu 24.04.5 x86_64, CPython 3.12.3 (`cpython-312-x86_64-linux-gnu`)
- Candidate tools: pip 26.3, pip-tools 7.6.2, setuptools 84.2.1,
  pyproject-hooks 1.3.3, build 1.6.1, wheel 0.48.0, click 8.5.0,
  packaging 26.3
- Bounded authorization: FrontEnd PR #61 comment
  <https://github.com/AromanCo/FrontEnd/pull/61#issuecomment-6640654462>
- Artifact basis: retained hash-verified P5/R1 wheelhouse only; no new package
  acquisition. P5/R1 reports and manifests remain outside this repository at
  `/home/mrq/aroman-evidence/m6-a28i-p5` and
  `/home/mrq/aroman-evidence/m6-a28i-p5-r1`.

The four files are separate install closures: runtime, dev, static build, and
bootstrap. Bootstrap includes pip and pip-tools plus the authorized candidate
toolchain closure. `build.txt` covers the static PEP 517 backend requirement;
the retained P5/R1 raw hook result reported no dynamic requirements for the
pinned source. That observation is experimental evidence, not a permanent
assertion about later source changes.

## Regenerate and verify offline

Use disposable CPython 3.12.3 and candidate tool commands from the retained
P5/R1 evidence. Point `AROMAN_P5_WHEELHOUSE_ROOT` to its copied
`baseline-p5` directory, `AROMAN_PYTHON` to the candidate tooling Python,
`AROMAN_PIP_COMPILE` to its `bin/pip-compile`, and
`AROMAN_EVIDENCE_DIR` to a new directory outside both repositories.
Then run `scripts/generate_provisional_locks.sh`. It asserts candidate Python,
pip and pip-tools versions, invokes pip-compile with `--no-index`, and records
commands, logs and exit codes outside the repository.

Run `scripts/verify_provisional_dependency_locks.sh` with the same external
evidence directory, setting `AROMAN_PIP` to candidate pip 26.3. It creates four
`venv --without-pip` environments; installs use only the corresponding
retained wheelhouse, `--no-index`, `--only-binary=:all:`, and
`--require-hashes`. Exact distribution/version inventories and `pip check`
results are captured externally. The wheel verifier compares every locked
package/version/hash and retained wheel byte digest to the P5/R1 manifest.

No default index, dependency resolution against a registry, uncontrolled build
dependency, or global installation is allowed. A missing wheel, hash mismatch,
target mismatch, or nonzero command is a hard failure. All generated locks and
inputs must continue to carry the provisional marker until separate Stage B
acceptance.
