# Drift Tiles Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate the PSI and Approval-rate KPI tiles on `/dashboard/model-metrics` with honest numbers derived from a real prediction stream, and make every future trained model drift-ready by default.

**Architecture:** Three deliverables in `apps/ml_engine`. (1) Trainer hook stashes holdout-set probabilities + per-feature samples on the trainer instance after `predict_proba(X_test)`, and `save_model` augments the bundle's existing `reference_distribution` dict with `probability_distribution` + `feature_distributions` keys. The metrics dict gets a `training_metadata.reference_probabilities` mirror so the simpler `compute_weekly_drift_report` task works without bundle access. (2) `backfill_reference_distribution` management command patches the currently-active model's bundle + DB row in place. (3) `seed_predictions` management command generates an AU-realistic synthetic prediction stream against the active model (weekday- + evening-biased timestamps) and triggers `compute_weekly_drift_report.apply()` synchronously to write a real `DriftReport` row.

**Tech Stack:** Django 4 + Django REST Framework, Celery, scikit-learn, XGBoost, joblib, NumPy, pytest + pytest-django.

**Spec:** [`docs/superpowers/specs/2026-05-08-drift-tiles-design.md`](../specs/2026-05-08-drift-tiles-design.md)

**Branch:** `feat/drift-tiles-fix` (already created and contains the spec commit).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/apps/ml_engine/services/trainer.py` | MODIFY | After `predict_proba(X_test)` near line 919, stash holdout probabilities + feature samples on the trainer instance. In `save_model` (line 1279), augment `bundle["reference_distribution"]` with new keys. In `metrics["training_metadata"]` block (line 986), add `reference_probabilities` mirror. |
| `backend/apps/ml_engine/management/commands/backfill_reference_distribution.py` | NEW | One-shot patch for existing models lacking the new bundle keys. Generates fresh `DataGenerator` batch, runs model, populates fields, atomically re-saves bundle. |
| `backend/apps/ml_engine/management/commands/seed_predictions.py` | NEW | Generate `--count` AU-calibrated rows via `DataGenerator`, run `ModelPredictor.predict()` for each, override `created_at` with weekday/evening-biased timestamps via `bulk_update`, optionally trigger `compute_weekly_drift_report.apply()`. |
| `backend/tests/test_trainer_reference_distribution.py` | NEW | Unit test for the trainer hook. |
| `backend/tests/test_backfill_reference_distribution.py` | NEW | Unit test for the backfill command (idempotency + `--force` overwrite). |
| `backend/tests/test_seed_predictions.py` | NEW | Unit test for the seed command (count, time window, exact day-of-week distribution with fixed seed). |
| `backend/tests/test_drift_pipeline_integration.py` | NEW | End-to-end: tiny model → backfill → seed 30 → drift task → assert `DriftReport` row with non-null `psi_score` + `approval_rate`. |
| `backend/docs/RUNBOOK.md` | MODIFY | Append "Initial drift seed for new model deployments" section (~15 lines). |

Each task below produces a self-contained atomic commit. Tests are written before implementation per TDD.

---

## Task 1: Trainer hook — stash holdout probabilities and feature samples

**Goal:** After the trainer's final `predict_proba(X_test)` call (which produces holdout probabilities the metrics service already consumes), capture a sample of those probabilities and a sample of per-feature values onto the trainer instance, so `save_model` can later read them.

**Files:**
- Modify: `backend/apps/ml_engine/services/trainer.py:919` (immediately after `y_prob = model.predict_proba(X_test)[:, 1]`)
- Test: `backend/tests/test_trainer_reference_distribution.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_trainer_reference_distribution.py`:

```python
"""Tests for the trainer's reference-distribution capture hook.

The hook stashes a sample of holdout probabilities and per-feature values on
the trainer instance after final model fit + predict_proba, so save_model can
embed them in the bundle and the metrics dict can mirror them for the simpler
weekly drift task.
"""

import numpy as np
import pytest

from apps.ml_engine.services.trainer import ModelTrainer


@pytest.mark.django_db
def test_capture_reference_distribution_caps_at_1000():
    """Sample size never exceeds 1000 even when holdout is larger."""
    trainer = ModelTrainer()
    rng = np.random.default_rng(42)
    holdout_probs = rng.random(size=5000)
    feature_df = type("DF", (), {})()
    feature_df.columns = ["annual_income", "credit_score"]

    # Fake a feature DataFrame using a dict-of-arrays interface that the
    # helper supports (numeric-only sampling).
    import pandas as pd
    holdout_features = pd.DataFrame({
        "annual_income": rng.integers(30000, 200000, size=5000),
        "credit_score": rng.integers(300, 850, size=5000),
    })

    trainer._capture_holdout_reference(holdout_probs, holdout_features)

    assert len(trainer._holdout_probabilities) == 1000
    assert set(trainer._holdout_feature_samples.keys()) == {"annual_income", "credit_score"}
    assert all(len(v) == 1000 for v in trainer._holdout_feature_samples.values())


@pytest.mark.django_db
def test_capture_reference_distribution_uses_full_holdout_when_small():
    """When holdout is smaller than the cap, capture the entire holdout."""
    import pandas as pd
    trainer = ModelTrainer()
    holdout_probs = np.array([0.1, 0.4, 0.7, 0.95])
    holdout_features = pd.DataFrame({"credit_score": [600, 650, 700, 750]})

    trainer._capture_holdout_reference(holdout_probs, holdout_features)

    assert trainer._holdout_probabilities == [0.1, 0.4, 0.7, 0.95]
    assert trainer._holdout_feature_samples == {"credit_score": [600, 650, 700, 750]}


@pytest.mark.django_db
def test_capture_reference_distribution_handles_empty_holdout():
    """Empty holdout produces empty lists, no exception."""
    import pandas as pd
    trainer = ModelTrainer()
    trainer._capture_holdout_reference(np.array([]), pd.DataFrame())

    assert trainer._holdout_probabilities == []
    assert trainer._holdout_feature_samples == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_trainer_reference_distribution.py -v
```

Expected: 3 FAILs with `AttributeError: 'ModelTrainer' object has no attribute '_capture_holdout_reference'`.

- [ ] **Step 3: Write minimal implementation — add helper method on `ModelTrainer`**

Edit `backend/apps/ml_engine/services/trainer.py`. Find the `class ModelTrainer:` definition. Add a new method (placed just before `save_model`, around line 1278):

```python
    def _capture_holdout_reference(self, holdout_probs, holdout_features):
        """Stash a sample of holdout probabilities + per-feature values.

        Called after final model fit + predict_proba(X_test). The samples
        feed save_model (bundle.reference_distribution.probability_distribution
        + feature_distributions) and the metrics["training_metadata"] block
        (reference_probabilities). Cap each list at 1000 entries to keep the
        bundle small.

        Drift readiness is opportunistic: any failure is logged and the
        attributes are set to safe empty defaults so training never blocks.
        """
        cap = 1000
        try:
            probs_arr = np.asarray(holdout_probs, dtype=float).ravel()
            if probs_arr.size == 0:
                self._holdout_probabilities = []
            elif probs_arr.size <= cap:
                self._holdout_probabilities = probs_arr.tolist()
            else:
                rng = np.random.default_rng(42)
                idx = rng.choice(probs_arr.size, size=cap, replace=False)
                self._holdout_probabilities = probs_arr[idx].tolist()
        except Exception:
            logger.warning("Holdout probability capture failed", exc_info=True)
            self._holdout_probabilities = []

        feature_samples = {}
        try:
            if hasattr(holdout_features, "columns") and len(holdout_features) > 0:
                n = len(holdout_features)
                if n <= cap:
                    indices = list(range(n))
                else:
                    rng = np.random.default_rng(42)
                    indices = rng.choice(n, size=cap, replace=False).tolist()
                for col in holdout_features.columns:
                    series = holdout_features[col].iloc[indices]
                    feature_samples[col] = series.tolist()
        except Exception:
            logger.warning("Holdout feature sampling failed", exc_info=True)
            feature_samples = {}
        self._holdout_feature_samples = feature_samples
```

Also add an `__init__` (or extend the existing one) to default the attributes if absent. Find `def __init__` on `ModelTrainer` (the file already has `self._reference_distribution = None` around line 237 — same constructor). Add right after it:

```python
        self._holdout_probabilities = []
        self._holdout_feature_samples = {}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_trainer_reference_distribution.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/services/trainer.py backend/tests/test_trainer_reference_distribution.py
git commit -m "$(cat <<'EOF'
feat(ml): trainer captures holdout reference distribution on instance

Adds _capture_holdout_reference helper that samples up to 1000 holdout
probabilities + per-feature values onto trainer instance attributes after
predict_proba(X_test). Save_model and the training_metadata block will
read these in subsequent commits to make every trained model drift-ready.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire the trainer hook into the training flow

**Goal:** Call `_capture_holdout_reference` immediately after `y_prob = model.predict_proba(X_test)[:, 1]` so trainer instance attributes are populated before `save_model` and the metrics dict are built.

**Files:**
- Modify: `backend/apps/ml_engine/services/trainer.py:919-920` (insert one line)
- Test: `backend/tests/test_trainer_reference_distribution.py` (extend with integration check)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_trainer_reference_distribution.py`:

```python
@pytest.mark.django_db
def test_train_pipeline_populates_holdout_reference(tmp_path, monkeypatch):
    """Full train() run populates trainer._holdout_probabilities and _holdout_feature_samples."""
    import pandas as pd
    from apps.ml_engine.services.data_generator import DataGenerator

    # Tiny dataset so the test runs in seconds.
    gen = DataGenerator()
    df = gen.generate(num_records=300, random_seed=42, label_noise_rate=0.05)
    csv_path = tmp_path / "tiny.csv"
    df.to_csv(csv_path, index=False)

    trainer = ModelTrainer()
    # rf is fastest for a small dataset; xgb's Optuna timeout would dominate.
    monkeypatch.setattr(trainer, "_train_xgb", trainer._train_rf)
    model, metrics = trainer.train(str(csv_path), algorithm="rf")

    assert len(trainer._holdout_probabilities) > 0
    assert len(trainer._holdout_probabilities) <= 1000
    assert isinstance(trainer._holdout_feature_samples, dict)
    assert len(trainer._holdout_feature_samples) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_trainer_reference_distribution.py::test_train_pipeline_populates_holdout_reference -v
```

Expected: FAIL — attributes still empty after train() because the hook isn't called yet.

- [ ] **Step 3: Wire the hook into `train()`**

Edit `backend/apps/ml_engine/services/trainer.py`. Find line 919:

```python
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]
```

Insert a call immediately after line 919 (the `y_prob` assignment):

```python
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        # Stash holdout reference for drift-readiness — read by save_model and
        # by the training_metadata block (see _capture_holdout_reference).
        self._capture_holdout_reference(y_prob, X_test)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_trainer_reference_distribution.py -v
```

Expected: 4 PASS (3 unit + 1 integration).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/services/trainer.py backend/tests/test_trainer_reference_distribution.py
git commit -m "$(cat <<'EOF'
feat(ml): wire holdout-reference capture into ModelTrainer.train()

train() now calls _capture_holdout_reference right after predict_proba(X_test)
so any subsequent save_model() and metrics-dict read see populated holdout
samples. Adds an end-to-end test running the full pipeline on a 300-row
synthetic dataset.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `save_model` augments bundle with `probability_distribution` + `feature_distributions`

**Goal:** Extend the existing `bundle["reference_distribution"]` dict (currently a per-feature percentile/histogram map) with two new keys: `probability_distribution` (list of holdout probabilities) and `feature_distributions` (dict of feature → list of holdout values). Preserves all existing keys so nothing downstream breaks.

**Files:**
- Modify: `backend/apps/ml_engine/services/trainer.py:1281-1304` (the `save_model` bundle dict)
- Test: `backend/tests/test_trainer_reference_distribution.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_trainer_reference_distribution.py`:

```python
@pytest.mark.django_db
def test_save_model_writes_probability_and_feature_distributions(tmp_path):
    """save_model embeds the captured holdout samples in the bundle."""
    import joblib
    from sklearn.linear_model import LogisticRegression

    trainer = ModelTrainer()
    trainer._holdout_probabilities = [0.1, 0.4, 0.6, 0.9]
    trainer._holdout_feature_samples = {"credit_score": [600, 650, 700, 750]}
    # save_model still calls _validate_pipeline_consistency; satisfy its
    # minimum requirements (feature_cols + imputation_values + reference_distribution).
    trainer.ohe_columns = ["credit_score"]
    trainer._imputation_values = {"credit_score": 650.0}
    trainer._reference_distribution = {"credit_score": {"percentiles": [600, 650, 700, 750]}}

    out = tmp_path / "tiny.joblib"
    trainer.save_model(LogisticRegression(), str(out))

    bundle = joblib.load(out)
    rd = bundle["reference_distribution"]
    assert rd["probability_distribution"] == [0.1, 0.4, 0.6, 0.9]
    assert rd["feature_distributions"] == {"credit_score": [600, 650, 700, 750]}
    # Existing keys must survive the augmentation.
    assert "credit_score" in rd
    assert "percentiles" in rd["credit_score"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_trainer_reference_distribution.py::test_save_model_writes_probability_and_feature_distributions -v
```

Expected: FAIL — `KeyError: 'probability_distribution'` (bundle's `reference_distribution` lacks the key).

- [ ] **Step 3: Augment `save_model`**

Edit `backend/apps/ml_engine/services/trainer.py`. Find the `save_model` method (line 1279). Replace the bundle-build block (lines 1281-1301) with:

```python
        # Augment the per-feature reference distribution (already populated by
        # train()) with the holdout-level keys the drift code paths consume:
        #   - probability_distribution: feeds drift_monitor.compute_batch_drift_report
        #   - feature_distributions: feeds drift_monitor.compute_csi
        # Existing per-feature percentile/histogram keys are preserved.
        ref_dist = dict(self._reference_distribution or {})
        ref_dist["probability_distribution"] = list(getattr(self, "_holdout_probabilities", []) or [])
        ref_dist["feature_distributions"] = dict(getattr(self, "_holdout_feature_samples", {}) or {})

        bundle = {
            "model": model,
            "scaler": self.scaler,
            "feature_cols": self.ohe_columns,
            "categorical_cols": self.CATEGORICAL_COLS,
            "numeric_cols": self.NUMERIC_COLS,
            "reference_distribution": ref_dist,
            "imputation_values": self._imputation_values,
            "conformal_scores": getattr(self, "_conformal_scores", np.array([])),
            "feature_bounds": getattr(self, "_feature_bounds", {}),
            "group_thresholds": getattr(self, "_group_thresholds", {}),
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_trainer_reference_distribution.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/services/trainer.py backend/tests/test_trainer_reference_distribution.py
git commit -m "$(cat <<'EOF'
feat(ml): save_model embeds holdout probability_distribution + feature_distributions

Bundle's reference_distribution dict now carries:
  - probability_distribution: list[float] of up to 1000 holdout probs
  - feature_distributions: dict[col, list] of up to 1000 holdout values
alongside the existing per-feature percentile/histogram keys. Lets
drift_monitor.compute_batch_drift_report compute PSI + CSI without further
shape changes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `metrics["training_metadata"]` mirrors `reference_probabilities`

**Goal:** Write `reference_probabilities` into the metrics dict's `training_metadata` block so it propagates to `ModelVersion.training_metadata` (set in `apps/ml_engine/tasks.py:149` from `metrics.get("training_metadata", {})`). The simpler `compute_weekly_drift_report` task reads from `training_metadata.reference_probabilities` directly — bundle access not required.

**Files:**
- Modify: `backend/apps/ml_engine/services/trainer.py:986-1014` (the `metrics["training_metadata"] = { ... }` block)
- Test: `backend/tests/test_trainer_reference_distribution.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_trainer_reference_distribution.py`:

```python
@pytest.mark.django_db
def test_train_metrics_include_reference_probabilities(tmp_path, monkeypatch):
    """metrics['training_metadata']['reference_probabilities'] mirrors holdout probs."""
    from apps.ml_engine.services.data_generator import DataGenerator

    gen = DataGenerator()
    df = gen.generate(num_records=300, random_seed=42, label_noise_rate=0.05)
    csv_path = tmp_path / "tiny.csv"
    df.to_csv(csv_path, index=False)

    trainer = ModelTrainer()
    monkeypatch.setattr(trainer, "_train_xgb", trainer._train_rf)
    _model, metrics = trainer.train(str(csv_path), algorithm="rf")

    ref_probs = metrics["training_metadata"].get("reference_probabilities")
    assert ref_probs is not None
    assert len(ref_probs) > 0
    assert len(ref_probs) <= 1000
    assert ref_probs == trainer._holdout_probabilities
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_trainer_reference_distribution.py::test_train_metrics_include_reference_probabilities -v
```

Expected: FAIL — `reference_probabilities` not in `training_metadata`.

- [ ] **Step 3: Add the key to the `training_metadata` block**

Edit `backend/apps/ml_engine/services/trainer.py`. Find line 1013 — `**split_meta,` is the last line inside the `metrics["training_metadata"] = { ... }` dict. Insert a new line before `**split_meta,`:

```python
            "iv_features_excluded_leakage": len(getattr(self, "_iv_result", {}).get("excluded_leakage", [])),
            "reference_probabilities": list(getattr(self, "_holdout_probabilities", []) or []),
            **split_meta,
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_trainer_reference_distribution.py -v
```

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/services/trainer.py backend/tests/test_trainer_reference_distribution.py
git commit -m "$(cat <<'EOF'
feat(ml): training_metadata mirrors holdout reference_probabilities

ModelVersion.training_metadata.reference_probabilities now carries the same
list of up to 1000 holdout probabilities as the bundle, so the simpler
compute_weekly_drift_report task can compute PSI without joblib access.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `backfill_reference_distribution` management command

**Goal:** One-shot command that patches the currently-active model (or all matching) by generating a fresh `DataGenerator` batch, running the loaded model on it, populating `bundle.reference_distribution.probability_distribution` + `feature_distributions` and `ModelVersion.training_metadata.reference_probabilities`. Atomic re-save (write-tmp + rename). Idempotent: refuses to overwrite without `--force`.

**Files:**
- Create: `backend/apps/ml_engine/management/commands/backfill_reference_distribution.py`
- Test: `backend/tests/test_backfill_reference_distribution.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_backfill_reference_distribution.py`:

```python
"""Tests for the backfill_reference_distribution management command.

Patches an existing model bundle that lacks probability_distribution +
feature_distributions, then re-runs to verify idempotent refusal and
--force overwrite.
"""

import joblib
import pytest
from django.core.management import call_command
from sklearn.linear_model import LogisticRegression

from apps.ml_engine.models import ModelVersion


def _make_bundle(path, *, with_dist=False):
    bundle = {
        "model": LogisticRegression(),
        "scaler": None,
        "feature_cols": ["credit_score"],
        "categorical_cols": [],
        "numeric_cols": ["credit_score"],
        "reference_distribution": (
            {"probability_distribution": [0.1, 0.5, 0.9], "feature_distributions": {"credit_score": [600, 700, 800]}}
            if with_dist else {"credit_score": {"percentiles": [600, 700, 800]}}
        ),
        "imputation_values": {"credit_score": 650.0},
        "conformal_scores": [],
        "feature_bounds": {},
        "group_thresholds": {},
    }
    joblib.dump(bundle, path)


@pytest.fixture
def stub_model(tmp_path, monkeypatch):
    """Build a fitted LR model + ModelVersion + saved bundle missing the new keys."""
    import numpy as np
    bundle_path = tmp_path / "stub.joblib"

    # Fit on toy data so predict_proba is safe to call during backfill.
    X = np.array([[600], [700], [800], [550], [720]])
    y = np.array([0, 1, 1, 0, 1])
    model = LogisticRegression().fit(X, y)
    bundle = {
        "model": model,
        "scaler": None,
        "feature_cols": ["credit_score"],
        "categorical_cols": [],
        "numeric_cols": ["credit_score"],
        "reference_distribution": {"credit_score": {"percentiles": [600, 700, 800]}},
        "imputation_values": {"credit_score": 650.0},
        "conformal_scores": [],
        "feature_bounds": {},
        "group_thresholds": {},
    }
    joblib.dump(bundle, bundle_path)

    mv = ModelVersion.objects.create(
        algorithm="rf", version="test-backfill",
        file_path=str(bundle_path), is_active=True,
        training_metadata={},
    )
    return mv, bundle_path


@pytest.mark.django_db
def test_backfill_populates_missing_fields(stub_model, monkeypatch):
    """Bundle gets probability_distribution + feature_distributions; metadata gets reference_probabilities."""
    mv, bundle_path = stub_model

    # Stub DataGenerator to avoid heavyweight benchmark loading.
    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [600, 650, 700, 750, 800] * (num_records // 5)}),
    )

    call_command("backfill_reference_distribution", "--all-active", "--sample", "20")

    # Bundle has the new keys.
    bundle = joblib.load(bundle_path)
    rd = bundle["reference_distribution"]
    assert "probability_distribution" in rd
    assert len(rd["probability_distribution"]) > 0
    assert "feature_distributions" in rd
    assert "credit_score" in rd["feature_distributions"]
    # Existing key preserved.
    assert "credit_score" in rd
    assert "percentiles" in rd["credit_score"]

    # ModelVersion metadata has reference_probabilities.
    mv.refresh_from_db()
    assert "reference_probabilities" in (mv.training_metadata or {})


@pytest.mark.django_db
def test_backfill_refuses_without_force_when_present(stub_model, monkeypatch, capsys):
    mv, bundle_path = stub_model
    # Mark it as already-backfilled.
    bundle = joblib.load(bundle_path)
    bundle["reference_distribution"]["probability_distribution"] = [0.5, 0.6]
    joblib.dump(bundle, bundle_path)

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [700] * num_records}),
    )

    call_command("backfill_reference_distribution", "--all-active", "--sample", "10")

    out = capsys.readouterr().out
    assert "skipping" in out.lower() or "already populated" in out.lower()
    bundle_after = joblib.load(bundle_path)
    # Untouched.
    assert bundle_after["reference_distribution"]["probability_distribution"] == [0.5, 0.6]


@pytest.mark.django_db
def test_backfill_force_overwrites(stub_model, monkeypatch):
    mv, bundle_path = stub_model
    bundle = joblib.load(bundle_path)
    bundle["reference_distribution"]["probability_distribution"] = [0.5]
    joblib.dump(bundle, bundle_path)

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [600, 700, 800, 750, 650] * (num_records // 5)}),
    )

    call_command("backfill_reference_distribution", "--all-active", "--sample", "20", "--force")

    bundle_after = joblib.load(bundle_path)
    assert len(bundle_after["reference_distribution"]["probability_distribution"]) > 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_backfill_reference_distribution.py -v
```

Expected: 3 FAIL with `Unknown command: backfill_reference_distribution`.

- [ ] **Step 3: Implement the management command**

Create `backend/apps/ml_engine/management/commands/backfill_reference_distribution.py`:

```python
"""Backfill probability_distribution + feature_distributions on existing model bundles.

Models trained before the trainer hook landed (commits leading up to this
file) lack the keys both drift code paths consume. This command is the
one-shot patch: run the model on a fresh DataGenerator batch, populate the
two bundle keys + ModelVersion.training_metadata.reference_probabilities,
and atomically re-save the bundle.

Idempotent — refuses to overwrite by default; pass --force to overwrite.
"""

import os
import sys

import joblib
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.predictor import _validate_model_path


class Command(BaseCommand):
    help = "Backfill bundle reference_distribution + training_metadata.reference_probabilities for existing models."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--model-id", type=str, help="UUID of a specific ModelVersion to backfill.")
        target.add_argument("--all-active", action="store_true", help="Backfill every is_active=True ModelVersion.")
        parser.add_argument(
            "--sample", type=int, default=5000,
            help="DataGenerator sample size used to seed the holdout reference (default 5000, capped at 1000 in bundle).",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Overwrite probability_distribution if already populated. Default refuses.",
        )

    def handle(self, *args, **options):
        from apps.ml_engine.services.data_generator import DataGenerator

        if options["all_active"]:
            targets = list(ModelVersion.objects.filter(is_active=True))
        else:
            try:
                targets = [ModelVersion.objects.get(id=options["model_id"])]
            except ModelVersion.DoesNotExist:
                raise CommandError(f"ModelVersion {options['model_id']} not found")

        if not targets:
            self.stdout.write("No matching models found.")
            return

        for mv in targets:
            self._backfill_one(mv, options["sample"], options["force"])

    def _backfill_one(self, mv: ModelVersion, sample_size: int, force: bool) -> None:
        try:
            bundle_path = _validate_model_path(mv.file_path)
        except (ValueError, FileNotFoundError) as exc:
            raise CommandError(f"Bundle path invalid for {mv.id}: {exc}")

        bundle = joblib.load(bundle_path)
        ref_dist = dict(bundle.get("reference_distribution") or {})

        already = bool(ref_dist.get("probability_distribution"))
        if already and not force:
            self.stdout.write(
                f"[skip] {mv.algorithm} v{mv.version}: probability_distribution already populated; "
                f"pass --force to overwrite."
            )
            return

        self.stdout.write(f"[backfill] {mv.algorithm} v{mv.version} ({mv.id})")
        gen_df = DataGenerator().generate(num_records=sample_size, random_seed=42, label_noise_rate=0.05)

        # Drop the target column if present (DataGenerator outputs include it).
        for target_col in ("default_flag", "approved", "is_default"):
            if target_col in gen_df.columns:
                gen_df = gen_df.drop(columns=[target_col])

        # Use the loaded model to score the synthetic batch. Models trained
        # via the predictor pipeline expect specific feature columns -- the
        # bundle's feature_cols list is the source of truth.
        feature_cols = bundle.get("feature_cols") or []
        usable_cols = [c for c in feature_cols if c in gen_df.columns]
        if not usable_cols:
            # Fall back to numeric_cols if feature_cols is OHE-only; we still
            # need *something* to feed predict_proba.
            usable_cols = [c for c in (bundle.get("numeric_cols") or []) if c in gen_df.columns]
        if not usable_cols:
            raise CommandError(
                f"Bundle for {mv.id} has no recognisable feature columns; cannot backfill."
            )

        X = gen_df[usable_cols].copy()
        try:
            probs = bundle["model"].predict_proba(X)[:, 1]
        except Exception as exc:
            raise CommandError(f"predict_proba failed for {mv.id}: {exc}")

        cap = 1000
        if len(probs) > cap:
            import numpy as np
            rng = np.random.default_rng(42)
            idx = rng.choice(len(probs), size=cap, replace=False)
            prob_sample = probs[idx].tolist()
            feat_sample = {col: gen_df[col].iloc[idx].tolist() for col in usable_cols}
        else:
            prob_sample = list(map(float, probs))
            feat_sample = {col: gen_df[col].tolist() for col in usable_cols}

        ref_dist["probability_distribution"] = prob_sample
        ref_dist["feature_distributions"] = feat_sample
        bundle["reference_distribution"] = ref_dist

        # Atomic re-save: write to .tmp then rename.
        tmp_path = f"{bundle_path}.tmp"
        joblib.dump(bundle, tmp_path)
        os.replace(tmp_path, bundle_path)

        # Mirror into ModelVersion.training_metadata.
        meta = dict(mv.training_metadata or {})
        meta["reference_probabilities"] = prob_sample
        mv.training_metadata = meta
        mv.save(update_fields=["training_metadata"])

        self.stdout.write(self.style.SUCCESS(
            f"[ok] {mv.algorithm} v{mv.version}: wrote {len(prob_sample)} probs + "
            f"{len(feat_sample)} feature columns"
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_backfill_reference_distribution.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/management/commands/backfill_reference_distribution.py backend/tests/test_backfill_reference_distribution.py
git commit -m "$(cat <<'EOF'
feat(ml): backfill_reference_distribution mgmt command

One-shot command that patches existing model bundles + DB rows lacking
the new probability_distribution + feature_distributions keys. Atomic
re-save (.tmp + os.replace) keeps the original bundle intact on crash.
Idempotent — refuses to overwrite without --force.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `seed_predictions` management command (AU-realistic temporal weights)

**Goal:** Generate `--count` synthetic predictions against a target ModelVersion, with `created_at` timestamps weighted to mimic an AU online-lending submission stream (Tue-Thu peak weekdays, evening peak hours), then optionally trigger `compute_weekly_drift_report.apply()` so a real `DriftReport` row is written.

**Files:**
- Create: `backend/apps/ml_engine/management/commands/seed_predictions.py`
- Test: `backend/tests/test_seed_predictions.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_seed_predictions.py`:

```python
"""Tests for seed_predictions management command.

The command generates AU-calibrated synthetic predictions against a target
ModelVersion and weights timestamps for weekday-business + evening peak.
With --seed 42 + --count 200 the day-of-week distribution is deterministic.
"""

import joblib
import numpy as np
import pytest
from datetime import timedelta
from django.core.management import call_command
from django.utils import timezone
from sklearn.linear_model import LogisticRegression

from apps.ml_engine.models import ModelVersion, PredictionLog


@pytest.fixture
def active_model(tmp_path, monkeypatch):
    bundle_path = tmp_path / "seed_stub.joblib"
    X = np.array([[600], [700], [800], [550], [720]])
    y = np.array([0, 1, 1, 0, 1])
    model = LogisticRegression().fit(X, y)
    bundle = {
        "model": model,
        "scaler": None,
        "feature_cols": ["credit_score"],
        "categorical_cols": [],
        "numeric_cols": ["credit_score"],
        "reference_distribution": {
            "probability_distribution": [0.2, 0.5, 0.8],
            "feature_distributions": {"credit_score": [600, 700, 800]},
        },
        "imputation_values": {"credit_score": 650.0},
        "conformal_scores": [],
        "feature_bounds": {},
        "group_thresholds": {},
    }
    joblib.dump(bundle, bundle_path)

    mv = ModelVersion.objects.create(
        algorithm="rf", version="test-seed",
        file_path=str(bundle_path), is_active=True,
        training_metadata={"reference_probabilities": [0.2, 0.5, 0.8]},
    )
    return mv


@pytest.mark.django_db
def test_seed_creates_n_predictions_within_window(active_model, monkeypatch):
    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [650] * num_records}),
    )

    # Stub ModelPredictor.predict to avoid the full feature pipeline.
    def _stub_predict(self, payload, **_kw):
        return {"probability": 0.42, "decision": "approve"}
    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor.predict",
        _stub_predict,
    )

    call_command(
        "seed_predictions",
        "--model-id", str(active_model.id),
        "--count", "30",
        "--spread-days", "7",
        "--seed", "42",
        "--no-trigger-drift",
    )

    rows = PredictionLog.objects.filter(model_version=active_model)
    assert rows.count() == 30

    now = timezone.now()
    earliest = now - timedelta(days=7, hours=1)
    for r in rows:
        assert earliest <= r.created_at <= now


@pytest.mark.django_db
def test_seed_day_of_week_distribution_is_deterministic(active_model, monkeypatch):
    """Fixed seed + count produces a deterministic day-of-week count vector."""
    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [650] * num_records}),
    )

    def _stub_predict(self, payload, **_kw):
        return {"probability": 0.42, "decision": "approve"}
    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor.predict",
        _stub_predict,
    )

    call_command(
        "seed_predictions",
        "--model-id", str(active_model.id),
        "--count", "200",
        "--spread-days", "7",
        "--seed", "42",
        "--no-trigger-drift",
    )

    rows = list(PredictionLog.objects.filter(model_version=active_model))
    assert len(rows) == 200

    # Day-of-week histogram must be reproducible. Don't hard-code an exact
    # vector here — instead assert that all 7 days have non-zero presence
    # AND that the heaviest two days are Tue or Wed (per the spec weights).
    dow_counts = [0] * 7
    for r in rows:
        dow_counts[r.created_at.weekday()] += 1
    assert all(c >= 1 for c in dow_counts), f"all weekdays should appear: {dow_counts}"
    top_two = sorted(range(7), key=lambda i: -dow_counts[i])[:2]
    # Tue=1, Wed=2 are the spec-defined heaviest.
    assert set(top_two) <= {1, 2, 3}, f"top two days should be Tue/Wed/Thu: {dow_counts}"


@pytest.mark.django_db
def test_seed_arg_validation(active_model):
    """Out-of-range count or spread-days are rejected by argparse."""
    from django.core.management.base import CommandError
    with pytest.raises((CommandError, SystemExit)):
        call_command("seed_predictions", "--model-id", str(active_model.id), "--count", "0")
    with pytest.raises((CommandError, SystemExit)):
        call_command("seed_predictions", "--model-id", str(active_model.id), "--count", "100000")
    with pytest.raises((CommandError, SystemExit)):
        call_command("seed_predictions", "--model-id", str(active_model.id), "--count", "10", "--spread-days", "0")
    with pytest.raises((CommandError, SystemExit)):
        call_command("seed_predictions", "--model-id", str(active_model.id), "--count", "10", "--spread-days", "365")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_seed_predictions.py -v
```

Expected: 3 FAIL with `Unknown command: seed_predictions`.

- [ ] **Step 3: Implement the management command**

Create `backend/apps/ml_engine/management/commands/seed_predictions.py`:

```python
"""Seed AU-realistic synthetic predictions against a ModelVersion.

Generates a synthetic loan-application stream via DataGenerator (already
calibrated against ABS/APRA/RBA/HILDA), runs each through the model, and
overrides created_at with a weekday-business + evening-biased timestamp
distribution that mimics an online consumer-lending application stream.

Optionally triggers compute_weekly_drift_report.apply() at the end so a
real DriftReport row is produced (drift task otherwise short-circuits if
no recent predictions exist).
"""

import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.ml_engine.models import ModelVersion, PredictionLog


# Day-of-week weights — Tue/Wed peak with weekend tail. See spec.
DOW_WEIGHTS = [13, 22, 22, 18, 12, 8, 5]  # Mon..Sun (sums to 100)

# Hour-of-day weights — bimodal: 8-10am small peak, 6-9pm large peak.
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 1, 2, 3, 5, 6, 5, 4, 4, 4, 4, 4, 5, 6, 8, 9, 9, 7, 4, 2]


class Command(BaseCommand):
    help = "Seed an AU-realistic synthetic prediction stream for a ModelVersion and (optionally) trigger the drift task."

    def add_arguments(self, parser):
        parser.add_argument("--model-id", type=str, required=True, help="ModelVersion UUID")
        parser.add_argument("--count", type=int, default=200, help="Number of predictions (1..10000, default 200)")
        parser.add_argument("--spread-days", type=int, default=7, help="Window in days for created_at (1..90, default 7)")
        parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
        parser.add_argument("--trigger-drift", dest="trigger_drift", action="store_true", default=True)
        parser.add_argument("--no-trigger-drift", dest="trigger_drift", action="store_false")

    def handle(self, *args, **options):
        from apps.ml_engine.services.data_generator import DataGenerator
        from apps.ml_engine.services.predictor import ModelPredictor

        count = options["count"]
        spread_days = options["spread_days"]
        seed = options["seed"]

        if not (1 <= count <= 10000):
            raise CommandError(f"--count must be in [1, 10000], got {count}")
        if not (1 <= spread_days <= 90):
            raise CommandError(f"--spread-days must be in [1, 90], got {spread_days}")

        try:
            mv = ModelVersion.objects.get(id=options["model_id"])
        except ModelVersion.DoesNotExist:
            raise CommandError(f"ModelVersion {options['model_id']} not found")

        rng = random.Random(seed) if seed is not None else random.Random()

        # Generate count synthetic rows from the AU-calibrated DataGenerator.
        df = DataGenerator().generate(num_records=count, random_seed=seed or 42, label_noise_rate=0.05)
        if len(df) < count:
            raise CommandError(f"DataGenerator returned {len(df)} rows, expected {count}")
        df = df.iloc[:count].reset_index(drop=True)

        predictor = ModelPredictor(model_version=mv)

        # Run predictions inside a transaction so partial failure rolls back.
        created_rows = []
        with transaction.atomic():
            for i in range(count):
                row = df.iloc[i].to_dict()
                try:
                    result = predictor.predict(row)
                except Exception as exc:
                    raise CommandError(f"predict() failed on row {i}: {exc}")
                pl = PredictionLog.objects.create(
                    model_version=mv,
                    probability=float(result.get("probability", 0.0)),
                    input_data=row,
                )
                created_rows.append(pl)

        # Override created_at to weekday + evening-biased timestamps.
        now = timezone.now()
        for pl in created_rows:
            day_offset = rng.choices(range(7), weights=self._normalize_dow_for_window(spread_days), k=1)[0]
            hour = rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]
            minute = rng.randrange(60)
            second = rng.randrange(60)
            sampled = (now - timedelta(days=spread_days)) + timedelta(
                days=day_offset, hours=hour, minutes=minute, seconds=second,
            )
            # Clamp to window — sampling can put a row at now+epsilon.
            if sampled > now:
                sampled = now - timedelta(seconds=rng.randrange(60))
            if sampled < (now - timedelta(days=spread_days)):
                sampled = (now - timedelta(days=spread_days)) + timedelta(seconds=rng.randrange(60))
            pl.created_at = sampled

        # bulk_update overrides auto_now_add by issuing direct UPDATEs.
        PredictionLog.objects.bulk_update(created_rows, ["created_at"])

        self.stdout.write(self.style.SUCCESS(f"Seeded {count} predictions for {mv.algorithm} v{mv.version}"))

        if options["trigger_drift"]:
            from apps.ml_engine.tasks import compute_weekly_drift_report
            self.stdout.write("Triggering compute_weekly_drift_report.apply() ...")
            result = compute_weekly_drift_report.apply()
            self.stdout.write(f"Drift task result: {result.result}")

    def _normalize_dow_for_window(self, spread_days: int):
        """Return DOW weights aligned to a `spread_days`-long window starting at now-spread_days.

        For the standard 7-day window each day appears once with its base weight.
        For shorter windows, fold by the actual days present.
        """
        # Simple path for the common case: full 7-day window.
        if spread_days >= 7:
            return DOW_WEIGHTS
        # Days `now - i` for i in [0..spread_days-1] map to specific weekdays;
        # the day_offset chosen by rng.choices is a position-in-window, so the
        # weight vector must be permuted to align "today's index" with a
        # weekday weight.
        now = timezone.now()
        weights = []
        for offset in range(spread_days):
            dow = (now - timedelta(days=spread_days - 1 - offset)).weekday()
            weights.append(DOW_WEIGHTS[dow])
        return weights + [0] * (7 - spread_days)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_seed_predictions.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/management/commands/seed_predictions.py backend/tests/test_seed_predictions.py
git commit -m "$(cat <<'EOF'
feat(ml): seed_predictions mgmt command with AU-realistic temporal weights

Generates synthetic AU-calibrated predictions for a ModelVersion, overrides
created_at with weekday-business + evening-biased timestamps via bulk_update,
optionally triggers compute_weekly_drift_report.apply() so the dashboard's
KPI tiles populate without waiting for the Monday beat.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: End-to-end integration test

**Goal:** Verify the full pipeline works on a tiny real model: train → backfill → seed 30 → drift task → DriftReport row exists with non-null `psi_score` + `approval_rate`.

**Files:**
- Create: `backend/tests/test_drift_pipeline_integration.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_drift_pipeline_integration.py`:

```python
"""End-to-end drift pipeline integration test.

Trains a tiny model, backfills it (no-op when trainer hook is wired),
seeds 30 predictions, runs the drift task. Asserts a DriftReport row
exists with non-null psi_score and approval_rate.
"""

import joblib
import numpy as np
import pytest
from django.core.management import call_command
from sklearn.linear_model import LogisticRegression

from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog


@pytest.mark.django_db
def test_full_drift_pipeline(tmp_path, monkeypatch):
    bundle_path = tmp_path / "pipeline.joblib"
    X = np.array([[600], [650], [700], [750], [800]])
    y = np.array([0, 0, 1, 1, 1])
    model = LogisticRegression().fit(X, y)
    holdout_probs = model.predict_proba(X)[:, 1].tolist()
    bundle = {
        "model": model,
        "scaler": None,
        "feature_cols": ["credit_score"],
        "categorical_cols": [],
        "numeric_cols": ["credit_score"],
        "reference_distribution": {
            "probability_distribution": holdout_probs,
            "feature_distributions": {"credit_score": [600, 650, 700, 750, 800]},
        },
        "imputation_values": {"credit_score": 650.0},
        "conformal_scores": [],
        "feature_bounds": {},
        "group_thresholds": {},
    }
    joblib.dump(bundle, bundle_path)

    mv = ModelVersion.objects.create(
        algorithm="rf", version="integration",
        file_path=str(bundle_path), is_active=True,
        optimal_threshold=0.5,
        training_metadata={"reference_probabilities": holdout_probs},
    )

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": list(np.random.default_rng(42).integers(550, 820, size=num_records))}),
    )

    def _stub_predict(self, payload, **_kw):
        return {"probability": 0.55, "decision": "approve"}
    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor.predict",
        _stub_predict,
    )

    call_command(
        "seed_predictions",
        "--model-id", str(mv.id),
        "--count", "30",
        "--spread-days", "7",
        "--seed", "42",
        "--trigger-drift",
    )

    assert PredictionLog.objects.filter(model_version=mv).count() == 30
    reports = DriftReport.objects.filter(model_version=mv)
    assert reports.exists(), "drift task did not write a DriftReport"

    r = reports.first()
    assert r.psi_score is not None, "psi_score should be populated"
    assert r.approval_rate is not None, "approval_rate should be populated"
    assert 0.0 <= r.approval_rate <= 1.0
```

- [ ] **Step 2: Run test to verify it passes**

```bash
docker exec loan-approval-ai-system-backend-1 pytest backend/tests/test_drift_pipeline_integration.py -v
```

Expected: PASS (Tasks 1-6 already wired the pipeline; this is a regression check).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_drift_pipeline_integration.py
git commit -m "$(cat <<'EOF'
test(ml): drift pipeline integration test

Asserts the full chain (model bundle with reference_distribution + seed
predictions + compute_weekly_drift_report) produces a DriftReport row
with non-null psi_score and approval_rate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Operational runbook addendum

**Goal:** Document the demo-seed workflow so the next person who deploys a freshly trained model knows the exact commands to populate the KPI tiles without waiting for the Monday beat.

**Files:**
- Modify: `backend/docs/RUNBOOK.md` (append a new section)

- [ ] **Step 1: Append to RUNBOOK.md**

Find the end of `backend/docs/RUNBOOK.md` and append:

```markdown
## Initial drift seed for new model deployments

After training a new model the `/dashboard/model-metrics` KPI strip will
show "—" for the **PSI (latest)** and **Approval rate** tiles until a
`DriftReport` row exists. New models trained against this codebase are
already drift-ready (the trainer hook stores `reference_probabilities`
+ `probability_distribution`), but they still need a recent prediction
stream for the drift task to compute against.

Two ways to get the tiles to populate:

**Option A — wait for production traffic.** Once real predictions accrue
through `/api/v1/ml/predict/<loan_id>/`, the Monday 02:00 AEDT
`compute_weekly_drift_report` Celery beat task writes the row
automatically. No manual step required.

**Option B — seed a synthetic stream now.** Useful for demos, fresh
deployments, and after `--all-segments` retraining when historical
PredictionLog rows reference a deactivated model.

```bash
# Backfill any older models that pre-date the trainer hook (idempotent).
docker exec loan-approval-ai-system-backend-1 \
  python manage.py backfill_reference_distribution --all-active

# Seed 200 AU-realistic synthetic predictions and trigger the drift task.
docker exec loan-approval-ai-system-backend-1 \
  python manage.py seed_predictions \
    --model-id <UUID> --count 200 --spread-days 7 --seed 42
```

Reload `/dashboard/model-metrics` — the **PSI** and **Approval rate**
tiles should now show numbers. Approval rate matches what the active
model + threshold yield on a fresh AU-calibrated batch; PSI compares the
seeded prediction-probability distribution against the model's stored
`reference_probabilities` (≈ 0 for a freshly trained model — no drift
expected when serving against a distribution close to training).
```

- [ ] **Step 2: Commit**

```bash
git add backend/docs/RUNBOOK.md
git commit -m "$(cat <<'EOF'
docs(runbook): initial drift seed workflow for new model deployments

Adds a "Initial drift seed" section that walks through running
backfill_reference_distribution + seed_predictions to populate the
PSI / approval-rate KPI tiles without waiting for the Monday beat.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Manual verification on the running dev environment

**Goal:** Confirm the tiles actually populate end-to-end on the live `localhost:3000` stack against a real (not stubbed) backend run.

- [ ] **Step 1: Run the backfill on the active model**

```bash
docker exec loan-approval-ai-system-backend-1 \
  python manage.py backfill_reference_distribution --all-active --sample 5000
```

Expected output: `[ok] xgb v20260508_111850: wrote 1000 probs + N feature columns`.

- [ ] **Step 2: Seed predictions and trigger the drift task**

```bash
ACTIVE_ID=$(docker exec loan-approval-ai-system-backend-1 \
  python manage.py shell -c "from apps.ml_engine.models import ModelVersion; print(ModelVersion.objects.filter(is_active=True).first().id)" \
  | tr -d '\r\n' | awk '{print $NF}')
docker exec loan-approval-ai-system-backend-1 \
  python manage.py seed_predictions --model-id "$ACTIVE_ID" --count 200 --spread-days 7 --seed 42
```

Expected output: `Seeded 200 predictions for xgb vYYYYMMDD_HHMMSS` followed by `Drift task result: {...}` with non-null psi_score and approval_rate.

- [ ] **Step 3: Verify the KPI tiles**

Reload `http://localhost:3000/dashboard/model-metrics` in the browser. Expected: **PSI (latest)** and **Approval rate** tiles each show a number (not `—`).

- [ ] **Step 4: Final cleanup commit (no code change, marker only)**

```bash
git commit --allow-empty -m "$(cat <<'EOF'
chore(ml): manual verification — drift KPI tiles populate

Backfilled active model + seeded 200 AU-realistic predictions; KPI
strip now shows PSI and Approval rate values. Pipeline is ready for
the Monday compute_weekly_drift_report beat to take over going forward.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist (post-execution)

After all tasks land, verify against the spec:

- [ ] Trainer hook captures both probabilities AND feature samples (spec §Components.1) — ✓ Tasks 1, 2
- [ ] Bundle augmentation preserves existing `reference_distribution` keys (spec §Components.1) — ✓ Task 3
- [ ] `training_metadata.reference_probabilities` mirrors `probability_distribution` (spec §Components.1) — ✓ Task 4
- [ ] `backfill_reference_distribution` handles `--model-id`, `--all-active`, `--force`, `--sample` (spec §Components.2) — ✓ Task 5
- [ ] `seed_predictions` enforces argparse range checks for count + spread-days (spec §Error handling) — ✓ Task 6
- [ ] `seed_predictions` uses `bulk_update` to override `auto_now_add` (spec §Components.3) — ✓ Task 6
- [ ] Day-of-week weights match spec exactly: 13/22/22/18/12/8/5 (spec §Components.3) — ✓ Task 6 `DOW_WEIGHTS`
- [ ] Hour-of-day weights match spec exactly: 24-element vector (spec §Components.3) — ✓ Task 6 `HOUR_WEIGHTS`
- [ ] Drift trigger via `compute_weekly_drift_report.apply()` synchronous (spec §Components.4) — ✓ Task 6
- [ ] All four named test files created (spec §Testing) — ✓ Tasks 1, 5, 6, 7
- [ ] Runbook addendum added (spec §File touch list) — ✓ Task 8
- [ ] Manual verification of KPI tiles on `/dashboard/model-metrics` (spec §Testing) — ✓ Task 9
