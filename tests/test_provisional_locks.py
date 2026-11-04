import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.provisional_safety import (
    APPROVED_SOURCE_REVISION,
    BACKEND_ROOT,
    FRONTEND_ROOT,
    pip_environment,
    validate_evidence_path,
)
from scripts.verify_provisional_wheels import main as verify_wheels

LOCK_ROOT = Path(__file__).parents[1] / "requirements/locks/provisional-ubuntu-24.04.5-x86_64-cp312"
VERIFY_SCRIPT = Path(__file__).parents[1] / "scripts/provisional_safety.py"
BUILD_SCRIPT = Path(__file__).parents[1] / "scripts/test_provisional_backend_wheel.sh"
GENERATE_SCRIPT = Path(__file__).parents[1] / "scripts/generate_provisional_locks.sh"


def parsed(path):
    entries = {}
    for line in path.read_text().splitlines():
        value = line.strip()
        if not value or value.startswith("#") or value.startswith("--"):
            continue
        if "==" in value:
            spec = value.split()[0].rstrip("\\")
            name, version = spec.split("==", 1)
            entries[name.split("[", 1)[0].lower().replace("_", "-")] = version
    return entries


def test_candidate_locks_are_provisional_and_hash_pinned():
    assert "PROVISIONAL — NOT APPROVED" in (LOCK_ROOT / "README.md").read_text()
    for scope in ("runtime", "dev", "build", "bootstrap"):
        path = LOCK_ROOT / f"{scope}.txt"
        text = path.read_text()
        assert text.startswith("# PROVISIONAL — NOT APPROVED")
        assert "--only-binary :all:" in text
        assert "--index-url" not in text
        assert "--find-links" not in text
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "==" in line and not line.lstrip().startswith("#"):
                assert i + 1 < len(lines) and "--hash=sha256:" in lines[i + 1]


def test_dev_is_a_standalone_superset_of_runtime():
    assert parsed(LOCK_ROOT / "runtime.txt").items() <= parsed(LOCK_ROOT / "dev.txt").items()


def test_bootstrap_contains_authorized_candidate_toolchain():
    bootstrap = parsed(LOCK_ROOT / "bootstrap.txt")
    assert {
        name: bootstrap[name]
        for name in (
            "pip",
            "pip-tools",
            "setuptools",
            "pyproject-hooks",
            "build",
            "wheel",
            "click",
            "packaging",
        )
    } == {
        "pip": "26.3",
        "pip-tools": "7.6.2",
        "setuptools": "84.2.1",
        "pyproject-hooks": "1.3.3",
        "build": "1.6.1",
        "wheel": "0.48.0",
        "click": "8.5.0",
        "packaging": "26.3",
    }


def test_evidence_path_rejects_relative_and_dotdot(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        validate_evidence_path("relative/evidence")
    with pytest.raises(ValueError, match="components"):
        validate_evidence_path(tmp_path / ".." / "escape")


def test_evidence_path_rejects_repository_and_symlink_escape(tmp_path):
    with pytest.raises(ValueError, match="overlaps repository"):
        validate_evidence_path(BACKEND_ROOT / "new-evidence")
    link = tmp_path / "link-to-backend"
    link.symlink_to(BACKEND_ROOT, target_is_directory=True)
    with pytest.raises(ValueError, match="overlaps repository"):
        validate_evidence_path(link / "evidence")
    with pytest.raises(ValueError, match="overlaps repository"):
        validate_evidence_path(FRONTEND_ROOT / "new-evidence")


def test_pip_environment_discards_caller_acquisition_settings(monkeypatch):
    monkeypatch.setenv("PIP_INDEX_URL", "https://example.invalid/simple")
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://example.invalid/extra")
    monkeypatch.setenv("PIP_FIND_LINKS", "/unexpected")
    monkeypatch.setenv("PIP_CACHE_DIR", "/unexpected-cache")
    env = pip_environment()
    allowed = {
        "PIP_CONFIG_FILE",
        "PIP_NO_INDEX",
        "PIP_NO_CACHE_DIR",
        "PIP_DISABLE_PIP_VERSION_CHECK",
    }
    assert {key for key in env if key.startswith("PIP_")} == allowed
    assert env["PIP_CONFIG_FILE"] == os.devnull
    assert env["PIP_NO_INDEX"] == "1"
    assert env["PIP_NO_CACHE_DIR"] == "1"


def test_evidence_path_refuses_to_overwrite_existing_run(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        validate_evidence_path(existing)


def test_wrong_source_revision_is_rejected_without_creating_evidence(tmp_path):
    evidence = tmp_path / "never-created"
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_SCRIPT),
            "--evidence",
            str(evidence),
            "--source-revision",
            "deadbeef",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "source revision differs" in result.stderr
    assert not evidence.exists()
    assert len(APPROVED_SOURCE_REVISION) == 40


def test_source_revision_override_cannot_be_smuggled_in_environment(tmp_path):
    evidence = tmp_path / "never-created"
    result = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), "--evidence", str(evidence)],
        env={**os.environ, "AROMAN_SOURCE_REV": "deadbeef"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "source revision differs" in result.stderr
    assert not evidence.exists()


def test_build_script_rejects_wrong_revision_before_writing(tmp_path):
    evidence = tmp_path / "build-evidence"
    result = subprocess.run(
        ["bash", str(BUILD_SCRIPT)],
        env={
            **os.environ,
            "AROMAN_SOURCE_REV": "deadbeef",
            "AROMAN_EVIDENCE_DIR": str(evidence),
            "AROMAN_PYTHON": "/unused/python",
            "AROMAN_PIP": "/unused/pip",
            "AROMAN_BOOTSTRAP_ENV": "/unused/bootstrap",
            "AROMAN_RUNTIME_ENV": "/unused/runtime",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "override is not supported" in result.stderr
    assert not evidence.exists()


def test_build_script_rejects_even_matching_revision_override(tmp_path):
    evidence = tmp_path / "build-evidence"
    result = subprocess.run(
        ["bash", str(BUILD_SCRIPT)],
        env={
            **os.environ,
            "AROMAN_SOURCE_REV": APPROVED_SOURCE_REVISION,
            "AROMAN_EVIDENCE_DIR": str(evidence),
            "AROMAN_PYTHON": "/unused/python",
            "AROMAN_PIP": "/unused/pip",
            "AROMAN_BOOTSTRAP_ENV": "/unused/bootstrap",
            "AROMAN_RUNTIME_ENV": "/unused/runtime",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "override is not supported" in result.stderr
    assert not evidence.exists()


def test_generation_script_rejects_repo_evidence_path_before_writing(tmp_path):
    evidence = BACKEND_ROOT / ".p8-negative-evidence-must-not-exist"
    result = subprocess.run(
        ["bash", str(GENERATE_SCRIPT)],
        env={
            **os.environ,
            "AROMAN_EVIDENCE_DIR": str(evidence),
            "AROMAN_P5_WHEELHOUSE_ROOT": str(tmp_path),
            "AROMAN_PIP_COMPILE": "/unused/pip-compile",
            "AROMAN_PYTHON": "/unused/python",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "overlaps repository" in result.stderr
    assert not evidence.exists()


def _verifier_fixture(tmp_path, wheel_bytes=b"wheel bytes"):
    root = tmp_path / "wheelhouse-root"
    (root / "wheelhouse-runtime").mkdir(parents=True)
    wheel = root / "wheelhouse-runtime" / "sample-1.0-py3-none-any.whl"
    wheel.write_bytes(wheel_bytes)
    digest = hashlib.sha256(wheel_bytes).hexdigest()
    manifest = root / "wheel-hashes.csv"
    with manifest.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["scope", "package", "version", "wheel", "sha256"])
        writer.writerow(["runtime", "sample", "1.0", wheel.name, digest])
    locks = tmp_path / "locks"
    locks.mkdir()
    for scope in ("runtime", "dev", "build", "bootstrap"):
        (locks / f"{scope}.txt").write_text("--only-binary :all:\n")
    (locks / "runtime.txt").write_text(f"sample==1.0 \\\n    --hash=sha256:{digest}\n")
    output = tmp_path / "evidence" / "result.json"
    output.parent.mkdir()
    return root, manifest, locks, output, wheel, digest


def _run_wheel_verifier(monkeypatch, manifest, root, locks, output):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_provisional_wheels",
            "--manifest",
            str(manifest),
            "--wheelhouse-root",
            str(root),
            "--locks",
            str(locks),
            "--output",
            str(output),
        ],
    )
    return verify_wheels()


@pytest.mark.parametrize("fault", ["missing-wheel", "corrupt-wheel", "incorrect-hash"])
def test_wheel_verifier_rejects_missing_corrupt_and_incorrect_hash(tmp_path, monkeypatch, fault):
    root, manifest, locks, output, wheel, digest = _verifier_fixture(tmp_path)
    if fault == "missing-wheel":
        wheel.unlink()
    elif fault == "corrupt-wheel":
        wheel.write_bytes(b"corrupted wheel bytes")
    else:
        (locks / "runtime.txt").write_text("sample==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n")
    result = _run_wheel_verifier(monkeypatch, manifest, root, locks, output)
    report = json.loads(output.read_text())
    assert result == 1
    assert report["problems"]


@pytest.mark.parametrize("fault", ["missing-package", "unexpected-package"])
def test_wheel_verifier_rejects_incomplete_or_unexpected_lock_entries(tmp_path, monkeypatch, fault):
    root, manifest, locks, output, _wheel, digest = _verifier_fixture(tmp_path)
    if fault == "missing-package":
        (locks / "runtime.txt").write_text("--only-binary :all:\n")
    else:
        (locks / "runtime.txt").write_text(
            f"sample==1.0 \\\n    --hash=sha256:{digest}\n"
            f"extra==2.0 \\\n    --hash=sha256:{'1' * 64}\n"
        )
    result = _run_wheel_verifier(monkeypatch, manifest, root, locks, output)
    report = json.loads(output.read_text())
    assert result == 1
    assert not report["lock_scopes"]["runtime"]["match"]


def test_wheel_verifier_refuses_existing_evidence_output(tmp_path, monkeypatch):
    root, manifest, locks, output, _wheel, _digest = _verifier_fixture(tmp_path)
    output.write_text("preserve me")
    with pytest.raises(ValueError, match="already exists"):
        _run_wheel_verifier(monkeypatch, manifest, root, locks, output)
    assert output.read_text() == "preserve me"
