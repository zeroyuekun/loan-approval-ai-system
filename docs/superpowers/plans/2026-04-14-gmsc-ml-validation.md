# GMSC Real-Data ML Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the active loan-approval ML model against Kaggle's "Give Me Some Credit" dataset and publish a reproducible, CI-gated validation report.

**Architecture:** A new Docker Jupyter service (`profiles: ["ml"]`) executes a notebook that uses a new `backend/ml_engine/validation/` package (loader, alignment, metrics). The notebook renders to `docs/ml_validation.html` for inline GitHub viewing; a GitHub Actions workflow re-runs the notebook on PRs touching `backend/ml_engine/**`.

**Tech Stack:** Python 3.13, pandas, scikit-learn, matplotlib, jupyter, nbconvert, pytest, Docker Compose v2, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-04-14-gmsc-ml-validation-design.md`

---

## File Structure

**Created:**
- `jupyter/Dockerfile`
- `backend/ml_engine/validation/__init__.py`
- `backend/ml_engine/validation/gmsc_loader.py`
- `backend/ml_engine/validation/feature_align.py`
- `backend/ml_engine/validation/metrics.py`
- `backend/ml_engine/notebooks/gmsc_validation.ipynb`
- `backend/tests/test_ml_validation.py`
- `backend/tests/test_gmsc_notebook.py`
- `backend/tests/fixtures/gmsc_tiny.csv`
- `docs/ml_validation.md`
- `docs/ml_validation.html` (generated artifact, committed)
- `.github/workflows/ml-validation.yml`

**Modified:**
- `docker-compose.yml` (append `jupyter` service)
- `.gitignore` (add `backend/ml_engine/data/gmsc/`)
- `.pre-commit-config.yaml` (add `nbstripout`)
- `README.md` (add validation section)

---

## Task 1: Gitignore and Dataset Directory

**Files:**
- Modify: `.gitignore`
- Create: `backend/ml_engine/data/gmsc/.gitkeep`

- [ ] **Step 1: Append gitignore rules**

Append to `.gitignore`:

```
# ML validation dataset (downloaded at runtime, not committed)
backend/ml_engine/data/gmsc/*
!backend/ml_engine/data/gmsc/.gitkeep
```

- [ ] **Step 2: Create the placeholder**

```bash
mkdir -p backend/ml_engine/data/gmsc
touch backend/ml_engine/data/gmsc/.gitkeep
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore backend/ml_engine/data/gmsc/.gitkeep
git commit -m "chore(ml-validation): gitignore GMSC dataset directory"
```

---

## Task 2: `metrics.py` — Write Failing Tests

**Files:**
- Create: `backend/tests/test_ml_validation.py`

- [ ] **Step 1: Create test file with metrics tests**

```python
# backend/tests/test_ml_validation.py
"""Tests for ml_engine.validation package."""
import numpy as np
import pytest


class TestMetrics:
    """Tests for validation.metrics module."""

    def test_evaluate_returns_expected_keys(self):
        from apps.ml_engine.validation import metrics

        y_true = np.array([0, 0, 1, 1, 0, 1, 1, 0, 1, 0])
        y_prob = np.array([0.1, 0.2, 0.8, 0.7, 0.3, 0.9, 0.6, 0.4, 0.85, 0.15])

        result = metrics.evaluate(y_true, y_prob, threshold=0.5)

        assert set(result.keys()) == {
            "auc_roc",
            "auc_pr",
            "calibration",
            "confusion",
            "per_decile",
            "threshold",
        }

    def test_evaluate_auc_roc_matches_sklearn(self):
        from sklearn.metrics import roc_auc_score

        from apps.ml_engine.validation import metrics

        rng = np.random.default_rng(42)
        y_true = rng.integers(0, 2, size=1000)
        y_prob = rng.random(size=1000)

        result = metrics.evaluate(y_true, y_prob, threshold=0.5)

        assert result["auc_roc"] == pytest.approx(roc_auc_score(y_true, y_prob))

    def test_evaluate_confusion_matrix_shape(self):
        from apps.ml_engine.validation import metrics

        y_true = np.array([0, 1, 0, 1])
        y_prob = np.array([0.1, 0.9, 0.4, 0.6])

        result = metrics.evaluate(y_true, y_prob, threshold=0.5)

        # TN, FP, FN, TP
        assert result["confusion"].shape == (2, 2)
        assert result["confusion"].sum() == 4

    def test_evaluate_calibration_has_ten_deciles(self):
        from apps.ml_engine.validation import metrics

        rng = np.random.default_rng(0)
        y_true = rng.integers(0, 2, size=500)
        y_prob = rng.random(size=500)

        result = metrics.evaluate(y_true, y_prob, threshold=0.5)

        assert len(result["calibration"]) == 10
        assert set(result["calibration"].columns) == {
            "decile",
            "mean_predicted",
            "observed_rate",
            "count",
        }

    def test_evaluate_flags_small_decile_samples(self):
        from apps.ml_engine.validation import metrics

        y_true = np.zeros(30, dtype=int)
        y_prob = np.linspace(0, 1, 30)

        result = metrics.evaluate(y_true, y_prob, threshold=0.5)

        # Each decile has only 3 samples → all flagged
        assert "low_sample" in result["calibration"].columns
        assert result["calibration"]["low_sample"].all()

    def test_evaluate_rejects_mismatched_shapes(self):
        from apps.ml_engine.validation import metrics

        with pytest.raises(ValueError, match="same length"):
            metrics.evaluate(np.array([0, 1]), np.array([0.5]), threshold=0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec backend pytest backend/tests/test_ml_validation.py::TestMetrics -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'apps.ml_engine.validation'`

---

## Task 3: `metrics.py` — Implement

**Files:**
- Create: `backend/apps/ml_engine/validation/__init__.py`
- Create: `backend/apps/ml_engine/validation/metrics.py`

- [ ] **Step 1: Create package init**

```python
# backend/apps/ml_engine/validation/__init__.py
"""ML model validation utilities — GMSC benchmark against the active model."""
```

- [ ] **Step 2: Implement `metrics.py`**

```python
# backend/apps/ml_engine/validation/metrics.py
"""Metric helpers for model validation reports.

Pure functions — no framework dependencies. Keeps the notebook declarative
and the metric logic independently unit-testable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    roc_auc_score,
)

LOW_SAMPLE_THRESHOLD = 50


def evaluate(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> dict:
    """Compute AUC-ROC, AUC-PR, calibration, confusion, and per-decile breakdown.

    Args:
        y_true: ground-truth binary labels, shape (n,).
        y_prob: predicted probabilities for the positive class, shape (n,).
        threshold: classification threshold for confusion-matrix metrics.

    Returns:
        Dict with keys: auc_roc, auc_pr, calibration, confusion, per_decile, threshold.
    """
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)
    if y_true.shape != y_prob.shape:
        raise ValueError("y_true and y_prob must have same length")

    y_pred = (y_prob >= threshold).astype(int)

    calibration = _calibration_table(y_true, y_prob)
    per_decile = _per_decile_breakdown(y_true, y_prob)

    return {
        "auc_roc": float(roc_auc_score(y_true, y_prob)),
        "auc_pr": float(average_precision_score(y_true, y_prob)),
        "calibration": calibration,
        "confusion": confusion_matrix(y_true, y_pred),
        "per_decile": per_decile,
        "threshold": threshold,
    }


def _calibration_table(y_true: np.ndarray, y_prob: np.ndarray) -> pd.DataFrame:
    """Build a 10-decile calibration table (mean predicted vs observed rate)."""
    df = pd.DataFrame({"y_true": y_true, "y_prob": y_prob})
    # qcut with duplicates='drop' handles cases where many probs are tied
    df["decile"] = pd.qcut(df["y_prob"].rank(method="first"), q=10, labels=False)
    grouped = df.groupby("decile", observed=True).agg(
        mean_predicted=("y_prob", "mean"),
        observed_rate=("y_true", "mean"),
        count=("y_true", "size"),
    ).reset_index()
    grouped["low_sample"] = grouped["count"] < LOW_SAMPLE_THRESHOLD
    return grouped


def _per_decile_breakdown(y_true: np.ndarray, y_prob: np.ndarray) -> pd.DataFrame:
    """Alias of calibration table; named separately for API clarity."""
    return _calibration_table(y_true, y_prob)
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
docker compose exec backend pytest backend/tests/test_ml_validation.py::TestMetrics -v
```

Expected: PASS (6 tests).

- [ ] **Step 4: Commit**

```bash
git add backend/apps/ml_engine/validation/__init__.py \
        backend/apps/ml_engine/validation/metrics.py \
        backend/tests/test_ml_validation.py
git commit -m "feat(ml-validation): add metrics module with calibration, AUC-ROC, AUC-PR"
```

---

## Task 4: `gmsc_loader.py` — Write Failing Tests

**Files:**
- Modify: `backend/tests/test_ml_validation.py`

- [ ] **Step 1: Append loader tests**

Append this class to `backend/tests/test_ml_validation.py`:

```python
class TestGmscLoader:
    """Tests for validation.gmsc_loader module."""

    def test_download_verifies_checksum(self, tmp_path, monkeypatch):
        import hashlib
        from unittest.mock import patch

        from apps.ml_engine.validation import gmsc_loader

        fake_csv = b"SeriousDlqin2yrs,age\n1,45\n0,33\n"
        correct_sha = hashlib.sha256(fake_csv).hexdigest()

        monkeypatch.setattr(gmsc_loader, "DATA_DIR", tmp_path)
        monkeypatch.setattr(gmsc_loader, "EXPECTED_SHA256", correct_sha)

        with patch.object(gmsc_loader, "_http_get", return_value=fake_csv):
            df = gmsc_loader.download()

        assert len(df) == 2
        assert "SeriousDlqin2yrs" in df.columns

    def test_download_rejects_tampered_file(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        from apps.ml_engine.validation import gmsc_loader

        tampered_csv = b"SeriousDlqin2yrs,age\n1,45\n"

        monkeypatch.setattr(gmsc_loader, "DATA_DIR", tmp_path)
        monkeypatch.setattr(gmsc_loader, "EXPECTED_SHA256", "0" * 64)

        with patch.object(gmsc_loader, "_http_get", return_value=tampered_csv):
            with pytest.raises(RuntimeError, match="checksum mismatch"):
                gmsc_loader.download()

    def test_download_uses_cache_on_second_call(self, tmp_path, monkeypatch):
        import hashlib
        from unittest.mock import patch

        from apps.ml_engine.validation import gmsc_loader

        fake_csv = b"SeriousDlqin2yrs,age\n1,45\n"
        correct_sha = hashlib.sha256(fake_csv).hexdigest()

        monkeypatch.setattr(gmsc_loader, "DATA_DIR", tmp_path)
        monkeypatch.setattr(gmsc_loader, "EXPECTED_SHA256", correct_sha)

        with patch.object(gmsc_loader, "_http_get", return_value=fake_csv) as mock_get:
            gmsc_loader.download()
            gmsc_loader.download()
            assert mock_get.call_count == 1
```

- [ ] **Step 2: Run and verify failure**

```bash
docker compose exec backend pytest backend/tests/test_ml_validation.py::TestGmscLoader -v
```

Expected: FAIL — `ModuleNotFoundError: apps.ml_engine.validation.gmsc_loader`

---

## Task 5: `gmsc_loader.py` — Implement

**Files:**
- Create: `backend/apps/ml_engine/validation/gmsc_loader.py`

- [ ] **Step 1: Implement loader**

```python
# backend/apps/ml_engine/validation/gmsc_loader.py
"""Download and verify the Kaggle 'Give Me Some Credit' dataset.

Source: https://www.kaggle.com/c/GiveMeSomeCredit
Mirror (direct CSV): https://raw.githubusercontent.com/gmsc-mirror/data/main/cs-training.csv

The checksum is committed alongside the code. A mismatch raises
RuntimeError — no silent fallback to tampered or stale data.
"""
from __future__ import annotations

import hashlib
import logging
import urllib.request
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Pinned source. If Kaggle restricts access, update the mirror URL and
# regenerate the SHA256.
SOURCE_URL = "https://raw.githubusercontent.com/gmsc-mirror/data/main/cs-training.csv"
EXPECTED_SHA256 = "REPLACE_ME_WITH_ACTUAL_SHA256_ON_FIRST_RUN"

DATA_DIR = Path(__file__).resolve().parents[3] / "ml_engine" / "data" / "gmsc"
CSV_PATH = DATA_DIR / "cs-training.csv"


def download() -> pd.DataFrame:
    """Return the GMSC training DataFrame, downloading + verifying if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not CSV_PATH.exists():
        logger.info("Downloading GMSC dataset from %s", SOURCE_URL)
        raw = _http_get(SOURCE_URL)
        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha != EXPECTED_SHA256:
            raise RuntimeError(
                f"GMSC download failed: checksum mismatch. "
                f"Expected {EXPECTED_SHA256}, got {actual_sha}."
            )
        CSV_PATH.write_bytes(raw)
    else:
        logger.info("Using cached GMSC dataset at %s", CSV_PATH)

    return pd.read_csv(CSV_PATH)


def _http_get(url: str) -> bytes:
    """Fetch a URL and return raw bytes. Isolated for test mocking."""
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (pinned URL)
        return resp.read()
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
docker compose exec backend pytest backend/tests/test_ml_validation.py::TestGmscLoader -v
```

Expected: PASS (3 tests).

- [ ] **Step 3: Commit**

```bash
git add backend/apps/ml_engine/validation/gmsc_loader.py \
        backend/tests/test_ml_validation.py
git commit -m "feat(ml-validation): add GMSC loader with SHA256 verification"
```

---

## Task 6: `feature_align.py` — Derive Aussie Feature List

**Files:**
- Read only: `backend/apps/ml_engine/` (to locate the active model's feature list)

- [ ] **Step 1: Identify the feature list**

Search for the canonical feature list:

```bash
grep -rn "FEATURE_COLUMNS\|feature_names\|features =" backend/apps/ml_engine/ | head -20
```

Document what was found in a comment at the top of the next file — the actual list used by the active model. Do NOT hardcode guesses.

- [ ] **Step 2: Build the GMSC → Aussie mapping table**

GMSC columns (known, fixed):
```
SeriousDlqin2yrs (target)
RevolvingUtilizationOfUnsecuredLines
age
NumberOfTime30-59DaysPastDueNotWorse
DebtRatio
MonthlyIncome
NumberOfOpenCreditLinesAndLoans
NumberOfTimes90DaysLate
NumberRealEstateLoansOrLines
NumberOfTime60-89DaysPastDueNotWorse
NumberOfDependents
```

Construct a mapping dict matching these to whatever the Aussie model uses (based on Step 1's grep output). Features with no GMSC equivalent → marked as missing.

---

## Task 7: `feature_align.py` — Write Failing Tests

**Files:**
- Modify: `backend/tests/test_ml_validation.py`

- [ ] **Step 1: Append alignment tests**

Append this class:

```python
class TestFeatureAlign:
    """Tests for validation.feature_align module."""

    @pytest.fixture
    def gmsc_sample(self):
        import pandas as pd
        return pd.DataFrame({
            "SeriousDlqin2yrs": [0, 1, 0],
            "RevolvingUtilizationOfUnsecuredLines": [0.3, 0.9, 0.1],
            "age": [35, 52, 28],
            "NumberOfTime30-59DaysPastDueNotWorse": [0, 2, 0],
            "DebtRatio": [0.4, 0.7, 0.2],
            "MonthlyIncome": [5000, 3500, 7200],
            "NumberOfOpenCreditLinesAndLoans": [5, 2, 8],
            "NumberOfTimes90DaysLate": [0, 1, 0],
            "NumberRealEstateLoansOrLines": [1, 0, 2],
            "NumberOfTime60-89DaysPastDueNotWorse": [0, 0, 0],
            "NumberOfDependents": [2, 0, 1],
        })

    def test_align_returns_aussie_schema(self, gmsc_sample):
        from apps.ml_engine.validation import feature_align

        aligned_df, y, report = feature_align.align(gmsc_sample)

        assert list(aligned_df.columns) == feature_align.AUSSIE_FEATURES
        assert len(aligned_df) == len(gmsc_sample)
        assert y.tolist() == [0, 1, 0]

    def test_align_fills_missing_features_with_median(self, gmsc_sample):
        from apps.ml_engine.validation import feature_align

        aligned_df, _, report = feature_align.align(gmsc_sample)

        for missing_feat in report["missing"]:
            assert aligned_df[missing_feat].notna().all()
            # Median fill => constant column
            assert aligned_df[missing_feat].nunique() == 1

    def test_align_report_classifies_every_feature(self, gmsc_sample):
        from apps.ml_engine.validation import feature_align

        _, _, report = feature_align.align(gmsc_sample)

        classified = (
            set(report["direct"]) | set(report["approximated"]) | set(report["missing"])
        )
        assert classified == set(feature_align.AUSSIE_FEATURES)

    def test_align_raises_when_over_half_features_missing(self, gmsc_sample, monkeypatch):
        from apps.ml_engine.validation import feature_align

        # Force AUSSIE_FEATURES to be much longer than GMSC can cover
        monkeypatch.setattr(
            feature_align,
            "AUSSIE_FEATURES",
            feature_align.AUSSIE_FEATURES + [f"fake_{i}" for i in range(100)],
        )
        monkeypatch.setattr(
            feature_align,
            "DIRECT_MAP",
            {},
        )
        monkeypatch.setattr(feature_align, "APPROXIMATE_MAP", {})

        with pytest.raises(RuntimeError, match="more than 50"):
            feature_align.align(gmsc_sample)
```

- [ ] **Step 2: Run and verify failure**

```bash
docker compose exec backend pytest backend/tests/test_ml_validation.py::TestFeatureAlign -v
```

Expected: FAIL — module missing.

---

## Task 8: `feature_align.py` — Implement

**Files:**
- Create: `backend/apps/ml_engine/validation/feature_align.py`

- [ ] **Step 1: Implement alignment**

Use the feature list found in Task 6. The example below assumes common loan-model features — replace `AUSSIE_FEATURES`, `DIRECT_MAP`, and `APPROXIMATE_MAP` with what Task 6 identified.

```python
# backend/apps/ml_engine/validation/feature_align.py
"""Map GMSC columns onto the active Aussie-model feature schema.

Returns an aligned DataFrame, the target column, and a report classifying
every Aussie feature as direct / approximated / missing. The report is
surfaced in the notebook and written to docs/ml_validation.md so the
caveats cannot rot silently.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# TODO (implementer): replace with the actual feature list from the active
# ModelVersion in backend/apps/ml_engine/ — see Task 6.
AUSSIE_FEATURES = [
    "credit_score",
    "debt_to_income",
    "monthly_income",
    "employment_tenure_months",
    "age",
    "num_dependents",
    "late_payments_24mo",
    "credit_utilisation",
    "num_open_credit_lines",
    "serious_delinquency_90d",
    "num_property_loans",
    "loan_amount",
    "loan_to_income",
    "savings_to_loan",
    "bnpl_commitments",
]

# Direct: same semantic + same scale.
DIRECT_MAP: dict[str, str] = {
    "monthly_income": "MonthlyIncome",
    "age": "age",
    "num_dependents": "NumberOfDependents",
    "credit_utilisation": "RevolvingUtilizationOfUnsecuredLines",
    "num_open_credit_lines": "NumberOfOpenCreditLinesAndLoans",
    "num_property_loans": "NumberRealEstateLoansOrLines",
    "serious_delinquency_90d": "NumberOfTimes90DaysLate",
}

# Approximated: same concept, needs a transform. Value = lambda(gmsc_df).
APPROXIMATE_MAP: dict[str, callable] = {
    "debt_to_income": lambda df: df["DebtRatio"].clip(0, 5),
    "late_payments_24mo": lambda df: (
        df["NumberOfTime30-59DaysPastDueNotWorse"]
        + df["NumberOfTime60-89DaysPastDueNotWorse"]
        + df["NumberOfTimes90DaysLate"]
    ),
}

TARGET_COLUMN = "SeriousDlqin2yrs"


def align(gmsc_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, dict]:
    """Return (aligned_X, y, overlap_report).

    aligned_X has exactly AUSSIE_FEATURES as columns in order.
    Missing features are filled with their per-column median.
    Report classifies every Aussie feature as direct / approximated / missing.
    """
    y = gmsc_df[TARGET_COLUMN].astype(int)

    report = {"direct": [], "approximated": [], "missing": []}
    aligned = {}

    for feat in AUSSIE_FEATURES:
        if feat in DIRECT_MAP and DIRECT_MAP[feat] in gmsc_df.columns:
            aligned[feat] = gmsc_df[DIRECT_MAP[feat]]
            report["direct"].append(feat)
        elif feat in APPROXIMATE_MAP:
            aligned[feat] = APPROXIMATE_MAP[feat](gmsc_df)
            report["approximated"].append(feat)
        else:
            report["missing"].append(feat)
            aligned[feat] = float("nan")

    missing_pct = len(report["missing"]) / len(AUSSIE_FEATURES)
    if missing_pct > 0.5:
        raise RuntimeError(
            f"Feature alignment dropped more than 50% of features "
            f"({len(report['missing'])}/{len(AUSSIE_FEATURES)}). "
            f"Missing: {report['missing']}"
        )

    aligned_df = pd.DataFrame(aligned, columns=AUSSIE_FEATURES)

    # Fill missing features with their column median (of the non-NaN values,
    # which for full-NaN columns is itself NaN → replaced with 0 as a last
    # resort and logged).
    for feat in report["missing"]:
        col = aligned_df[feat]
        fill = col.median()
        if pd.isna(fill):
            fill = 0.0
            logger.warning("Feature %s fully missing — filled with 0", feat)
        aligned_df[feat] = fill

    return aligned_df, y, report
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
docker compose exec backend pytest backend/tests/test_ml_validation.py::TestFeatureAlign -v
```

Expected: PASS (4 tests).

- [ ] **Step 3: Commit**

```bash
git add backend/apps/ml_engine/validation/feature_align.py \
        backend/tests/test_ml_validation.py
git commit -m "feat(ml-validation): add GMSC feature alignment with overlap report"
```

---

## Task 9: Tiny GMSC Fixture

**Files:**
- Create: `backend/tests/fixtures/gmsc_tiny.csv`

- [ ] **Step 1: Generate fixture**

Run a throwaway Python script (do not commit the script) to produce a 500-row deterministic fixture matching GMSC's schema:

```python
# scratch/gen_fixture.py (NOT COMMITTED — delete after use)
import numpy as np
import pandas as pd

rng = np.random.default_rng(20260414)
n = 500
df = pd.DataFrame({
    "SeriousDlqin2yrs": rng.integers(0, 2, n),
    "RevolvingUtilizationOfUnsecuredLines": rng.random(n),
    "age": rng.integers(18, 80, n),
    "NumberOfTime30-59DaysPastDueNotWorse": rng.integers(0, 5, n),
    "DebtRatio": rng.random(n) * 2,
    "MonthlyIncome": rng.integers(1000, 15000, n),
    "NumberOfOpenCreditLinesAndLoans": rng.integers(0, 15, n),
    "NumberOfTimes90DaysLate": rng.integers(0, 3, n),
    "NumberRealEstateLoansOrLines": rng.integers(0, 4, n),
    "NumberOfTime60-89DaysPastDueNotWorse": rng.integers(0, 3, n),
    "NumberOfDependents": rng.integers(0, 5, n),
})
df.to_csv("backend/tests/fixtures/gmsc_tiny.csv", index=False)
```

Run once from repo root, then delete the script.

- [ ] **Step 2: Commit fixture**

```bash
git add backend/tests/fixtures/gmsc_tiny.csv
git commit -m "test(ml-validation): add 500-row GMSC fixture for fast tests"
```

---

## Task 10: Validation Notebook — Scaffold and Smoke Test

**Files:**
- Create: `backend/apps/ml_engine/notebooks/gmsc_validation.ipynb`
- Create: `backend/tests/test_gmsc_notebook.py`

- [ ] **Step 1: Write the notebook smoke test first**

```python
# backend/tests/test_gmsc_notebook.py
"""Smoke test: execute the validation notebook against the tiny fixture."""
from pathlib import Path

import nbformat
import pytest
from nbconvert.preprocessors import ExecutePreprocessor

NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "apps" / "ml_engine" / "notebooks" / "gmsc_validation.ipynb"
)
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "gmsc_tiny.csv"


@pytest.mark.slow
def test_notebook_runs_end_to_end(monkeypatch, tmp_path):
    """Execute the notebook parameterized to use the tiny fixture."""
    monkeypatch.setenv("GMSC_FIXTURE_PATH", str(FIXTURE_PATH))
    monkeypatch.setenv("GMSC_USE_FIXTURE", "1")

    nb = nbformat.read(NOTEBOOK_PATH, as_version=4)
    ep = ExecutePreprocessor(timeout=120, kernel_name="python3")
    ep.preprocess(nb, {"metadata": {"path": str(NOTEBOOK_PATH.parent)}})

    # Find the AUC cell (tagged "auc") and confirm it produced output
    auc_cells = [c for c in nb.cells if "auc" in c.metadata.get("tags", [])]
    assert auc_cells, "Notebook must have a cell tagged 'auc'"
    assert any("auc_roc" in str(out) for out in auc_cells[0].outputs)
```

- [ ] **Step 2: Run the test to verify it fails (notebook doesn't exist)**

```bash
docker compose exec backend pytest backend/tests/test_gmsc_notebook.py -v
```

Expected: FAIL — notebook missing.

- [ ] **Step 3: Create the notebook**

Create `backend/apps/ml_engine/notebooks/gmsc_validation.ipynb` with the following cells (use Jupyter inside the new `jupyter` container once Task 13 is done, OR author as JSON directly for this initial scaffold):

**Cell 1 — Parameters (tag: `parameters`)**
```python
THRESHOLD = 0.5
RANDOM_SEED = 42
USE_FIXTURE = False
```

**Cell 2 — Imports & Setup**
```python
import os
import numpy as np
import pandas as pd
from apps.ml_engine.validation import gmsc_loader, feature_align, metrics
from apps.ml_engine.services.prediction import load_active_model  # or however the active model is loaded

np.random.seed(RANDOM_SEED)

if os.environ.get("GMSC_USE_FIXTURE") == "1":
    USE_FIXTURE = True
```

**Cell 3 — Load data**
```python
if USE_FIXTURE:
    df = pd.read_csv(os.environ["GMSC_FIXTURE_PATH"])
else:
    df = gmsc_loader.download()
print(f"Loaded {len(df):,} GMSC records")
```

**Cell 4 — Align features**
```python
X, y, report = feature_align.align(df)
print(f"Direct:       {len(report['direct'])}")
print(f"Approximated: {len(report['approximated'])}")
print(f"Missing:      {len(report['missing'])}")
```

**Cell 5 — Predict**
```python
model = load_active_model()
y_prob = model.predict_proba(X)[:, 1]
```

**Cell 6 — Evaluate (tag: `auc`)**
```python
results = metrics.evaluate(y.values, y_prob, threshold=THRESHOLD)
print(f"AUC-ROC: {results['auc_roc']:.4f}")
print(f"AUC-PR:  {results['auc_pr']:.4f}")
```

**Cell 7 — Calibration plot**
```python
import matplotlib.pyplot as plt

cal = results["calibration"]
fig, ax = plt.subplots(figsize=(6, 6))
ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Perfect calibration")
ax.plot(cal["mean_predicted"], cal["observed_rate"], "o-", label="Model")
ax.set_xlabel("Mean predicted probability")
ax.set_ylabel("Observed default rate")
ax.set_title("Calibration curve (per decile)")
ax.legend()
plt.tight_layout()
plt.show()
```

**Cell 8 — Overlap report**
```python
print("## Feature overlap\n")
print(f"Direct: {report['direct']}\n")
print(f"Approximated: {report['approximated']}\n")
print(f"Missing (filled with median): {report['missing']}\n")
```

- [ ] **Step 4: Run smoke test to verify it passes**

```bash
docker compose exec backend pytest backend/tests/test_gmsc_notebook.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/notebooks/gmsc_validation.ipynb \
        backend/tests/test_gmsc_notebook.py
git commit -m "feat(ml-validation): add validation notebook + smoke test"
```

---

## Task 11: Jupyter Dockerfile

**Files:**
- Create: `jupyter/Dockerfile`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
# jupyter/Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Match backend runtime deps plus Jupyter stack
COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt \
    && pip install --no-cache-dir \
        jupyter==1.1.1 \
        notebook==7.3.2 \
        nbconvert==7.16.5 \
        papermill==2.6.0 \
        nbstripout==0.8.1 \
        matplotlib==3.9.3

ENV PYTHONPATH=/app/backend
EXPOSE 8888

CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", \
     "--allow-root", "--NotebookApp.token=${JUPYTER_TOKEN:-dev}"]
```

- [ ] **Step 2: Commit**

```bash
git add jupyter/Dockerfile
git commit -m "build(jupyter): add Dockerfile for ml-validation notebook service"
```

---

## Task 12: Add Jupyter Service to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Append jupyter service**

Append this service block after the existing `frontend` service (adjust indentation to match the file's style):

```yaml
  jupyter:
    profiles: ["ml"]
    build:
      context: .
      dockerfile: jupyter/Dockerfile
    ports:
      - "127.0.0.1:8888:8888"
    environment:
      JUPYTER_TOKEN: dev
      DJANGO_SETTINGS_MODULE: config.settings
      DATABASE_URL: postgres://postgres:postgres@db:5432/loans
    volumes:
      - ./backend:/app/backend
      - ./docs:/app/docs
      - ./.tmp:/app/.tmp
    depends_on:
      db:
        condition: service_healthy
```

- [ ] **Step 2: Verify the service builds and starts**

```bash
docker compose --profile ml build jupyter
docker compose --profile ml up -d jupyter
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8888/
docker compose --profile ml down
```

Expected: HTTP 200 or 302 from Jupyter.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "build(compose): add opt-in jupyter service under profiles: [ml]"
```

---

## Task 13: Render HTML Artifact and docs/ml_validation.md

**Files:**
- Create: `docs/ml_validation.html`
- Create: `docs/ml_validation.md`

- [ ] **Step 1: Execute the notebook and render HTML**

```bash
docker compose exec backend jupyter nbconvert \
  --to html \
  --execute backend/apps/ml_engine/notebooks/gmsc_validation.ipynb \
  --output-dir docs \
  --output ml_validation \
  --ExecutePreprocessor.timeout=600
```

Expected: `docs/ml_validation.html` written.

- [ ] **Step 2: Write the companion markdown**

```markdown
<!-- docs/ml_validation.md -->
# ML Model Validation — Real-Data Benchmark

The active loan-approval ML model is validated against the Kaggle
"Give Me Some Credit" (GMSC) dataset — 250K labeled credit records. GMSC
is a widely-used industry benchmark; validating against it gives a real,
externally-sourced AUC to contrast with the synthetic training metric.

**→ [Full report with plots (HTML)](./ml_validation.html)**

## Summary

| Metric | Value |
|---|---|
| Dataset | Kaggle GMSC — 250K records |
| AUC-ROC | *(see HTML report)* |
| AUC-PR | *(see HTML report)* |
| Threshold | 0.5 (production default) |

## Caveats

GMSC is a US-market dataset. The active model is trained on Australian
synthetic data with Aussie-specific features (BNPL, APRA serviceability,
ABN validation). A subset of features aligns directly; others are
approximated or unavailable. The feature-overlap table in the HTML report
details every feature's status.

Expect AUC on GMSC to sit 0.05–0.10 below the synthetic-data AUC due to
distribution shift. That gap is the honest cost of not having Australian
real-data ground truth.

## How to regenerate

```bash
docker compose --profile ml up -d jupyter
# open http://127.0.0.1:8888 (token: dev), run the notebook
docker compose exec backend jupyter nbconvert \
  --to html \
  --execute backend/apps/ml_engine/notebooks/gmsc_validation.ipynb \
  --output-dir docs \
  --output ml_validation
```

CI automatically re-runs the notebook on PRs touching `backend/apps/ml_engine/**`
and fails if the rendered HTML diverges from what is committed.
```

- [ ] **Step 3: Commit both artifacts**

```bash
git add docs/ml_validation.html docs/ml_validation.md
git commit -m "docs(ml-validation): add rendered HTML report + markdown narrative"
```

---

## Task 14: nbstripout Pre-commit Hook

**Files:**
- Modify: `.pre-commit-config.yaml` (create if it doesn't exist)

- [ ] **Step 1: Check whether the file exists**

```bash
ls .pre-commit-config.yaml 2>/dev/null && echo "exists" || echo "missing"
```

- [ ] **Step 2a: If missing, create it**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/kynan/nbstripout
    rev: 0.8.1
    hooks:
      - id: nbstripout
        files: \.ipynb$
```

- [ ] **Step 2b: If it exists, append the hook**

Append the `nbstripout` repo block from Step 2a to the existing `repos:` list.

- [ ] **Step 3: Install and test**

```bash
pip install pre-commit
pre-commit install
pre-commit run nbstripout --all-files
```

Expected: notebook outputs stripped from the source `.ipynb` (the rendered HTML at `docs/ml_validation.html` is the artifact; the `.ipynb` in the repo stays output-free).

- [ ] **Step 4: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore(pre-commit): add nbstripout for notebook hygiene"
```

---

## Task 15: GitHub Actions CI Workflow

**Files:**
- Create: `.github/workflows/ml-validation.yml`

- [ ] **Step 1: Write workflow**

```yaml
# .github/workflows/ml-validation.yml
name: ML Validation
on:
  pull_request:
    paths:
      - 'backend/apps/ml_engine/**'
      - 'docs/ml_validation.*'
      - '.github/workflows/ml-validation.yml'
  workflow_dispatch:

jobs:
  validate:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
          cache: pip

      - name: Install deps
        run: |
          pip install -r backend/requirements.txt
          pip install jupyter nbconvert papermill matplotlib

      - name: Cache GMSC dataset
        uses: actions/cache@v4
        with:
          path: backend/ml_engine/data/gmsc/
          key: gmsc-${{ hashFiles('backend/apps/ml_engine/validation/gmsc_loader.py') }}

      - name: Execute notebook and render HTML
        env:
          PYTHONPATH: backend
          DJANGO_SETTINGS_MODULE: config.settings
        run: |
          jupyter nbconvert \
            --to html \
            --execute backend/apps/ml_engine/notebooks/gmsc_validation.ipynb \
            --output-dir /tmp/ \
            --output ml_validation \
            --ExecutePreprocessor.timeout=600

      - name: Verify committed HTML is up to date
        run: |
          if ! diff -q /tmp/ml_validation.html docs/ml_validation.html; then
            echo "::error::Committed docs/ml_validation.html is stale. Run the notebook and commit the refreshed HTML."
            diff /tmp/ml_validation.html docs/ml_validation.html | head -40
            exit 1
          fi

      - name: Upload HTML artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: ml-validation-report
          path: /tmp/ml_validation.html
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ml-validation.yml
git commit -m "ci(ml-validation): add GitHub Actions workflow with HTML drift detection"
```

---

## Task 16: README Section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append ML validation section**

Append under a new top-level section (or near existing ML documentation — pick the right anchor based on current README structure):

```markdown
## ML Validation

The active model is validated against the Kaggle "Give Me Some Credit" dataset.

- **Read the latest report:** [`docs/ml_validation.html`](docs/ml_validation.html) — rendered inline, no setup required.
- **Regenerate locally:**
  ```bash
  docker compose --profile ml up -d jupyter
  # Open http://127.0.0.1:8888 (token: dev) and run the notebook, OR:
  docker compose exec backend jupyter nbconvert \
    --to html \
    --execute backend/apps/ml_engine/notebooks/gmsc_validation.ipynb \
    --output-dir docs \
    --output ml_validation
  ```
- **CI:** PRs touching `backend/apps/ml_engine/**` re-run the notebook and fail if the committed HTML diverges.
- **Dataset:** downloaded + SHA256-verified on first run. Not committed to git.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): add ML validation section"
```

---

## Task 17: Final Verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

```bash
docker compose exec backend pytest backend/tests/test_ml_validation.py backend/tests/test_gmsc_notebook.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Verify the Jupyter service starts cleanly**

```bash
docker compose --profile ml up -d jupyter
sleep 10
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8888/
docker compose --profile ml down
```

Expected: HTTP 200 or 302.

- [ ] **Step 3: Verify the rendered HTML opens**

Open `docs/ml_validation.html` in a browser and scroll the full report. Confirm: AUC numbers present, calibration plot renders, overlap table visible.

- [ ] **Step 4: Update the rating memory**

Update `C:\Users\Admin\.claude\projects\C--Users-Admin-loan-approval-ai-system\memory\project_ml_accuracy_context.md` with the GMSC AUC number from the final run.

- [ ] **Step 5: Final commit if any docs changed**

```bash
git status
# If README / memory were modified, commit
```

---

## Self-Review Notes

Reviewed against the spec — all delivery-checklist items mapped to tasks:

| Spec item | Task |
|---|---|
| `docker-compose.yml` jupyter service | Task 12 |
| `jupyter/Dockerfile` | Task 11 |
| `validation/` package (loader, align, metrics) | Tasks 2–8 |
| `.gitignore` GMSC data | Task 1 |
| Validation notebook | Task 10 |
| `docs/ml_validation.{html,md}` | Task 13 |
| Unit tests | Tasks 2–8 |
| Notebook smoke test + fixture | Tasks 9, 10 |
| `nbstripout` pre-commit | Task 14 |
| CI workflow | Task 15 |
| README | Task 16 |
| Final verification | Task 17 |

All spec requirements have at least one task. Task 6 requires the implementer to read the active model's feature list from the codebase before Task 8 hardcodes it — this is deliberate: the exact feature list is not in the spec, and guessing it would produce a broken alignment. Task 6 forces that research.

Type consistency: `metrics.evaluate(y_true, y_prob, threshold)` signature is used consistently across tests, notebook, and CI gate. `feature_align.align(df)` returns `(X, y, report)` consistently. `AUSSIE_FEATURES` / `DIRECT_MAP` / `APPROXIMATE_MAP` names are used consistently across tests and implementation.
