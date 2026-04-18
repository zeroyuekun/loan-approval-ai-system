"""Guard: `make clean-soft` must exist and must NOT delete Docker volumes.

The old `make clean` ran `docker compose down -v` which nuked the Postgres
volume along with caches/build output. That's fine for a fresh start but
devastating when a developer just wants to drop Python caches. D6 adds
`clean-soft` as the non-destructive default and keeps `clean` for the
full wipe.

This test locks in the split so a future refactor doesn't accidentally
re-introduce volume deletion into the soft-clean path.
"""

from pathlib import Path

import pytest


def _makefile_path() -> Path:
    return Path(__file__).resolve().parents[2] / "Makefile"


def _makefile_text() -> str:
    path = _makefile_path()
    if not path.is_file():
        pytest.skip(f"Makefile not mounted at {path} (CI runs from host; Docker exec skips)")
    return path.read_text(encoding="utf-8")


def _target_body(text: str, target: str) -> str:
    """Return the recipe lines for *target* (lines until the next non-indented line)."""
    lines = text.splitlines()
    body: list[str] = []
    in_target = False
    for line in lines:
        if line.startswith(f"{target}:"):
            in_target = True
            continue
        if in_target:
            if line.startswith("\t") or line.strip() == "" or line.startswith(" "):
                body.append(line)
            else:
                break
    return "\n".join(body)


def test_clean_soft_target_exists():
    text = _makefile_text()
    assert "clean-soft:" in text, "make clean-soft must exist (D6)"


def test_clean_soft_does_not_delete_volumes():
    body = _target_body(_makefile_text(), "clean-soft")
    assert "down -v" not in body, "clean-soft must NOT run `docker compose down -v` — that nukes the DB"
    assert "docker volume rm" not in body, "clean-soft must not remove docker volumes"


def test_clean_still_wipes_volumes():
    """Full wipe stays available under `make clean`."""
    body = _target_body(_makefile_text(), "clean")
    assert "down -v" in body, "`make clean` should still perform the full wipe"


def test_phony_declaration_includes_clean_soft():
    text = _makefile_text()
    phony_lines = [ln for ln in text.splitlines() if ln.startswith(".PHONY:")]
    phony_targets = " ".join(phony_lines)
    assert "clean-soft" in phony_targets, "clean-soft must appear in .PHONY"
