import re
from pathlib import Path

LOCK_ROOT = Path(__file__).parents[1] / "requirements/locks/provisional-ubuntu-24.04.5-x86_64-cp312"


def parsed(path):
    entries = {}
    for line in path.read_text().splitlines():
        value = line.strip()
        if not value or value.startswith("#") or value.startswith("--"):
            continue
        if "==" in value:
            spec = value.split()[0].rstrip("\\")
            name, version = spec.split("==", 1)
            entries[re.sub(r"[-_.]+", "-", name.split("[", 1)[0]).lower()] = version
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
            if re.match(r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?==[^\s\\]+", line):
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
