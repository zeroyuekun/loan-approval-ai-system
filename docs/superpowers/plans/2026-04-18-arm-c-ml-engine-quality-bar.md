# Arm C — ml_engine/services/ Quality Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-04-18-arm-c-ml-engine-quality-bar-design.md`

**Goal:** Install a ≤500-LOC quality bar enforced via CI on `backend/apps/ml_engine/services/`, then refactor the 6 hot-path god-modules so each file sits below the bar with a single responsibility and its own test module.

**Architecture:** A custom CI check (`tools/check_file_sizes.py`) walks the services package, reads a machine-readable allowlist, and fails the build when any file exceeds its recorded cap. Each refactor phase is an atomic PR that extracts one file into focused sub-modules (keeping re-exports for backward compatibility) and removes that file from the allowlist. Shadow-verification tests (deleted on merge) guarantee byte-identical outputs on the hot path before and after each split.

**Tech Stack:** Python 3.12, Django 5, pytest, pytest-cov, ruff, GitHub Actions, pre-commit, XGBoost, scikit-learn, pandas.

**Baseline (2026-04-18, master at `4f8b13f`):** 16,470 LOC across 23 files in `backend/apps/ml_engine/services/`. Over-bar inventory (10 files):

| File | LOC |
|------|-----|
| data_generator.py | 1,551 |
| real_world_benchmarks.py | 1,378 |
| trainer.py | 1,316 |
| predictor.py | 1,209 |
| metrics.py | 1,010 |
| underwriting_engine.py | 1,001 |
| property_data_service.py | 765 |
| macro_data_service.py | 579 |
| calibration_validator.py | 536 |
| credit_bureau_service.py | 506 |

**Branch strategy:** Each phase is one PR. Phase 0 merges first; subsequent phases can land in any order, though the recommended order is P0 (Phase 1-2) → P1 (Phase 3-4) → P2 (Phase 5-6) → P3 (Phase 7).

---

## Phase 0 — Quality Bar + CI Check

Installs the enforcement without refactoring any source file. Initial allowlist records current LOC as each file's ceiling. Ships in a single small PR.

### Task 0.1: File-size checker

**Files:**
- Create: `tools/check_file_sizes.py`
- Create: `tools/file_size_allowlist.json`

- [ ] **Step 1: Create the allowlist JSON**

Write `tools/file_size_allowlist.json`:

```json
{
  "$comment": "Cap per file in LOC (blank-line + comment-inclusive). Files not listed default to the global cap of 500. Each phase-PR deletes its target from this map. See docs/superpowers/specs/2026-04-18-arm-c-ml-engine-quality-bar-design.md.",
  "global_cap": 500,
  "packages": {
    "backend/apps/ml_engine/services": {
      "files": {
        "data_generator.py": 1551,
        "real_world_benchmarks.py": 1378,
        "trainer.py": 1316,
        "predictor.py": 1209,
        "metrics.py": 1010,
        "underwriting_engine.py": 1001,
        "property_data_service.py": 765,
        "macro_data_service.py": 579,
        "calibration_validator.py": 536,
        "credit_bureau_service.py": 506
      }
    }
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `tools/tests/test_check_file_sizes.py`:

```python
"""Tests for the file-size quality-bar checker."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


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
    (pkg / "tiny.py").write_text("x = 1\n")
    _write_allowlist(tmp_path, {"backend/apps/demo": {"files": {}}})

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_fails_when_file_exceeds_global_cap(tmp_path):
    pkg = tmp_path / "backend" / "apps" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "big.py").write_text("\n".join(f"x_{i} = {i}" for i in range(600)))
    _write_allowlist(tmp_path, {"backend/apps/demo": {"files": {}}})

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "big.py" in result.stdout
    assert "500" in result.stdout


def test_allowlisted_file_passes_at_its_cap(tmp_path):
    pkg = tmp_path / "backend" / "apps" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "legacy.py").write_text("\n".join(f"x_{i} = {i}" for i in range(600)))
    _write_allowlist(tmp_path, {"backend/apps/demo": {"files": {"legacy.py": 600}}})

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_allowlisted_file_fails_when_it_grows_past_its_cap(tmp_path):
    pkg = tmp_path / "backend" / "apps" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "drift.py").write_text("\n".join(f"x_{i} = {i}" for i in range(700)))
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
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `python -m pytest tools/tests/test_check_file_sizes.py -v`
Expected: all tests FAIL (checker doesn't exist yet).

- [ ] **Step 4: Implement the checker**

Create `tools/check_file_sizes.py`:

```python
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
        if any(seg in EXEMPT_DIR_SEGMENTS for seg in path.relative_to(pkg_root).parts):
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
        print(f"ERROR: allowlist missing at {allowlist_path}", file=sys.stderr)
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
```

- [ ] **Step 5: Run tests, verify green**

Run: `python -m pytest tools/tests/test_check_file_sizes.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 6: Run against the real repo**

Run: `python tools/check_file_sizes.py`
Expected: prints `Quality-bar check passed.` and exits 0 (allowlist covers all current offenders).

- [ ] **Step 7: Smoke-test the failure path**

Temporarily bump `data_generator.py`'s cap in the allowlist down to `1000`. Re-run `python tools/check_file_sizes.py`. Expected: exit 1, message mentions `data_generator.py: 1551 LOC exceeds cap 1000`. Revert the allowlist change.

- [ ] **Step 8: Commit Task 0.1**

```bash
git add tools/check_file_sizes.py tools/file_size_allowlist.json tools/tests/test_check_file_sizes.py
git commit -m "build(arm-c): add ml_engine/services quality-bar checker + initial allowlist"
```

### Task 0.2: CI workflow integration

**Files:**
- Create or Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Inspect existing CI workflow**

Run: `cat .github/workflows/ci.yml | head -60`
Identify the existing Python test job. The new check must run alongside (not inside) the pytest job so a file-size violation fails CI cleanly on its own.

- [ ] **Step 2: Add quality-bar job**

Edit `.github/workflows/ci.yml` to add a new job (exact placement depends on existing structure — add alongside the lint/ruff job):

```yaml
  quality-bar:
    name: ml_engine quality bar
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Run file-size + docstring check
        run: python tools/check_file_sizes.py
```

- [ ] **Step 3: Commit Task 0.2**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(arm-c): add quality-bar job to enforce ml_engine/services file caps"
```

### Task 0.3: Pre-commit hook

**Files:**
- Modify: `.pre-commit-config.yaml`

- [ ] **Step 1: Inspect existing hooks**

Run: `cat .pre-commit-config.yaml`
Identify the `repos:` key and the `local` repo entry (if any).

- [ ] **Step 2: Add local hook entry**

Append to `.pre-commit-config.yaml` (under `repos:` → `local` — create the `local` repo block if absent):

```yaml
  - repo: local
    hooks:
      - id: ml-engine-quality-bar
        name: ml_engine/services quality bar
        entry: python tools/check_file_sizes.py
        language: system
        pass_filenames: false
        always_run: true
        stages: [pre-commit]
```

- [ ] **Step 3: Test the hook**

Run: `pre-commit run ml-engine-quality-bar --all-files`
Expected: passes, prints `Quality-bar check passed.`

- [ ] **Step 4: Commit Task 0.3**

```bash
git add .pre-commit-config.yaml
git commit -m "ci(arm-c): wire quality-bar into pre-commit hooks"
```

### Task 0.4: Open Phase 0 PR

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin arm-c/ml-engine-quality-bar
gh pr create --base master --title "arm-c phase 0: ml_engine/services quality bar + CI check" --body "$(cat <<'EOF'
## Summary
- Adds `tools/check_file_sizes.py` — walks configured packages, enforces LOC cap + module docstring presence, reads a per-file allowlist for current offenders
- Seeds `tools/file_size_allowlist.json` with the 10 files currently above the 500-LOC global cap (caps = their current LOC)
- Wires the checker into `.github/workflows/ci.yml` as a standalone job and into `.pre-commit-config.yaml`
- Zero refactoring in this PR — subsequent Arm C phases shrink the allowlist as each target file is split

## Spec
`docs/superpowers/specs/2026-04-18-arm-c-ml-engine-quality-bar-design.md`

## Test plan
- [x] `pytest tools/tests/test_check_file_sizes.py -v` all 7 tests pass
- [x] `python tools/check_file_sizes.py` against real repo returns 0
- [x] Manual smoke: temporarily lowered `data_generator.py` cap, confirmed CI-style failure, reverted
- [ ] CI run on this PR is green
- [ ] Pre-commit hook fires on a local commit without issue

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Wait for CI**

Run: `gh pr checks --watch` until all green.
Expected: all checks pass.

- [ ] **Step 3: Merge Phase 0**

Ask user for explicit merge approval (per `feedback_master_push_requires_auth`). On approval:

```bash
gh pr merge --merge --delete-branch
git checkout master && git pull
```

---

## Phase 1 — `predictor.py` split (P0)

Extracts 3 modules from the 1,209-LOC file. `ModelPredictor.predict()` currently spans 414-871 (457 LOC of orchestration + SHAP cache + drift + stress test + conformal + counterfactuals). Target: `predictor.py` ≤ 500 LOC after extraction.

**Branch:** `arm-c/phase-1-predictor-split` off master (post Phase 0).

### Task 1.1: Baseline + shadow-verification test

**Files:**
- Create: `backend/apps/ml_engine/tests/test_predictor_shadow.py` (deleted on merge)
- Create: `backend/apps/ml_engine/tests/fixtures/predictor_golden.json`

- [ ] **Step 1: Capture golden output**

Run a fixture application through the current `ModelPredictor.predict()` and serialise the response dict to `predictor_golden.json`. Use a Django management shell:

```bash
cd backend && python manage.py shell <<'EOF'
import json
from pathlib import Path
from apps.ml_engine.services.predictor import ModelPredictor
from apps.loans.models import LoanApplication

# Pick the most recent application with a complete feature set
app = LoanApplication.objects.filter(status__in=["approved", "denied"]).order_by("-id").first()
if app is None:
    raise SystemExit("no application available for golden fixture")

predictor = ModelPredictor.for_application(app)
result = predictor.predict(app)

# Strip non-deterministic fields (timestamps, request IDs) if any
result_clean = {k: v for k, v in result.items() if k not in {"timestamp", "request_id"}}

fixtures = Path("apps/ml_engine/tests/fixtures")
fixtures.mkdir(parents=True, exist_ok=True)
(fixtures / "predictor_golden.json").write_text(json.dumps({
    "application_id": app.id,
    "result": result_clean,
}, default=str, indent=2))
print(f"wrote fixture for application {app.id}")
EOF
```

- [ ] **Step 2: Write the shadow test**

Create `backend/apps/ml_engine/tests/test_predictor_shadow.py`:

```python
"""Shadow-verification test for Phase 1 predictor.py refactor.

DELETE THIS FILE ON MERGE — it exists only as a gate for the refactor PR.
It asserts that post-refactor ModelPredictor.predict() produces an identical
response dict to the pre-refactor golden capture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.loans.models import LoanApplication
from apps.ml_engine.services.predictor import ModelPredictor

GOLDEN = Path(__file__).parent / "fixtures" / "predictor_golden.json"


@pytest.mark.django_db
def test_predictor_output_matches_golden():
    assert GOLDEN.exists(), "capture the golden fixture first (see plan Task 1.1 Step 1)"
    snap = json.loads(GOLDEN.read_text())
    app = LoanApplication.objects.get(pk=snap["application_id"])

    predictor = ModelPredictor.for_application(app)
    result = predictor.predict(app)
    result_clean = {k: v for k, v in result.items() if k not in {"timestamp", "request_id"}}

    expected = snap["result"]
    assert result_clean == expected, (
        "predictor output drifted vs golden fixture — the refactor changed behaviour. "
        "Either revert the change, or (if the drift is intended) regenerate the fixture "
        "AND document the drift in the PR description."
    )
```

- [ ] **Step 3: Run the shadow test, verify green**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_predictor_shadow.py -v`
Expected: PASS (we haven't refactored anything yet, so output matches).

- [ ] **Step 4: Commit Task 1.1**

```bash
git add backend/apps/ml_engine/tests/test_predictor_shadow.py backend/apps/ml_engine/tests/fixtures/predictor_golden.json
git commit -m "test(arm-c): predictor shadow-verification fixture for phase 1 refactor"
```

### Task 1.2: Extract `policy_recompute.py`

The `_recompute_lvr_driven_policy_vars` function at predictor.py:123-160 is already a free function and the easiest extraction — does not depend on `self`.

**Files:**
- Create: `backend/apps/ml_engine/services/policy_recompute.py`
- Create: `backend/apps/ml_engine/tests/test_policy_recompute.py`
- Modify: `backend/apps/ml_engine/services/predictor.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/ml_engine/tests/test_policy_recompute.py`:

```python
"""Unit tests for the LVR-driven policy recompute helper.

Verifies that LVR and LTI policy variables are recomputed consistently from the
underlying loan/property/income fields, with the 5.2M loan ceiling applied.
"""

from __future__ import annotations

import pytest

from apps.ml_engine.services.policy_recompute import recompute_lvr_driven_policy_vars


def test_recompute_lvr_from_loan_and_property():
    row = {"loan_amount": 400_000, "property_value": 500_000, "annual_income": 100_000}
    result = recompute_lvr_driven_policy_vars(row)
    assert result["lvr"] == pytest.approx(0.80, abs=1e-6)


def test_recompute_lti_from_loan_and_income():
    row = {"loan_amount": 600_000, "property_value": 750_000, "annual_income": 120_000}
    result = recompute_lvr_driven_policy_vars(row)
    assert result["loan_to_income"] == pytest.approx(5.0, abs=1e-6)


def test_loan_ceiling_applied_at_5_2m():
    row = {"loan_amount": 7_000_000, "property_value": 10_000_000, "annual_income": 500_000}
    result = recompute_lvr_driven_policy_vars(row)
    assert result["effective_loan_amount"] == 5_200_000


def test_missing_property_returns_none_lvr():
    row = {"loan_amount": 50_000, "property_value": None, "annual_income": 80_000}
    result = recompute_lvr_driven_policy_vars(row)
    assert result["lvr"] is None or result["lvr"] == 0
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_policy_recompute.py -v`
Expected: FAIL with ImportError (module doesn't exist).

- [ ] **Step 3: Create the module by copying lines 123-160 from predictor.py**

First read the current content:

```bash
sed -n '123,160p' backend/apps/ml_engine/services/predictor.py
```

Create `backend/apps/ml_engine/services/policy_recompute.py`:

```python
"""Policy-variable recomputation for LVR-driven fields.

When a caller submits an application, the LVR / LTI / effective-loan-amount
fields must be recomputed from the raw inputs to guarantee consistency with
the underwriting engine's policy gates — we can't trust client-supplied values
for gate-critical variables.

Extracted from predictor.py (Arm C Phase 1) so the predictor orchestrator
stays focused on model invocation rather than policy arithmetic.
"""

from __future__ import annotations

__all__ = ["recompute_lvr_driven_policy_vars"]

LOAN_AMOUNT_CEILING = 5_200_000


def recompute_lvr_driven_policy_vars(row: dict) -> dict:
    """Return the subset of `row` fields that LVR / LTI / loan ceiling drives.

    The caller is expected to merge these back into its own feature dict.
    """
    # [MOVE BODY FROM predictor.py:123-160 HERE, verbatim, adjusting the
    #  signature from `_recompute_lvr_driven_policy_vars(row)` to the
    #  public `recompute_lvr_driven_policy_vars(row)` and ensuring the
    #  loan-ceiling constant is referenced as LOAN_AMOUNT_CEILING.]
    ...
```

Note: the `[MOVE BODY FROM ... HERE]` marker indicates an exact-copy step. The implementing agent must paste the lines verbatim without rewording.

- [ ] **Step 4: Run test to verify pass**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_policy_recompute.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Update `predictor.py` to use the extracted module**

Edit `backend/apps/ml_engine/services/predictor.py`:

1. Remove the `_recompute_lvr_driven_policy_vars` function body (lines 123-160).
2. Replace with a backward-compat import at the top of the file (right after other imports):

```python
from apps.ml_engine.services.policy_recompute import (
    recompute_lvr_driven_policy_vars as _recompute_lvr_driven_policy_vars,
)
```

The `as _recompute_lvr_driven_policy_vars` alias preserves the underscore-prefixed name for any in-module callers that use it.

- [ ] **Step 6: Run shadow test + full ml_engine suite**

Run:
```bash
cd backend && python -m pytest apps/ml_engine/tests/test_predictor_shadow.py apps/ml_engine/tests/ -v
```
Expected: all tests PASS, shadow test PASS.

- [ ] **Step 7: Commit Task 1.2**

```bash
git add backend/apps/ml_engine/services/policy_recompute.py backend/apps/ml_engine/services/predictor.py backend/apps/ml_engine/tests/test_policy_recompute.py
git commit -m "refactor(arm-c): extract policy_recompute.py from predictor.py"
```

### Task 1.3: Extract `feature_prep.py`

Target: the `_add_derived_features`, `_safe_get_state`, `_validate_input`, and `_transform` methods on `ModelPredictor` (lines 306-414) plus the input-validation + feature-dict-assembly portion of `predict()` (lines 414-~500). These form a cohesive "take an application, produce a model-ready feature DataFrame" unit.

**Files:**
- Create: `backend/apps/ml_engine/services/feature_prep.py`
- Create: `backend/apps/ml_engine/tests/test_feature_prep.py`
- Modify: `backend/apps/ml_engine/services/predictor.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/ml_engine/tests/test_feature_prep.py`:

```python
"""Unit tests for feature-prep: application → model-ready DataFrame."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.ml_engine.services.feature_prep import (
    ApplicationValidationError,
    prepare_features_for_prediction,
    safe_get_state,
    validate_input,
)


def test_safe_get_state_returns_string_when_present():
    class _App:
        state = "NSW"
    assert safe_get_state(_App()) == "NSW"


def test_safe_get_state_returns_default_when_missing():
    class _App:
        pass
    assert safe_get_state(_App()) == "NSW"  # documented default


def test_validate_input_rejects_negative_income():
    with pytest.raises(ApplicationValidationError, match="annual_income"):
        validate_input({"annual_income": -1000, "loan_amount": 50_000, "credit_score": 700})


def test_validate_input_rejects_credit_score_out_of_range():
    with pytest.raises(ApplicationValidationError, match="credit_score"):
        validate_input({"annual_income": 80_000, "loan_amount": 50_000, "credit_score": 2000})


def test_prepare_features_returns_dataframe_with_expected_cols():
    features = {
        "annual_income": 80_000,
        "credit_score": 750,
        "loan_amount": 50_000,
        "loan_term_months": 36,
        "debt_to_income": 2.0,
        "employment_length": 5,
        "purpose": "personal",
        "home_ownership": "rent",
        "has_cosigner": 0,
        "number_of_dependants": 1,
        "employment_type": "payg_permanent",
        "applicant_type": "single",
        "has_hecs": 0,
        "has_bankruptcy": 0,
        "state": "NSW",
    }
    # imputation_values + feature_cols are what ModelPredictor.predict passes in
    imputation_values = {
        "monthly_expenses": 3000,
        "property_value": 0,
        "deposit_amount": 0,
        "existing_credit_card_limit": 0,
        "savings_balance": 10_000,
        "rba_cash_rate": 4.35,
        "document_consistency_score": 1.0,
    }
    feature_cols = list(features.keys()) + list(imputation_values.keys()) + ["lvr", "loan_to_income"]

    df = prepare_features_for_prediction(features, imputation_values=imputation_values, feature_cols=feature_cols)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert "lvr" in df.columns
    assert "loan_to_income" in df.columns
    assert not df.isna().any().any()
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_feature_prep.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Create `feature_prep.py`**

Read the current methods from `predictor.py`:

```bash
sed -n '306,414p' backend/apps/ml_engine/services/predictor.py
```

Create `backend/apps/ml_engine/services/feature_prep.py`:

```python
"""Feature preparation: loan application → model-ready pandas DataFrame.

Handles three responsibilities, kept together because they share the same
in-memory feature dict:

1. Input validation — reject obviously invalid values (negative income,
   out-of-range credit scores, impossible term lengths) before they reach
   the model.
2. Derived-feature computation — call the trainer's `add_derived_features`
   on the per-applicant row so the row carries LVR, LTI, etc.
3. DataFrame construction + imputation — build the exact-column,
   exact-order frame that `ModelPredictor._transform` expects.

Extracted from predictor.py (Arm C Phase 1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "ApplicationValidationError",
    "prepare_features_for_prediction",
    "safe_get_state",
    "validate_input",
]


class ApplicationValidationError(ValueError):
    """Raised when an application's feature values fail basic sanity checks."""


def safe_get_state(application) -> str:
    """Return the application's state, defaulting to NSW if absent."""
    # [MOVE BODY FROM predictor.py:317-326 HERE; remove the `self` parameter,
    #  keep logic identical.]
    ...


def validate_input(features: dict) -> None:
    """Raise ApplicationValidationError if any feature value fails sanity checks."""
    # [MOVE BODY FROM predictor.py:327-361 HERE; remove `self`, raise
    #  ApplicationValidationError instead of returning bool / adding to a list.]
    ...


def _add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-row derived features (LVR, LTI, DTI interactions, ...)."""
    # [MOVE BODY FROM predictor.py:306-316 HERE; remove `self`.]
    ...


def prepare_features_for_prediction(
    features: dict,
    *,
    imputation_values: dict,
    feature_cols: list[str],
) -> pd.DataFrame:
    """One-call entry point: validate → DataFrame → derive → impute → align columns."""
    validate_input(features)
    df = pd.DataFrame([features])
    df = _add_derived_features(df)
    for col, default in imputation_values.items():
        if col not in df.columns:
            df[col] = default
        else:
            df[col] = df[col].fillna(default)
    for col in feature_cols:
        if col not in df.columns:
            df[col] = 0
    return df[feature_cols]
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_feature_prep.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Update `ModelPredictor` to delegate**

Edit `backend/apps/ml_engine/services/predictor.py`:

1. Remove the extracted methods (`_add_derived_features`, `_safe_get_state`, `_validate_input`, and inline them via imports).
2. Add at the top of the file:

```python
from apps.ml_engine.services.feature_prep import (
    ApplicationValidationError,
    prepare_features_for_prediction,
    safe_get_state as _safe_get_state,
    validate_input as _validate_input,
)
```

3. Update `ModelPredictor.predict()` to call `prepare_features_for_prediction(features, imputation_values=self._imputation_values, feature_cols=self._feature_cols)` in place of the inline DataFrame-building block. Keep the rest of `predict()` (model invocation, SHAP, drift, stress, conformal, counterfactuals) unchanged.

- [ ] **Step 6: Run shadow test + ml_engine suite**

Run:
```bash
cd backend && python -m pytest apps/ml_engine/tests/ -v
```
Expected: all tests PASS including the shadow test (byte-identical output).

- [ ] **Step 7: Commit Task 1.3**

```bash
git add backend/apps/ml_engine/services/feature_prep.py backend/apps/ml_engine/services/predictor.py backend/apps/ml_engine/tests/test_feature_prep.py
git commit -m "refactor(arm-c): extract feature_prep.py from predictor.py"
```

### Task 1.4: Extract `prediction_cache.py`

Target: the module-level `_load_bundle`, `_verify_model_hash`, `_validate_model_path`, `clear_model_cache` functions (lines 161-218) plus the in-class SHAP-cache machinery used inside `predict()`.

**Files:**
- Create: `backend/apps/ml_engine/services/prediction_cache.py`
- Create: `backend/apps/ml_engine/tests/test_prediction_cache.py`
- Modify: `backend/apps/ml_engine/services/predictor.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/ml_engine/tests/test_prediction_cache.py`:

```python
"""Unit tests for the model-bundle + SHAP cache."""

from __future__ import annotations

import hashlib
from pathlib import Path

import joblib
import pytest

from apps.ml_engine.services.prediction_cache import (
    ModelBundleNotFoundError,
    ModelHashMismatchError,
    clear_model_cache,
    load_bundle,
    validate_model_path,
    verify_model_hash,
)


def test_validate_model_path_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match="path traversal"):
        validate_model_path("../../../etc/passwd")


def test_validate_model_path_accepts_within_ml_models(tmp_path, monkeypatch):
    ml_models = tmp_path / "ml_models"
    ml_models.mkdir()
    (ml_models / "model.joblib").write_bytes(b"x")
    monkeypatch.setenv("ML_MODELS_DIR", str(ml_models))
    # Shouldn't raise
    validate_model_path(str(ml_models / "model.joblib"))


def test_verify_model_hash_passes_on_match(tmp_path):
    p = tmp_path / "model.joblib"
    p.write_bytes(b"artefact")
    expected = hashlib.sha256(b"artefact").hexdigest()
    verify_model_hash(str(p), expected)


def test_verify_model_hash_raises_on_mismatch(tmp_path):
    p = tmp_path / "model.joblib"
    p.write_bytes(b"artefact")
    with pytest.raises(ModelHashMismatchError):
        verify_model_hash(str(p), "0" * 64)


def test_load_bundle_caches_by_version(tmp_path):
    clear_model_cache()

    class _FakeVersion:
        id = "v1"
        model_path = str(tmp_path / "model.joblib")
        model_hash = hashlib.sha256(b"x").hexdigest()

    (tmp_path / "model.joblib").write_bytes(b"x")
    # Monkey-patch joblib.load via a tiny stub — the cache should still dedupe
    calls = []
    orig_load = joblib.load

    def _patched(path):
        calls.append(path)
        return {"model": "stub", "feature_cols": [], "imputation_values": {}, "scaler": None}

    joblib.load = _patched
    try:
        load_bundle(_FakeVersion())
        load_bundle(_FakeVersion())
    finally:
        joblib.load = orig_load

    assert len(calls) == 1, "bundle should be cached after first load"
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_prediction_cache.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Create `prediction_cache.py`**

Read current lines:

```bash
sed -n '161,218p' backend/apps/ml_engine/services/predictor.py
```

Create `backend/apps/ml_engine/services/prediction_cache.py`:

```python
"""Model-bundle loading, hash verification, and SHAP explainer caching.

The active model bundle (XGBoost + preprocessing scaler + feature columns +
imputation defaults) is expensive to deserialise on every request, so we
cache it keyed by ModelVersion.id. The cache is cleared on model activation
change via a Django signal in apps.ml_engine.signals.

Hash verification is defence-in-depth against on-disk model-artefact
tampering — production should only load artefacts whose SHA-256 matches
what was recorded at training time.

Extracted from predictor.py (Arm C Phase 1).
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

import joblib

__all__ = [
    "ModelBundleNotFoundError",
    "ModelHashMismatchError",
    "clear_model_cache",
    "load_bundle",
    "validate_model_path",
    "verify_model_hash",
]


log = logging.getLogger("ml_engine.prediction_cache")

_bundle_cache: dict[str, dict] = {}
_bundle_cache_lock = threading.Lock()


class ModelBundleNotFoundError(FileNotFoundError):
    """Raised when the configured model_path does not resolve to an artefact on disk."""


class ModelHashMismatchError(ValueError):
    """Raised when the loaded artefact's SHA-256 does not match the recorded hash."""


def validate_model_path(file_path: str) -> None:
    """Ensure the path is inside $ML_MODELS_DIR (or repo-relative fallback)."""
    # [MOVE BODY FROM predictor.py:161-175 HERE; raise ValueError("path traversal")
    #  for traversal attempts, ModelBundleNotFoundError for missing files.]
    ...


def verify_model_hash(file_path: str, expected_hash: str) -> None:
    """SHA-256 the file on disk and compare to expected; raise on mismatch."""
    # [MOVE BODY FROM predictor.py:176-191 HERE; raise ModelHashMismatchError
    #  instead of the old in-place behaviour.]
    ...


def load_bundle(model_version) -> dict:
    """Return the joblib bundle for `model_version`, cached by id."""
    # [MOVE BODY FROM predictor.py:192-213 HERE; use _bundle_cache + lock.]
    ...


def clear_model_cache() -> None:
    """Drop all cached bundles. Called on ModelVersion activation change."""
    with _bundle_cache_lock:
        _bundle_cache.clear()
    log.info("prediction cache cleared")
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_prediction_cache.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Update `predictor.py` to delegate**

Edit `backend/apps/ml_engine/services/predictor.py`:

1. Remove the 4 module-level helpers (lines 161-218).
2. Re-export for backward compat at the top:

```python
from apps.ml_engine.services.prediction_cache import (
    clear_model_cache,
    load_bundle as _load_bundle,
    validate_model_path as _validate_model_path,
    verify_model_hash as _verify_model_hash,
)
```

3. Check `apps/ml_engine/signals.py` (it already imports `clear_model_cache`) — the import path is `from apps.ml_engine.services.predictor import clear_model_cache`; since we re-export it, the signals file still works. Consider updating to the canonical path:

```python
from apps.ml_engine.services.prediction_cache import clear_model_cache
```

- [ ] **Step 6: Run shadow test + ml_engine suite**

Run:
```bash
cd backend && python -m pytest apps/ml_engine/tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 7: Commit Task 1.4**

```bash
git add backend/apps/ml_engine/services/prediction_cache.py backend/apps/ml_engine/services/predictor.py backend/apps/ml_engine/signals.py backend/apps/ml_engine/tests/test_prediction_cache.py
git commit -m "refactor(arm-c): extract prediction_cache.py from predictor.py"
```

### Task 1.5: Verify predictor.py below 500, update allowlist, delete shadow test

- [ ] **Step 1: Measure**

Run: `wc -l backend/apps/ml_engine/services/predictor.py`
Expected: below 500. If above, examine `ModelPredictor.predict()` for further sections to extract (e.g., the SHAP post-processing section could become a helper).

- [ ] **Step 2: Update allowlist**

Edit `tools/file_size_allowlist.json` — remove the `predictor.py` entry so the default 500 cap applies.

- [ ] **Step 3: Run quality-bar check**

Run: `python tools/check_file_sizes.py`
Expected: passes (predictor.py is now below the default cap).

- [ ] **Step 4: Delete the shadow test**

```bash
rm backend/apps/ml_engine/tests/test_predictor_shadow.py
rm backend/apps/ml_engine/tests/fixtures/predictor_golden.json
```

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && python -m pytest -v`
Expected: green.

- [ ] **Step 6: Commit Task 1.5**

```bash
git add tools/file_size_allowlist.json backend/apps/ml_engine/tests/test_predictor_shadow.py backend/apps/ml_engine/tests/fixtures/predictor_golden.json
git commit -m "chore(arm-c): remove predictor.py from allowlist and delete shadow gate"
```

### Task 1.6: Open Phase 1 PR

- [ ] **Step 1: Push and open PR**

```bash
git push -u origin arm-c/phase-1-predictor-split
gh pr create --base master --title "arm-c phase 1: split predictor.py into 3 focused modules" --body "$(cat <<'EOF'
## Summary
- Extracts `policy_recompute.py` (LVR/LTI arithmetic + loan ceiling)
- Extracts `feature_prep.py` (input validation + derived features + DataFrame assembly)
- Extracts `prediction_cache.py` (bundle caching + hash verification + path validation)
- `predictor.py` now below the 500-LOC bar; removed from allowlist
- Shadow-verification test ran green (byte-identical predict() output pre- and post-refactor), then deleted

## Spec
`docs/superpowers/specs/2026-04-18-arm-c-ml-engine-quality-bar-design.md`

## Test plan
- [x] New modules each have their own test file (≥70% coverage)
- [x] Shadow test produced identical predictor output (deleted on merge)
- [x] Full ml_engine pytest suite green
- [ ] CI run green on this PR

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Merge with user approval**

Follow same approval flow as Phase 0.

---

## Phase 2 — `trainer.py` split (P0)

Branch: `arm-c/phase-2-trainer-split` off latest master.

Current `trainer.py` is 1,316 LOC. Extract:

| New module | Responsibility | Source lines (approx.) |
|------------|----------------|-------------------------|
| `preprocessing.py` | `add_derived_features`, `fit_preprocess`, `transform`, `_imputation_values` management | 232-302 |
| `hyperopt.py` | Optuna tuning loop + hyperparameter bookkeeping | portions of `train()` 508-1131 + `_compute_temporal_cv_auc` |
| `evaluation.py` | Metrics computation, confusion matrix, feature importance, calibration curve, split-strategy metadata | portions of `train()` that compute post-training metrics |
| `trainer.py` (orchestrator) | `ModelTrainer.train()`, `save_model()`, constants (NUMERIC_COLS/CATEGORICAL_COLS), `_train_rf`, `_train_xgb`, `_build_monotonic_constraints`, `_CalibratedModel` wrapper | remainder |

### Task 2.1: Baseline + shadow test

**Files:**
- Create: `backend/apps/ml_engine/tests/test_trainer_shadow.py` (deleted on merge)
- Create: `backend/apps/ml_engine/tests/fixtures/trainer_golden.json`

- [ ] **Step 1: Capture golden metrics**

```bash
cd backend && python manage.py shell <<'EOF'
import json
from pathlib import Path
from apps.ml_engine.services.data_generator import DataGenerator
from apps.ml_engine.services.trainer import ModelTrainer
import tempfile, os

gen = DataGenerator()
df = gen.generate(num_records=500, random_seed=99)
with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
    df.to_csv(tmp.name, index=False)
    csv = tmp.name

trainer = ModelTrainer()
_, metrics = trainer.train(csv, algorithm="rf", use_reject_inference=False)
os.unlink(csv)

golden = {
    "auc_roc": round(metrics["auc_roc"], 6),
    "ks_statistic": round(metrics.get("ks_statistic", 0.0), 6),
    "num_features": len(metrics["feature_importances"]),
}
Path("apps/ml_engine/tests/fixtures").mkdir(parents=True, exist_ok=True)
Path("apps/ml_engine/tests/fixtures/trainer_golden.json").write_text(json.dumps(golden, indent=2))
print(golden)
EOF
```

- [ ] **Step 2: Write shadow test**

Create `backend/apps/ml_engine/tests/test_trainer_shadow.py`:

```python
"""Shadow test for Phase 2 trainer.py refactor — DELETE ON MERGE.

Verifies that post-refactor training produces AUC/KS within ±0.002 and the
same number of features as the pre-refactor baseline.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from apps.ml_engine.services.data_generator import DataGenerator
from apps.ml_engine.services.trainer import ModelTrainer

GOLDEN = Path(__file__).parent / "fixtures" / "trainer_golden.json"


@pytest.mark.django_db
def test_trainer_produces_same_metrics_as_golden():
    assert GOLDEN.exists(), "capture golden fixture first"
    golden = json.loads(GOLDEN.read_text())

    gen = DataGenerator()
    df = gen.generate(num_records=500, random_seed=99)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        df.to_csv(tmp.name, index=False)
        csv = tmp.name

    try:
        trainer = ModelTrainer()
        _, metrics = trainer.train(csv, algorithm="rf", use_reject_inference=False)
    finally:
        os.unlink(csv)

    assert abs(metrics["auc_roc"] - golden["auc_roc"]) < 0.002
    assert abs(metrics.get("ks_statistic", 0.0) - golden["ks_statistic"]) < 0.002
    assert len(metrics["feature_importances"]) == golden["num_features"]
```

- [ ] **Step 3: Run, verify pass (baseline matches itself)**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_trainer_shadow.py -v`
Expected: PASS.

- [ ] **Step 4: Commit Task 2.1**

```bash
git add backend/apps/ml_engine/tests/test_trainer_shadow.py backend/apps/ml_engine/tests/fixtures/trainer_golden.json
git commit -m "test(arm-c): trainer shadow-verification fixture for phase 2 refactor"
```

### Task 2.2: Extract `preprocessing.py`

**Files:**
- Create: `backend/apps/ml_engine/services/preprocessing.py`
- Create: `backend/apps/ml_engine/tests/test_preprocessing.py`
- Modify: `backend/apps/ml_engine/services/trainer.py`

- [ ] **Step 1: Write failing test**

Create `backend/apps/ml_engine/tests/test_preprocessing.py`:

```python
"""Unit tests for the training preprocessing layer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.ml_engine.services.preprocessing import (
    DerivedFeaturesComputer,
    Preprocessor,
    compute_imputation_values,
)


@pytest.fixture
def minimal_df():
    return pd.DataFrame({
        "annual_income": [80_000, 120_000],
        "loan_amount": [40_000, 60_000],
        "credit_score": [750, 680],
        "loan_term_months": [36, 60],
        "debt_to_income": [2.0, 3.5],
        "employment_length": [5, 3],
        "purpose": ["personal", "home"],
        "home_ownership": ["rent", "mortgage"],
        "has_cosigner": [0, 0],
        "property_value": [np.nan, 500_000],
        "deposit_amount": [np.nan, 100_000],
        "monthly_expenses": [3000, 4500],
        "existing_credit_card_limit": [10_000, 20_000],
        "number_of_dependants": [1, 2],
        "employment_type": ["payg_permanent", "payg_permanent"],
        "applicant_type": ["single", "couple"],
        "has_hecs": [0, 1],
        "has_bankruptcy": [0, 0],
        "state": ["NSW", "VIC"],
    })


def test_derived_features_computer_adds_lvr(minimal_df):
    result = DerivedFeaturesComputer().compute(minimal_df)
    assert "lvr" in result.columns


def test_compute_imputation_values_returns_dict(minimal_df):
    imp = compute_imputation_values(minimal_df)
    assert "monthly_expenses" in imp
    assert isinstance(imp["monthly_expenses"], (int, float))


def test_preprocessor_fit_then_transform_roundtrip(minimal_df):
    pre = Preprocessor()
    pre.fit(minimal_df)
    transformed = pre.transform(minimal_df)
    assert not transformed.isna().any().any()
```

- [ ] **Step 2: Verify failure**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_preprocessing.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Create `preprocessing.py`**

Read current trainer preprocessing:

```bash
sed -n '225,302p' backend/apps/ml_engine/services/trainer.py
```

Create `backend/apps/ml_engine/services/preprocessing.py`:

```python
"""Training-time preprocessing: derived features + imputation + scaling.

Separates the "transform a raw loan DataFrame into model-ready features"
concern from the training-loop orchestration.  Used by `ModelTrainer` at
fit time and re-used by `ModelPredictor` via shared imputation values
(stored on the saved bundle).

Extracted from trainer.py (Arm C Phase 2).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

__all__ = [
    "DerivedFeaturesComputer",
    "Preprocessor",
    "compute_imputation_values",
]


class DerivedFeaturesComputer:
    """Attach per-row derived features (LVR, LTI, DTI interactions, ...) to a DataFrame."""

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        # [MOVE BODY FROM trainer.add_derived_features (lines 232-253) HERE;
        #  remove self, operate purely on df.]
        ...


def compute_imputation_values(df: pd.DataFrame) -> dict:
    """Return a dict of {column: median/default} for optional columns."""
    # [COLLECT THE medians/defaults THAT trainer._imputation_values
    #  was building in add_derived_features + fit_preprocess.]
    ...


class Preprocessor:
    """Fit-then-transform preprocessing. Owns scaler + imputation_values state."""

    def __init__(self) -> None:
        self.scaler: StandardScaler | None = None
        self.imputation_values: dict = {}
        self._derived = DerivedFeaturesComputer()

    def fit(self, df: pd.DataFrame) -> None:
        # [MOVE BODY FROM trainer.fit_preprocess (lines 254-273) HERE;
        #  store scaler and imputation_values on self.]
        ...

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        # [MOVE BODY FROM trainer.transform (lines 274-302) HERE;
        #  use self.scaler + self.imputation_values.]
        ...
```

- [ ] **Step 4: Run test, verify pass**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_preprocessing.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Update `ModelTrainer` to delegate**

In `backend/apps/ml_engine/services/trainer.py`:

1. Remove the extracted methods (`add_derived_features`, `fit_preprocess`, `transform`).
2. Add import:

```python
from apps.ml_engine.services.preprocessing import (
    DerivedFeaturesComputer,
    Preprocessor,
    compute_imputation_values,
)
```

3. In `ModelTrainer.__init__` construct `self._preprocessor = Preprocessor()`.
4. Expose `add_derived_features`, `fit_preprocess`, `transform`, and `_imputation_values` on `ModelTrainer` as thin delegations to `self._preprocessor` so external callers (and the existing test suite's `trainer.add_derived_features(df.copy())` idiom) keep working.

- [ ] **Step 6: Run shadow + backend tests**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_trainer_shadow.py tests/test_trainer_pipeline.py apps/ml_engine/tests/test_preprocessing.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit Task 2.2**

```bash
git add backend/apps/ml_engine/services/preprocessing.py backend/apps/ml_engine/services/trainer.py backend/apps/ml_engine/tests/test_preprocessing.py
git commit -m "refactor(arm-c): extract preprocessing.py from trainer.py"
```

### Task 2.3: Extract `hyperopt.py`

**Files:**
- Create: `backend/apps/ml_engine/services/hyperopt.py`
- Create: `backend/apps/ml_engine/tests/test_hyperopt.py`
- Modify: `backend/apps/ml_engine/services/trainer.py`

- [ ] **Step 1: Write failing test**

Create `backend/apps/ml_engine/tests/test_hyperopt.py`:

```python
"""Unit tests for hyperparameter tuning helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.ml_engine.services.hyperopt import (
    HyperoptBudget,
    TemporalCVScorer,
    run_xgb_hyperopt,
)


def test_hyperopt_budget_defaults_are_sane():
    budget = HyperoptBudget()
    assert budget.n_trials > 0
    assert budget.timeout_seconds > 0


def test_temporal_cv_scorer_handles_three_folds():
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(300, 5)), columns=list("abcde"))
    y = pd.Series(rng.integers(0, 2, size=300))
    quarters = pd.Series(rng.choice(["2024Q1", "2024Q2", "2024Q3", "2024Q4"], size=300))
    scorer = TemporalCVScorer(max_folds=3)
    score = scorer.score({"n_estimators": 50, "max_depth": 3}, X, y, quarters)
    assert 0.0 < score < 1.0


def test_run_xgb_hyperopt_respects_small_budget():
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(100, 4)), columns=list("abcd"))
    y = pd.Series(rng.integers(0, 2, size=100))
    best = run_xgb_hyperopt(X, y, budget=HyperoptBudget(n_trials=3, timeout_seconds=30))
    assert isinstance(best, dict)
    assert "max_depth" in best
```

- [ ] **Step 2: Verify failure**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_hyperopt.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Create `hyperopt.py`**

```python
"""Hyperparameter tuning via Optuna, with temporal CV scoring.

Isolates the Optuna-driven search from the core training loop so the
trainer orchestrator can call `run_xgb_hyperopt(...)` and pass the best
params through to `_train_xgb`.

Extracted from trainer.py (Arm C Phase 2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "HyperoptBudget",
    "TemporalCVScorer",
    "run_xgb_hyperopt",
]


@dataclass
class HyperoptBudget:
    n_trials: int = 25
    timeout_seconds: int = 600


class TemporalCVScorer:
    """Score a hyperparameter set via K-fold temporal split on quarter labels."""

    def __init__(self, max_folds: int = 3) -> None:
        self.max_folds = max_folds

    def score(self, params: dict, X: pd.DataFrame, y: pd.Series, quarters: pd.Series) -> float:
        # [MOVE BODY FROM trainer._compute_temporal_cv_auc (lines 434-507) HERE;
        #  parameterise by `params` instead of reading trainer state.]
        ...


def run_xgb_hyperopt(X: pd.DataFrame, y: pd.Series, *, budget: HyperoptBudget | None = None) -> dict:
    """Run Optuna search returning best params dict for XGBoost."""
    # [EXTRACT THE Optuna portion of trainer.train() (inside the algorithm=="xgb"
    #  branch) HERE; honour budget.n_trials + budget.timeout_seconds.]
    ...
```

- [ ] **Step 4: Verify pass**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_hyperopt.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Update `trainer.py`**

Replace the inline Optuna section of `ModelTrainer.train()` with `run_xgb_hyperopt(...)`. Keep the `_compute_temporal_cv_auc` method as a thin delegate to `TemporalCVScorer`.

- [ ] **Step 6: Run shadow + backend tests**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_trainer_shadow.py tests/test_trainer_pipeline.py -v`
Expected: green.

- [ ] **Step 7: Commit Task 2.3**

```bash
git add backend/apps/ml_engine/services/hyperopt.py backend/apps/ml_engine/services/trainer.py backend/apps/ml_engine/tests/test_hyperopt.py
git commit -m "refactor(arm-c): extract hyperopt.py from trainer.py"
```

### Task 2.4: Extract `evaluation.py`

**Files:**
- Create: `backend/apps/ml_engine/services/evaluation.py`
- Create: `backend/apps/ml_engine/tests/test_evaluation.py`
- Modify: `backend/apps/ml_engine/services/trainer.py`

- [ ] **Step 1: Write test**

```python
"""Unit tests for post-training evaluation + metric aggregation."""

from __future__ import annotations

import numpy as np
import pytest

from apps.ml_engine.services.evaluation import (
    ModelEvaluationBundle,
    evaluate_trained_model,
)


def test_evaluate_trained_model_returns_all_fields():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, size=200)
    proba = rng.uniform(size=200)

    class _FakeModel:
        classes_ = np.array([0, 1])
        feature_importances_ = np.ones(3)
        def predict_proba(self, X):
            return np.column_stack([1 - proba, proba])
        def predict(self, X):
            return (proba > 0.5).astype(int)

    bundle = evaluate_trained_model(
        model=_FakeModel(),
        X_test=np.zeros((200, 3)),
        y_test=y,
        feature_cols=["a", "b", "c"],
    )
    assert isinstance(bundle, ModelEvaluationBundle)
    assert 0.0 <= bundle.auc_roc <= 1.0
    assert bundle.confusion_matrix.shape == (2, 2)
    assert len(bundle.feature_importances) == 3
```

- [ ] **Step 2: Verify failure**

Run: `cd backend && python -m pytest apps/ml_engine/tests/test_evaluation.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Create `evaluation.py`**

Extract the post-training metric-computation block from `ModelTrainer.train()`. Define a `ModelEvaluationBundle` dataclass with fields: `auc_roc`, `ks_statistic`, `gini_coefficient`, `confusion_matrix`, `feature_importances`, `calibration_curve`, `brier_score`, `ece`, `roc_curve_data`.

- [ ] **Step 4: Verify pass**

- [ ] **Step 5: Update `trainer.py`** — replace the inline metric block with `evaluate_trained_model(...)`.

- [ ] **Step 6: Run shadow + backend tests**

- [ ] **Step 7: Commit Task 2.4**

```bash
git add backend/apps/ml_engine/services/evaluation.py backend/apps/ml_engine/services/trainer.py backend/apps/ml_engine/tests/test_evaluation.py
git commit -m "refactor(arm-c): extract evaluation.py from trainer.py"
```

### Task 2.5: Verify trainer.py below 500, update allowlist, delete shadow

- [ ] **Step 1:** `wc -l backend/apps/ml_engine/services/trainer.py` → expect ≤ 500.
- [ ] **Step 2:** Remove `trainer.py` from `tools/file_size_allowlist.json`.
- [ ] **Step 3:** `python tools/check_file_sizes.py` → passes.
- [ ] **Step 4:** Delete `test_trainer_shadow.py` + `trainer_golden.json`.
- [ ] **Step 5:** `cd backend && python -m pytest -v` → green.
- [ ] **Step 6:** Commit:

```bash
git add tools/file_size_allowlist.json backend/apps/ml_engine/tests/test_trainer_shadow.py backend/apps/ml_engine/tests/fixtures/trainer_golden.json
git commit -m "chore(arm-c): remove trainer.py from allowlist and delete shadow gate"
```

### Task 2.6: Open Phase 2 PR

Same PR-creation pattern as Task 1.6; body summarises preprocessing + hyperopt + evaluation extractions and the byte-identical-metrics guarantee.

---

## Phase 3 — `data_generator.py` split (P1)

Branch: `arm-c/phase-3-data-generator-split`.

1,551 LOC dominated by a single `generate()` method (488-1540, 1,052 LOC). Split along variable families.

### Task 3.1: Baseline + shadow test

Capture: `DataGenerator(random_seed=42).generate(num_records=1000)` → hash the resulting DataFrame (`pd.util.hash_pandas_object(df).sum()`) and save that hash as `data_generator_golden.json`. Shadow test compares post-refactor hash to baseline.

### Task 3.2: Create `realism/` subpackage skeleton

**Files:**
- Create: `backend/apps/ml_engine/services/realism/__init__.py`
- Create: `backend/apps/ml_engine/services/realism/income.py`
- Create: `backend/apps/ml_engine/services/realism/credit.py`
- Create: `backend/apps/ml_engine/services/realism/employment.py`
- Create: `backend/apps/ml_engine/services/realism/property.py`
- Create: `backend/apps/ml_engine/services/realism/macro.py`
- Create: `backend/apps/ml_engine/services/realism/hem.py`
- Create: `backend/apps/ml_engine/services/realism/reject_inference.py`
- Create corresponding `test_realism_*.py` per module under `apps/ml_engine/tests/realism/`

- [ ] **Step 1:** Each module gets a module docstring + `__all__` + stub functions.

- [ ] **Step 2:** Each test file follows RED → GREEN TDD pattern with 2-3 unit tests per module.

### Task 3.3-3.9: Move per-variable logic into its module

One task per realism/*.py module. Each task:
- Writes failing unit test against the module's public function
- Moves the relevant section out of `DataGenerator.generate()` into the new module
- Replaces the removed block with a call to the new function
- Verifies the shadow hash test still passes
- Commits

Example pattern for Task 3.3 (income):

- [ ] **Step 1: Write failing test** in `test_realism_income.py`:

```python
"""Tests for synthetic income generation."""

from __future__ import annotations

import numpy as np
import pytest

from apps.ml_engine.services.realism.income import (
    generate_annual_income,
    resolve_income_params,
)


def test_resolve_income_params_returns_mu_and_sigma():
    mu, sigma = resolve_income_params("middle_class", is_couple=False, state_mult=1.0)
    assert mu > 0 and sigma > 0


def test_generate_annual_income_is_positive():
    rng = np.random.default_rng(0)
    incomes = generate_annual_income(
        n=1000,
        pop_name="middle_class",
        is_couple=np.zeros(1000, dtype=bool),
        state_mult=np.ones(1000),
        rng=rng,
    )
    assert (incomes > 0).all()
    assert 40_000 < incomes.mean() < 200_000
```

- [ ] **Step 2:** Move `_resolve_income_params` + income-generation block from `generate()` to `realism/income.py`.

- [ ] **Step 3:** Update `generate()` to call `generate_annual_income(...)`.

- [ ] **Step 4:** Run shadow test → expect PASS (byte-identical hash).

- [ ] **Step 5:** Commit.

Tasks 3.4 (credit), 3.5 (employment), 3.6 (property), 3.7 (macro), 3.8 (hem), 3.9 (reject_inference) follow the same pattern. The executing agent reads the spec + source file and moves each section atomically.

### Task 3.10: Verify data_generator.py below 500, update allowlist, delete shadow

Same pattern as Task 1.5.

### Task 3.11: Open Phase 3 PR

Same pattern as prior phases.

---

## Phase 4 — `metrics.py` split (P1)

Branch: `arm-c/phase-4-metrics-split`.

1,010 LOC; split into private metric families + public facade.

| Task | Extract | Source lines (approx.) |
|------|---------|-------------------------|
| 4.2  | `_psi.py` | `compute_psi`, `compute_feature_psi` |
| 4.3  | `_ks.py` | `ks_statistic`, `compute_ks_statistic` |
| 4.4  | `_brier.py` | `brier_decomposition` |
| 4.5  | `_calibration.py` | `compute_calibration_data`, ECE helpers |
| 4.6  | `_woe.py` | `compute_woe_iv`, `compute_all_woe_iv`, `build_woe_scorecard` |
| 4.7  | `_vintage.py` | `VintageAnalyser` class |

### Task 4.1: Baseline + shadow test

Shadow compares pre- and post-refactor return values of `MetricsService.compute_metrics(...)` on a fixture.

### Tasks 4.2 – 4.7: Per-family extraction

Each task: write failing test → extract functions to private module → update `metrics.py` to re-export them → shadow test stays green → commit.

`metrics.py` ends as a facade that re-exports everything via:

```python
from apps.ml_engine.services._psi import psi, psi_by_feature, compute_psi, compute_feature_psi
from apps.ml_engine.services._ks import ks_statistic, compute_ks_statistic
from apps.ml_engine.services._brier import brier_decomposition
from apps.ml_engine.services._calibration import (
    compute_calibration_data,
    compute_expected_calibration_error,
)
from apps.ml_engine.services._woe import compute_woe_iv, compute_all_woe_iv, build_woe_scorecard
from apps.ml_engine.services._vintage import VintageAnalyser

__all__ = [
    "MetricsService",
    "VintageAnalyser",
    "psi", "psi_by_feature", "compute_psi", "compute_feature_psi",
    "ks_statistic", "compute_ks_statistic",
    "brier_decomposition",
    "compute_calibration_data", "compute_expected_calibration_error",
    "compute_woe_iv", "compute_all_woe_iv", "build_woe_scorecard",
]
```

### Task 4.8: Verify metrics.py below 500, update allowlist, delete shadow

### Task 4.9: Open Phase 4 PR

---

## Phase 5 — `real_world_benchmarks.py` split (P2)

Branch: `arm-c/phase-5-benchmarks-split`.

1,378 LOC; split into `benchmarks/` subpackage with one file per data source (RBA, APRA, ABS, HELP).

### Task 5.1: Baseline + shadow test

Shadow: hash of `RealWorldBenchmarks().get_calibration_snapshot()` output dict.

### Tasks 5.2 – 5.7: Per-benchmark extraction

| Task | New module | Fetch + parse functions |
|------|-----------|-------------------------|
| 5.2  | `benchmarks/rba_cash_rate.py` | `_fetch_rba_e2_csv`, `_parse_rba_e2_csv` |
| 5.3  | `benchmarks/rba_lending_rates.py` | `_fetch_lending_rates`, `_parse_rba_f5_csv` |
| 5.4  | `benchmarks/rba_f6.py` | `_fetch_rba_f6_rates`, `_parse_rba_f6_csv` |
| 5.5  | `benchmarks/apra_arrears.py` | `_fetch_apra_arrears`, `_parse_apra_xlsx` |
| 5.6  | `benchmarks/abs_income.py` | `_fetch_abs_data`, `_parse_abs_latest_value`, `_parse_abs_series_values`, `_fetch_income_percentiles`, `_fetch_sa4_unemployment`, `_fetch_industry_income_multipliers` |
| 5.7  | `benchmarks/help_debt.py` | `_fetch_help_debt_statistics`, `_parse_help_debt_xlsx` |

Each task follows the TDD + extract + shadow pattern. `RealWorldBenchmarks` becomes a thin facade that composes the benchmark modules + caches results.

### Task 5.8: Verify, update allowlist, delete shadow

### Task 5.9: Open Phase 5 PR

---

## Phase 6 — `underwriting_engine.py` split (P2)

Branch: `arm-c/phase-6-underwriting-split`.

1,001 LOC with `compute_approval()` being 687 of those. Split into `underwriting/` subpackage with one module per rule family.

### Task 6.1: Baseline + shadow test

Shadow: deterministic seeded run of `UnderwritingEngine().compute_approval(df, rng)` on a 200-row fixture → hash resulting decisions.

### Tasks 6.2 – 6.6: Per-rule extraction

| Task | New module | Rule family |
|------|-----------|-------------|
| 6.2  | `underwriting/serviceability.py` | Income-to-repayment serviceability checks |
| 6.3  | `underwriting/lvr.py` | LVR-based gates + LMI threshold handling |
| 6.4  | `underwriting/affordability.py` | HEM-adjusted affordability calculations |
| 6.5  | `underwriting/credit_history.py` | Bureau score + bankruptcy + enquiry gates |
| 6.6  | `underwriting/calibration.py` | `calibrate_default_probability` + its helpers |

Each rule module exports one public entry: `evaluate(row, context) -> RuleResult` where `RuleResult` is a shared dataclass `{passed: bool, reason: str, adjustment: dict}`.

`UnderwritingEngine.compute_approval()` becomes a composer that collects rule results and aggregates into the final approval decision.

### Task 6.7: Verify, update allowlist, delete shadow

### Task 6.8: Open Phase 6 PR

---

## Phase 7 — P3 triage + v1.11.0 release

Branch: `arm-c/phase-7-p3-triage-release`.

### Task 7.1: Triage `property_data_service.py` (765 LOC)

- [ ] **Step 1:** Read the file and categorise sections (service orchestrator vs. client wrappers vs. parsers).
- [ ] **Step 2:** If a clean split exists (e.g., into `property_data/service.py` + `property_data/client.py`), execute the split following the TDD + shadow pattern.
- [ ] **Step 3:** If the file is a single cohesive concern (e.g., all sections coupled via shared state), add to allowlist with rationale comment.
- [ ] **Step 4:** Commit.

### Tasks 7.2 – 7.4: Same pattern for `macro_data_service.py`, `calibration_validator.py`, `credit_bureau_service.py`

### Task 7.5: Bump APP_VERSION and CHANGELOG

**Files:**
- Modify: `backend/config/settings/base.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1:** In `backend/config/settings/base.py` change `APP_VERSION = "1.10.0"` → `APP_VERSION = "1.11.0"`.

- [ ] **Step 2:** Prepend to `CHANGELOG.md`:

```markdown
## [1.11.0] - 2026-04-XX

### Arm C — ml_engine/services/ Quality Bar + Hot-Path Refactor

**Quality bar installed** (`tools/check_file_sizes.py` + CI + pre-commit):
- ≤500 LOC per file under `backend/apps/ml_engine/services/`
- Module docstring required
- `__all__` explicit public API
- Per-PR allowlist with documented exceptions

**Files refactored** (each into focused sub-modules with own tests):
- `predictor.py` 1,209 → ≤500 LOC, extracted `feature_prep.py`, `policy_recompute.py`, `prediction_cache.py`
- `trainer.py` 1,316 → ≤500 LOC, extracted `preprocessing.py`, `hyperopt.py`, `evaluation.py`
- `data_generator.py` 1,551 → ≤500 LOC, extracted `realism/` subpackage (income/credit/employment/property/macro/hem/reject_inference)
- `metrics.py` 1,010 → ≤500 LOC, extracted `_psi.py`, `_ks.py`, `_brier.py`, `_calibration.py`, `_woe.py`, `_vintage.py`
- `real_world_benchmarks.py` 1,378 → ≤500 LOC, extracted `benchmarks/` subpackage (per-data-source modules)
- `underwriting_engine.py` 1,001 → ≤500 LOC, extracted `underwriting/` rules subpackage

**Regression safety:**
- Shadow-verification tests ensured byte-identical outputs for predictor/trainer/data_generator/metrics/benchmarks/underwriting before and after each phase; all deleted on merge.
- Full pytest suite green per phase; no API surface change — old import paths preserved via re-exports.

**P3 triage outcomes:** (list per-file result here — split or allowlisted with rationale)
```

- [ ] **Step 3:** Commit:

```bash
git add backend/config/settings/base.py CHANGELOG.md
git commit -m "chore(release): v1.11.0 — Arm C ml_engine quality bar + refactor"
```

### Task 7.6: Final verification

- [ ] **Step 1:** `wc -l backend/apps/ml_engine/services/*.py | sort -rn | head -10` — confirm no file >500 LOC except allowlisted P3 exceptions.
- [ ] **Step 2:** `python tools/check_file_sizes.py` — confirm green.
- [ ] **Step 3:** `cd backend && python -m pytest -v` — full suite green.
- [ ] **Step 4:** `cd backend && python -m pytest --cov=apps.ml_engine --cov-report=term-missing` — coverage baseline maintained or improved.

### Task 7.7: Open Phase 7 PR + cut release

- [ ] **Step 1:** Push and open PR (same pattern as prior phases).
- [ ] **Step 2:** After merge to master, tag `v1.11.0` (if the project uses tags).

---

## Self-review checklist for the executing agent

Before closing out Arm C, verify:

- [ ] All 10 originally-over-bar files are either under 500 LOC or explicitly allowlisted with a documented rationale
- [ ] No public import path was broken (old `from apps.ml_engine.services.<file> import X` calls still work via re-exports)
- [ ] Coverage did not drop below the Phase 0 baseline
- [ ] All shadow tests were deleted — none should remain in the tree
- [ ] `tools/check_file_sizes.py` runs in both CI and pre-commit and blocks drift
- [ ] APP_VERSION bumped to 1.11.0
- [ ] CHANGELOG.md documents the arm

Any "no" answers get fixed before merging Phase 7.
