#!/usr/bin/env python3
"""Check provisional lock pins/hashes against retained P5/R1 wheel bytes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def lock_map(path: Path) -> dict[tuple[str, str], set[str]]:
    entries: dict[tuple[str, str], set[str]] = {}
    current = None
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current and "--hash=sha256:" in stripped:
            entries[current].add(stripped.split("--hash=sha256:", 1)[1].strip().rstrip("\\"))
            if not stripped.endswith("\\"):
                current = None
            continue
        if stripped.startswith("--"):
            continue
        if "==" in stripped:
            spec = stripped.split()[0].rstrip("\\")
            name, version = spec.split("==", 1)
            current = (canonical(name.split("[", 1)[0]), version)
            entries[current] = set()
    return entries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--wheelhouse-root", type=Path, required=True)
    parser.add_argument("--locks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = list(csv.DictReader(args.manifest.open()))
    report = {"provisional": True, "wheel_scopes": {}, "lock_scopes": {}, "problems": []}
    by_scope = {
        scope: [row for row in rows if row["scope"] == scope]
        for scope in ("runtime", "dev", "build", "bootstrap")
    }
    for scope, scoped_rows in by_scope.items():
        checked, bad = 0, []
        for row in scoped_rows:
            wheel = args.wheelhouse_root / f"wheelhouse-{scope}" / row["wheel"]
            if not wheel.is_file():
                bad.append({"wheel": row["wheel"], "problem": "missing"})
                continue
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            checked += 1
            if digest != row["sha256"]:
                bad.append({"wheel": row["wheel"], "problem": "sha256 mismatch", "actual": digest})
        report["wheel_scopes"][scope] = {
            "manifest_entries": len(scoped_rows),
            "checked": checked,
            "problems": bad,
        }
        if bad or checked != len(scoped_rows):
            report["problems"].append(f"{scope}: retained wheel integrity failure")
        expected = {(canonical(r["package"]), r["version"]): r["sha256"] for r in scoped_rows}
        actual = lock_map(args.locks / f"{scope}.txt")
        missing_or_bad = []
        for key, digest in expected.items():
            if digest not in actual.get(key, set()):
                missing_or_bad.append(
                    {
                        "package": key[0],
                        "version": key[1],
                        "manifest_sha256": digest,
                        "lock_hashes": sorted(actual.get(key, set())),
                    }
                )
        unexpected = sorted([f"{n}=={v}" for n, v in actual if (n, v) not in expected])
        report["lock_scopes"][scope] = {
            "manifest_entries": len(expected),
            "lock_entries": len(actual),
            "missing_or_bad": missing_or_bad,
            "unexpected": unexpected,
            "match": not missing_or_bad and not unexpected and len(actual) == len(expected),
        }
        if not report["lock_scopes"][scope]["match"]:
            report["problems"].append(f"{scope}: candidate lock differs from retained manifest")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(bool(report["problems"]))


if __name__ == "__main__":
    raise SystemExit(main())
