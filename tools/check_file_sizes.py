"""File-size + single-responsibility quality-bar checker.

Walks every package listed in `tools/file_size_allowlist.json`, counts LOC
per Python file, and fails the build if any file exceeds its recorded cap.
Also verifies every module starts with a non-empty docstring.

Usage:
    python tools/check_file_sizes.py

Exit codes:
    0 — all files under cap AND have module docstrings
    1 — one or more violations (printed to stdout)
    2 — configuration error (allowlist missing or malformed)
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

EXEMPT_FILENAMES = {"__init__.py"}
EXEMPT_DIR_SEGMENTS = {"migrations", "__pycache__", "tests"}


def _iter_python_files(pkg_root: Path):
    for path in sorted(pkg_root.rglob("*.py")):
        if path.name in EXEMPT_FILENAMES:
            continue
        rel_parts = path.relative_to(pkg_root).parts
        if any(seg in EXEMPT_DIR_SEGMENTS for seg in rel_parts):
            continue
        yield path


def _count_lines(path: Path) -> int:
    return sum(1 for _ in path.read_text(encoding="utf-8").splitlines())


def _has_module_docstring(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    if not tree.body:
        return False
    first = tree.body[0]
    if not isinstance(first, ast.Expr):
        return False
    if not isinstance(first.value, ast.Constant):
        return False
    return isinstance(first.value.value, str) and bool(first.value.value.strip())


def main() -> int:
    root = Path.cwd()
    allowlist_path = root / "tools" / "file_size_allowlist.json"
    if not allowlist_path.exists():
        print(
            f"ERROR: allowlist missing at tools/file_size_allowlist.json ({allowlist_path})",
            file=sys.stderr,
        )
        return 2
    try:
        config = json.loads(allowlist_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: allowlist is not valid JSON: {exc}", file=sys.stderr)
        return 2

    global_cap = int(config.get("global_cap", 500))
    violations: list[str] = []

    for pkg_relpath, pkg_cfg in config.get("packages", {}).items():
        pkg_root = root / pkg_relpath
        if not pkg_root.is_dir():
            violations.append(f"CONFIG: package missing: {pkg_relpath}")
            continue
        per_file_caps = pkg_cfg.get("files", {})
        for path in _iter_python_files(pkg_root):
            rel_in_pkg = path.relative_to(pkg_root).as_posix()
            cap = int(per_file_caps.get(rel_in_pkg, global_cap))
            loc = _count_lines(path)
            if loc > cap:
                violations.append(
                    f"SIZE: {pkg_relpath}/{rel_in_pkg}: {loc} LOC exceeds cap {cap}"
                )
            if not _has_module_docstring(path):
                violations.append(
                    f"DOCSTRING: {pkg_relpath}/{rel_in_pkg}: missing module docstring"
                )

    if violations:
        print("Quality-bar check FAILED:")
        for v in violations:
            print(f"  - {v}")
        print()
        print(
            "To fix a SIZE violation: split the file, or (if genuinely cohesive) "
            "raise its entry in tools/file_size_allowlist.json and document in the PR."
        )
        return 1

    print("Quality-bar check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
