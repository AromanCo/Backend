"""Compare two provisional Backend wheel builds and fail closed on differences."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from provisional_safety import validate_evidence_path


def _wheel_in(directory: Path) -> Path:
    wheels = sorted(directory.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"expected exactly one wheel in {directory}, found {len(wheels)}")
    return wheels[0]


def compare(run1: Path, run2: Path, evidence: Path) -> int:
    """Write comparison evidence and return nonzero unless builds are identical."""
    output = validate_evidence_path(evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {
        "run1_directory": str(run1),
        "run2_directory": str(run2),
        "passed": False,
        "errors": [],
    }
    try:
        wheel1 = _wheel_in(run1)
        wheel2 = _wheel_in(run2)
        bytes1, bytes2 = wheel1.read_bytes(), wheel2.read_bytes()
        sha1, sha2 = hashlib.sha256(bytes1).hexdigest(), hashlib.sha256(bytes2).hexdigest()
        result.update(
            {
                "run1_wheel": wheel1.name,
                "run2_wheel": wheel2.name,
                "run1_sha256": sha1,
                "run2_sha256": sha2,
                "sha256_equal": sha1 == sha2,
                "byte_identical": bytes1 == bytes2,
            }
        )

        members: list[dict[str, object]] = []
        try:
            with ZipFile(wheel1) as archive1, ZipFile(wheel2) as archive2:
                names1, names2 = sorted(archive1.namelist()), sorted(archive2.namelist())
                for name in sorted(set(names1) | set(names2)):
                    if name not in names1 or name not in names2:
                        members.append(
                            {
                                "name": name,
                                "run1_present": name in names1,
                                "run2_present": name in names2,
                            }
                        )
                        continue
                    info1, info2 = archive1.getinfo(name), archive2.getinfo(name)
                    content1, content2 = archive1.read(name), archive2.read(name)
                    if (
                        info1.date_time != info2.date_time
                        or content1 != content2
                        or info1.compress_type != info2.compress_type
                    ):
                        members.append(
                            {
                                "name": name,
                                "timestamp_run1": info1.date_time,
                                "timestamp_run2": info2.date_time,
                                "content_equal": content1 == content2,
                                "content_sha256_run1": hashlib.sha256(content1).hexdigest(),
                                "content_sha256_run2": hashlib.sha256(content2).hexdigest(),
                                "compression_equal": info1.compress_type == info2.compress_type,
                            }
                        )
                result["member_names_equal"] = names1 == names2
                result["zip_members_equal"] = names1 == names2 and not members
                result["differing_members"] = members
        except (BadZipFile, OSError) as error:
            result["zip_diagnostic_error"] = f"{type(error).__name__}: {error}"
            result["member_names_equal"] = False
            result["zip_members_equal"] = False
            result["differing_members"] = members

        passed = bool(
            result["sha256_equal"]
            and result["byte_identical"]
            and result.get("member_names_equal")
            and result.get("zip_members_equal")
        )
        result["passed"] = passed
        result["errors"] = [] if passed else ["wheel builds are not byte-identical"]
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if passed else 1
    except Exception as error:  # Preserve diagnostics for malformed build outputs too.
        result["errors"] = [f"{type(error).__name__}: {error}"]
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run1", type=Path, required=True)
    parser.add_argument("--run2", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    return compare(args.run1, args.run2, args.evidence)


if __name__ == "__main__":
    raise SystemExit(main())
