"""Tests for the file-size quality-bar checker."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


CHECKER = Path(__file__).resolve().parents[1] / "check_file_sizes.py"


def _run(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _write_allowlist(root: Path, packages: dict, global_cap: int = 500) -> None:
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "file_size_allowlist.json").write_text(
        json.dumps({"global_cap": global_cap, "packages": packages})
    )


def test_passes_when_all_files_under_global_cap(tmp_path):
    pkg = tmp_path / "backend" / "apps" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "tiny.py").write_text('"""doc."""\nx = 1\n')
    _write_allowlist(tmp_path, {"backend/apps/demo": {"files": {}}})

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_fails_when_file_exceeds_global_cap(tmp_path):
    pkg = tmp_path / "backend" / "apps" / "demo"
    pkg.mkdir(parents=True)
    body = '"""doc."""\n' + "\n".join(f"x_{i} = {i}" for i in range(600))
    (pkg / "big.py").write_text(body)
    _write_allowlist(tmp_path, {"backend/apps/demo": {"files": {}}})

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "big.py" in result.stdout
    assert "500" in result.stdout


def test_allowlisted_file_passes_at_its_cap(tmp_path):
    pkg = tmp_path / "backend" / "apps" / "demo"
    pkg.mkdir(parents=True)
    body = '"""doc."""\n' + "\n".join(f"x_{i} = {i}" for i in range(599))
    (pkg / "legacy.py").write_text(body)
    _write_allowlist(tmp_path, {"backend/apps/demo": {"files": {"legacy.py": 600}}})

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_allowlisted_file_fails_when_it_grows_past_its_cap(tmp_path):
    pkg = tmp_path / "backend" / "apps" / "demo"
    pkg.mkdir(parents=True)
    body = '"""doc."""\n' + "\n".join(f"x_{i} = {i}" for i in range(700))
    (pkg / "drift.py").write_text(body)
    _write_allowlist(tmp_path, {"backend/apps/demo": {"files": {"drift.py": 600}}})

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "drift.py" in result.stdout


def test_init_files_and_migrations_are_exempt(tmp_path):
    pkg = tmp_path / "backend" / "apps" / "demo"
    (pkg / "migrations").mkdir(parents=True)
    (pkg / "__init__.py").write_text("x = 1\n" * 600)
    (pkg / "migrations" / "0001_initial.py").write_text("y = 1\n" * 600)
    _write_allowlist(tmp_path, {"backend/apps/demo": {"files": {}}})

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_allowlist_file_is_a_clear_error(tmp_path):
    result = _run(tmp_path)

    assert result.returncode != 0
    assert "file_size_allowlist.json" in (result.stdout + result.stderr)


def test_module_docstring_missing_is_flagged(tmp_path):
    pkg = tmp_path / "backend" / "apps" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "no_docstring.py").write_text("x = 1\n")
    _write_allowlist(tmp_path, {"backend/apps/demo": {"files": {}}})

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "no_docstring.py" in result.stdout
    assert "docstring" in result.stdout.lower()
