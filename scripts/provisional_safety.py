"""Fail-closed path and pip-environment checks for P8 provisional tools."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

APPROVED_SOURCE_REVISION = "0be24c4597bd693e70348243c26e550a20a8ad0e"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = BACKEND_ROOT.parent / "FrontEnd"


def _overlaps(path: Path, repo: Path) -> bool:
    return path == repo or path in repo.parents or repo in path.parents


def validate_evidence_path(raw: str | os.PathLike[str], *, must_not_exist: bool = True) -> Path:
    """Require a new absolute external path and reject lexical or resolved repo overlap."""
    text = os.fspath(raw)
    candidate = Path(text)
    if not candidate.is_absolute():
        raise ValueError("evidence path must be absolute")
    if any(part in {".", ".."} for part in text.split("/")):
        raise ValueError("evidence path must not contain . or .. components")
    if "\x00" in text:
        raise ValueError("evidence path contains NUL")
    # Resolve the nearest existing parent before any mkdir. This detects symlink
    # traversal even when the requested leaf does not exist yet.
    resolved = candidate.resolve(strict=False)
    for repo in (BACKEND_ROOT.resolve(), FRONTEND_ROOT.resolve()):
        if _overlaps(candidate, repo) or _overlaps(resolved, repo):
            raise ValueError(f"evidence path overlaps repository: {repo}")
    if must_not_exist and (candidate.exists() or candidate.is_symlink()):
        raise ValueError("evidence path already exists; choose a new run directory")
    return resolved


def validate_wheelhouse_path(raw: str | os.PathLike[str]) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("wheelhouse path must be absolute")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("wheelhouse path must be a directory")
    if any(
        _overlaps(path, repo.resolve()) or _overlaps(resolved, repo.resolve())
        for repo in (BACKEND_ROOT, FRONTEND_ROOT)
    ):
        raise ValueError("wheelhouse path must be outside both repositories")
    return resolved


def validate_external_directory(raw: str | os.PathLike[str]) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("external environment path must be absolute")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("external environment path must be a directory")
    if any(
        _overlaps(candidate, repo.resolve()) or _overlaps(resolved, repo.resolve())
        for candidate in (path,)
        for repo in (BACKEND_ROOT, FRONTEND_ROOT)
    ):
        raise ValueError("external environment path must be outside both repositories")
    return resolved


def pip_environment() -> dict[str, str]:
    """Return an isolated, offline pip environment with all caller config removed."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PIP_")}
    env.update(
        PIP_CONFIG_FILE=os.devnull,
        PIP_NO_INDEX="1",
        PIP_NO_CACHE_DIR="1",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--wheelhouse")
    parser.add_argument("--source-revision")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    requested_source = args.source_revision or os.environ.get("AROMAN_SOURCE_REV")
    if requested_source and requested_source != APPROVED_SOURCE_REVISION:
        raise ValueError("source revision differs from P8 authorization")
    evidence = validate_evidence_path(args.evidence)
    if args.wheelhouse:
        validate_wheelhouse_path(args.wheelhouse)
    if not args.check_only:
        evidence.mkdir(parents=True, exist_ok=False)
    print(evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
