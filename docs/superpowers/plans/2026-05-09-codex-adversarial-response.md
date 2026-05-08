# Codex Adversarial Review Response Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three Codex adversarial-review findings: dossier reading the wrong calibration field, trainer not mirroring `psi_by_feature` into `training_metadata`, advisory gate-mode defaults letting non-compliant models activate, and a stale `next-env.d.ts` hand-edit.

**Architecture:** Seven small atomic deliverables in `backend/apps/ml_engine`, `backend/config/settings`, `backend/docs`, and `frontend/`. Trainer change is a single new key inside the existing `metrics["training_metadata"]` block. Dossier change is a single field-lookup correction. Gate-mode flip is three default-value edits in `settings/base.py`. Backfill command mirrors the structure of the existing `backfill_reference_distribution` command. Frontend change is a one-file revert. RUNBOOK addendum is documentation only.

**Tech Stack:** Django + DRF, scikit-learn / XGBoost via existing `ModelTrainer`, joblib bundles, `apps.ml_engine.services.metrics.psi_by_feature` helper, pytest + pytest-django. Frontend: Next.js 16 (Turbopack).

**Spec:** [`docs/superpowers/specs/2026-05-09-codex-adversarial-response-design.md`](../specs/2026-05-09-codex-adversarial-response-design.md)

**Branch:** `feat/codex-adversarial-response` (already checked out, forked from `feat/drift-tiles-fix` which is open as PR #182). The spec commit is also on `feat/drift-tiles-fix` HEAD; if PR #182 is squash-merged or merged-with-merge-commit, the spec history flows naturally into master either way.

**Tests:** `docker exec loan-approval-ai-system-backend-1 python -m pytest tests/<path> -v` (container `/app` workdir maps to host `backend/`).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/apps/ml_engine/services/mrm_dossier.py` | MODIFY | `_calibration_section` now reads `mv.decile_analysis["deciles"]` first, falls back to legacy `calibration_data` keys. |
| `backend/apps/ml_engine/services/trainer.py` | MODIFY | Mirror `psi_by_feature` into `metrics["training_metadata"]` so it lands on `ModelVersion.training_metadata`. |
| `backend/apps/ml_engine/management/commands/backfill_psi_by_feature.py` | NEW | One-shot patch: load bundle, generate fresh DataGenerator batch, compute per-feature PSI vs the bundle's stored `feature_distributions`, write into `mv.training_metadata.psi_by_feature`. Idempotent. |
| `backend/config/settings/base.py` | MODIFY | Default `CREDIT_POLICY_OVERLAY_MODE=enforce`, `ML_FAIRNESS_GATE_MODE=block`, `ML_PROMOTION_GATE_MODE=block`. Env-var override semantics preserved. |
| `frontend/next-env.d.ts` | MODIFY | Revert to standard Next-generated content (no dev-only routes import). |
| `backend/docs/RUNBOOK.md` | MODIFY | Append "Strict gate defaults — when and how to relax" section. |
| `backend/tests/test_mrm_dossier_calibration.py` | NEW | Unit test: dossier renders deciles when `mv.decile_analysis.deciles` is populated. |
| `backend/tests/test_trainer_psi_mirror.py` | NEW | Unit test: trainer copies `psi_by_feature` into `metrics["training_metadata"]`. |
| `backend/tests/test_backfill_psi_by_feature.py` | NEW | 3 tests: populates / refuses-without-force / force-overwrites. |
| `backend/tests/test_settings_strict_gate_defaults.py` | NEW | Asserts default gate modes when no env vars set. |

---

## Task 1: Dossier reads deciles from `mv.decile_analysis`

**Goal:** Fix the wrong-field-lookup bug. The dossier currently checks `mv.calibration_data["deciles"]`; deciles actually live at `mv.decile_analysis["deciles"]` (a separate JSONField on `ModelVersion`).

**Files:**
- Modify: `backend/apps/ml_engine/services/mrm_dossier.py` (the `_calibration_section` function near line 231)
- Test: `backend/tests/test_mrm_dossier_calibration.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_mrm_dossier_calibration.py`:

```python
"""Tests for the MRM dossier's calibration section path lookup.

Regression: the dossier used to read `mv.calibration_data["deciles"]` but
deciles live on a separate `mv.decile_analysis` JSONField. Fix preserves
fallback for legacy bundles that stored deciles inside calibration_data.
"""

import pytest
from types import SimpleNamespace

from apps.ml_engine.services.mrm_dossier import _calibration_section


def _stub_mv(decile_analysis=None, calibration_data=None):
    return SimpleNamespace(
        decile_analysis=decile_analysis or {},
        calibration_data=calibration_data or {},
    )


def test_calibration_reads_decile_analysis_field():
    """When deciles are on mv.decile_analysis (current trainer output)."""
    deciles = [
        {"decile": 1, "n": 100, "actual_default_rate": 0.02, "predicted_default_rate": 0.018},
        {"decile": 2, "n": 100, "actual_default_rate": 0.05, "predicted_default_rate": 0.048},
    ]
    mv = _stub_mv(decile_analysis={"deciles": deciles})
    section = _calibration_section(mv)
    assert "Decile calibration not recorded" not in section
    assert "0.02" in section or "2.0%" in section or "0.018" in section


def test_calibration_falls_back_to_calibration_data_deciles():
    """Legacy bundles where deciles were nested under calibration_data."""
    deciles = [{"decile": 1, "n": 100, "actual_default_rate": 0.01, "predicted_default_rate": 0.012}]
    mv = _stub_mv(calibration_data={"deciles": deciles})
    section = _calibration_section(mv)
    assert "Decile calibration not recorded" not in section


def test_calibration_empty_state_when_no_deciles():
    """Both fields empty/absent → empty-state line."""
    mv = _stub_mv()
    section = _calibration_section(mv)
    assert "Decile calibration not recorded" in section
    assert "decile_analysis.deciles" in section  # new canonical path in the message
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
docker exec loan-approval-ai-system-backend-1 python -m pytest tests/test_mrm_dossier_calibration.py -v
```

Expected: `test_calibration_reads_decile_analysis_field` FAIL (the dossier doesn't read from `decile_analysis`); `test_calibration_empty_state_when_no_deciles` FAIL (the empty-state message doesn't yet mention the canonical path).

- [ ] **Step 3: Apply the fix**

Edit `backend/apps/ml_engine/services/mrm_dossier.py`. Find `def _calibration_section(mv)` (around line 231). Replace its body's lookup chain + empty-state message:

```python
def _calibration_section(mv) -> str:
    """§6 — Calibration report (decile table)."""
    decile_analysis = mv.decile_analysis or {}
    calibration = mv.calibration_data or {}
    deciles = (
        decile_analysis.get("deciles")
        or calibration.get("deciles")
        or calibration.get("decile_analysis")
        or []
    )
    if not deciles:
        return (
            "## 6. Calibration report\n\n"
            "Decile calibration not recorded. Re-train with v1.9.0+ trainer which "
            "emits `decile_analysis.deciles` on every run."
        )
```

The rest of the function (the part that builds the table once `deciles` is non-empty) stays unchanged.

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec loan-approval-ai-system-backend-1 python -m pytest tests/test_mrm_dossier_calibration.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Admin/loan-approval-ai-system"
git add backend/apps/ml_engine/services/mrm_dossier.py backend/tests/test_mrm_dossier_calibration.py
git commit -m "$(cat <<'EOF'
fix(mrm): dossier reads deciles from mv.decile_analysis (canonical path)

The dossier's calibration section was looking for deciles at
mv.calibration_data["deciles"], but the trainer stores them on the
separate mv.decile_analysis JSONField. The empty-state stub fired even
when calibration data was present. Adds the canonical lookup first,
preserves the legacy calibration_data fallback for older bundles.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Trainer mirrors `psi_by_feature` into `training_metadata`

**Goal:** The trainer computes `metrics["psi_by_feature"]` at the top level of the metrics dict, but `ModelVersion.training_metadata` is populated from `metrics["training_metadata"]` only — so `psi_by_feature` was being dropped before reaching the DB. Mirror it into the nested block so it follows the existing pattern.

**Files:**
- Modify: `backend/apps/ml_engine/services/trainer.py` — the `metrics["training_metadata"] = { ... }` block (around line 986-1014)
- Test: `backend/tests/test_trainer_psi_mirror.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_trainer_psi_mirror.py`:

```python
"""Tests for trainer mirroring psi_by_feature into training_metadata.

The dossier reads training_metadata.psi_by_feature; the trainer used to
write only metrics["psi_by_feature"] (top level) which was dropped by the
ModelVersion creation path. This test pins the mirror.
"""

import pytest

from apps.ml_engine.services.trainer import ModelTrainer


@pytest.mark.django_db
def test_train_metrics_include_psi_by_feature_in_training_metadata(tmp_path, monkeypatch):
    """metrics['training_metadata']['psi_by_feature'] mirrors the top-level metrics['psi_by_feature']."""
    from apps.ml_engine.services.data_generator import DataGenerator

    gen = DataGenerator()
    df = gen.generate(num_records=300, random_seed=42, label_noise_rate=0.05)
    csv_path = tmp_path / "tiny.csv"
    df.to_csv(csv_path, index=False)

    trainer = ModelTrainer()
    monkeypatch.setattr(trainer, "_train_xgb", trainer._train_rf)
    _model, metrics = trainer.train(str(csv_path), algorithm="rf")

    top_level = metrics.get("psi_by_feature") or {}
    mirrored = metrics.get("training_metadata", {}).get("psi_by_feature") or {}

    # Mirror is populated.
    assert isinstance(mirrored, dict)
    # Mirror keys are a subset of (or equal to) top-level keys — same data.
    assert set(mirrored.keys()) == set(top_level.keys())
    # Numeric values match (within float tolerance).
    for k in mirrored:
        assert abs(mirrored[k] - top_level[k]) < 1e-9, f"mirror diverged for {k}"
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
docker exec loan-approval-ai-system-backend-1 python -m pytest tests/test_trainer_psi_mirror.py -v
```

Expected: FAIL — `training_metadata["psi_by_feature"]` is empty / missing.

- [ ] **Step 3: Apply the mirror**

Edit `backend/apps/ml_engine/services/trainer.py`. Find the line in the `metrics["training_metadata"] = { ... }` block (around line 1019) that reads:

```python
            "iv_features_excluded_leakage": len(getattr(self, "_iv_result", {}).get("excluded_leakage", [])),
            "reference_probabilities": list(getattr(self, "_holdout_probabilities", []) or []),
            **split_meta,
```

Insert one new key between `iv_features_excluded_leakage` and `reference_probabilities`:

```python
            "iv_features_excluded_leakage": len(getattr(self, "_iv_result", {}).get("excluded_leakage", [])),
            "psi_by_feature": dict(metrics.get("psi_by_feature") or {}),
            "reference_probabilities": list(getattr(self, "_holdout_probabilities", []) or []),
            **split_meta,
```

Note: at this point in `train()`, `metrics["psi_by_feature"]` was already set (line ~952). Reading it back is safe and decouples the mirror from upstream computation order changes.

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec loan-approval-ai-system-backend-1 python -m pytest tests/test_trainer_psi_mirror.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Admin/loan-approval-ai-system"
git add backend/apps/ml_engine/services/trainer.py backend/tests/test_trainer_psi_mirror.py
git commit -m "$(cat <<'EOF'
feat(ml): trainer mirrors psi_by_feature into training_metadata

The dossier reads mv.training_metadata.psi_by_feature; the trainer wrote
only metrics["psi_by_feature"] which was dropped before hitting the DB.
Mirror it into the training_metadata block so the canonical path is
populated for every newly trained model.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `backfill_psi_by_feature` management command

**Goal:** Patch existing models that were trained before Task 2 landed. The active `1c21d19b...` model has `psi_by_feature: {}` in its metadata; the dossier consequently reports "No PSI data recorded". Backfill computes per-feature PSI between the bundle's stored `feature_distributions` (training reference) and a fresh `DataGenerator` batch, writes the result into `mv.training_metadata.psi_by_feature`. Idempotent: refuses to overwrite without `--force`.

**Files:**
- Create: `backend/apps/ml_engine/management/commands/backfill_psi_by_feature.py`
- Test: `backend/tests/test_backfill_psi_by_feature.py` (NEW)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_backfill_psi_by_feature.py`:

```python
"""Tests for the backfill_psi_by_feature management command.

Mirror of the test_backfill_reference_distribution structure: stub
ModelVersion with a bundle that has feature_distributions but no
training_metadata.psi_by_feature, run command, assert mirror is now
populated. Then re-run and verify idempotent refusal + --force overwrite.
"""

import joblib
import numpy as np
import pytest
from django.core.management import call_command
from django.test import override_settings
from sklearn.linear_model import LogisticRegression

from apps.ml_engine.models import ModelVersion


@pytest.fixture
def stub_model(tmp_path):
    bundle_path = tmp_path / "psi_stub.joblib"
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
            "feature_distributions": {"credit_score": [600, 650, 700, 750, 800]},
        },
        "imputation_values": {"credit_score": 650.0},
        "conformal_scores": [],
        "feature_bounds": {},
        "group_thresholds": {},
    }
    joblib.dump(bundle, bundle_path)

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        mv = ModelVersion.objects.create(
            algorithm="rf", version="psi-stub",
            file_path=str(bundle_path), is_active=True,
            optimal_threshold=0.5,
            training_metadata={"reference_probabilities": [0.2, 0.5, 0.8]},
        )
    return mv, bundle_path, tmp_path


def _patch_predictor(monkeypatch, model, feature_cols):
    """Stub ModelPredictor so tests don't need a full bundle pipeline."""

    def _fake_init(self, model_version=None, **kwargs):
        self.model_version = model_version
        self.model = model
        self.feature_cols = feature_cols

    def _fake_transform(self, df):
        return df  # passthrough

    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor.__init__",
        _fake_init,
    )
    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor._transform",
        _fake_transform,
    )


def _fitted_test_model():
    """Tiny fitted model the predictor stub returns."""
    return LogisticRegression().fit(np.array([[600], [700], [800]]), np.array([0, 1, 1]))


@pytest.mark.django_db
def test_backfill_populates_psi_by_feature(stub_model, monkeypatch):
    mv, _bundle_path, tmp_path = stub_model

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [620, 660, 690, 740, 780] * (num_records // 5)}),
    )
    _patch_predictor(monkeypatch, _fitted_test_model(), ["credit_score"])

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command("backfill_psi_by_feature", "--all-active", "--sample", "20")

    mv.refresh_from_db()
    psi = (mv.training_metadata or {}).get("psi_by_feature") or {}
    assert "credit_score" in psi
    assert isinstance(psi["credit_score"], float)


@pytest.mark.django_db
def test_backfill_refuses_without_force_when_present(stub_model, monkeypatch, capsys):
    mv, _bundle_path, tmp_path = stub_model
    mv.training_metadata = {**(mv.training_metadata or {}), "psi_by_feature": {"credit_score": 0.5}}
    mv.save(update_fields=["training_metadata"])

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [700] * num_records}),
    )
    _patch_predictor(monkeypatch, _fitted_test_model(), ["credit_score"])

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command("backfill_psi_by_feature", "--all-active", "--sample", "10")

    out = capsys.readouterr().out
    assert "skip" in out.lower() or "already populated" in out.lower()
    mv.refresh_from_db()
    assert (mv.training_metadata or {}).get("psi_by_feature") == {"credit_score": 0.5}


@pytest.mark.django_db
def test_backfill_force_overwrites(stub_model, monkeypatch):
    mv, _bundle_path, tmp_path = stub_model
    mv.training_metadata = {**(mv.training_metadata or {}), "psi_by_feature": {"credit_score": 0.5}}
    mv.save(update_fields=["training_metadata"])

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [620, 660, 690, 740, 780] * (num_records // 5)}),
    )
    _patch_predictor(monkeypatch, _fitted_test_model(), ["credit_score"])

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command("backfill_psi_by_feature", "--all-active", "--sample", "20", "--force")

    mv.refresh_from_db()
    psi = (mv.training_metadata or {}).get("psi_by_feature") or {}
    assert psi != {"credit_score": 0.5}
    assert "credit_score" in psi
```

- [ ] **Step 2: Run, verify all 3 fail**

```bash
docker exec loan-approval-ai-system-backend-1 python -m pytest tests/test_backfill_psi_by_feature.py -v
```

Expected: 3 FAILs with `Unknown command: backfill_psi_by_feature`.

- [ ] **Step 3: Implement the management command**

Create `backend/apps/ml_engine/management/commands/backfill_psi_by_feature.py`:

```python
"""Backfill training_metadata.psi_by_feature on existing model versions.

Models trained before the trainer's psi_by_feature mirror landed have
empty `mv.training_metadata.psi_by_feature`, so the dossier prints
"No PSI data recorded" even when reference distributions exist in the
bundle. This command computes per-feature PSI between the bundle's
stored feature_distributions (training reference) and a fresh
DataGenerator batch (the proxy for "current" data), and writes the
result into mv.training_metadata.psi_by_feature.

Idempotent — refuses to overwrite without --force.
"""

import joblib
import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.metrics import psi_by_feature
from apps.ml_engine.services.prediction_cache import _validate_model_path


class Command(BaseCommand):
    help = "Backfill ModelVersion.training_metadata.psi_by_feature for models that pre-date the trainer mirror."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--model-id", type=str, help="UUID of a specific ModelVersion to backfill.")
        target.add_argument("--all-active", action="store_true", help="Backfill every is_active=True ModelVersion.")
        parser.add_argument(
            "--sample", type=int, default=5000,
            help="DataGenerator sample size used as the 'current' frame for PSI (default 5000).",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Overwrite existing training_metadata.psi_by_feature. Default refuses.",
        )

    def handle(self, *args, **options):
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
        from apps.ml_engine.services.data_generator import DataGenerator
        from apps.ml_engine.services.predictor import ModelPredictor

        meta = dict(mv.training_metadata or {})
        if meta.get("psi_by_feature") and not force:
            self.stdout.write(
                f"[skip] {mv.algorithm} v{mv.version}: psi_by_feature already populated; "
                f"pass --force to overwrite."
            )
            return

        try:
            bundle_path = _validate_model_path(mv.file_path)
        except (ValueError, FileNotFoundError) as exc:
            raise CommandError(f"Bundle path invalid for {mv.id}: {exc}")

        bundle = joblib.load(bundle_path)
        ref_dist = bundle.get("reference_distribution") or {}
        feature_distributions = ref_dist.get("feature_distributions") or {}
        if not feature_distributions:
            raise CommandError(
                f"Bundle for {mv.id} has no feature_distributions in reference_distribution; "
                f"run backfill_reference_distribution first."
            )

        # Build the "training reference" DataFrame from the bundle's stored samples.
        train_df = pd.DataFrame({col: vals for col, vals in feature_distributions.items()})

        # Build the "current" DataFrame: a fresh DataGenerator batch passed
        # through the predictor's transform pipeline so feature engineering
        # matches what the bundle was trained against.
        gen_df = DataGenerator().generate(num_records=sample_size, random_seed=42, label_noise_rate=0.05)
        for target_col in ("default_flag", "approved", "is_default"):
            if target_col in gen_df.columns:
                gen_df = gen_df.drop(columns=[target_col])

        try:
            predictor = ModelPredictor(model_version=mv)
        except Exception as exc:
            raise CommandError(f"Could not load predictor for {mv.id}: {exc}")

        try:
            current_df = predictor._transform(gen_df.copy())
        except Exception as exc:
            raise CommandError(f"Feature transformation failed for {mv.id}: {exc}")

        # Restrict to the columns that exist in the training-reference frame
        # (those are the columns the bundle stored samples for).
        feature_cols = [c for c in feature_distributions.keys() if c in current_df.columns]
        if not feature_cols:
            raise CommandError(
                f"No overlap between bundle feature_distributions and predictor output for {mv.id}; "
                f"cannot compute PSI."
            )

        try:
            psi_map = psi_by_feature(train_df, current_df, feature_cols)
        except Exception as exc:
            raise CommandError(f"psi_by_feature computation failed for {mv.id}: {exc}")

        meta["psi_by_feature"] = psi_map
        mv.training_metadata = meta
        mv.save(update_fields=["training_metadata"])

        self.stdout.write(self.style.SUCCESS(
            f"[ok] {mv.algorithm} v{mv.version}: wrote psi_by_feature with {len(psi_map)} feature columns"
        ))
```

- [ ] **Step 4: Run tests**

```bash
docker exec loan-approval-ai-system-backend-1 python -m pytest tests/test_backfill_psi_by_feature.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Admin/loan-approval-ai-system"
git add backend/apps/ml_engine/management/commands/backfill_psi_by_feature.py backend/tests/test_backfill_psi_by_feature.py
git commit -m "$(cat <<'EOF'
feat(ml): backfill_psi_by_feature mgmt command

One-shot patch for ModelVersions that pre-date the trainer's
psi_by_feature mirror. Computes per-feature PSI between the bundle's
stored feature_distributions and a fresh DataGenerator batch passed
through the predictor's _transform pipeline, then writes
mv.training_metadata.psi_by_feature so the dossier renders the table.
Idempotent -- refuses to overwrite without --force.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Strict gate defaults in `settings/base.py`

**Goal:** Flip the three gate-mode defaults from advisory (`shadow` / `warn` / `warn`) to enforcement (`enforce` / `block` / `block`). Operators can still override via env vars for emergency rollback.

**Files:**
- Modify: `backend/config/settings/base.py:241,252,263`
- Test: `backend/tests/test_settings_strict_gate_defaults.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_settings_strict_gate_defaults.py`:

```python
"""Pin the strict default gate modes in base settings.

Defaults must be enforcement-by-default so a non-compliant model cannot
silently activate. Env vars can still relax the modes for emergency
rollback.
"""

import os

import pytest


def test_credit_policy_overlay_mode_default_is_enforce(monkeypatch):
    monkeypatch.delenv("CREDIT_POLICY_OVERLAY_MODE", raising=False)
    import importlib
    from django.conf import settings as django_settings
    from config.settings import base
    importlib.reload(base)
    assert base.CREDIT_POLICY_OVERLAY_MODE == "enforce"


def test_ml_fairness_gate_mode_default_is_block(monkeypatch):
    monkeypatch.delenv("ML_FAIRNESS_GATE_MODE", raising=False)
    import importlib
    from config.settings import base
    importlib.reload(base)
    assert base.ML_FAIRNESS_GATE_MODE == "block"


def test_ml_promotion_gate_mode_default_is_block(monkeypatch):
    monkeypatch.delenv("ML_PROMOTION_GATE_MODE", raising=False)
    import importlib
    from config.settings import base
    importlib.reload(base)
    assert base.ML_PROMOTION_GATE_MODE == "block"


def test_env_var_override_still_works(monkeypatch):
    """An operator setting ML_FAIRNESS_GATE_MODE=warn must still see warn."""
    monkeypatch.setenv("ML_FAIRNESS_GATE_MODE", "warn")
    import importlib
    from config.settings import base
    importlib.reload(base)
    assert base.ML_FAIRNESS_GATE_MODE == "warn"
```

- [ ] **Step 2: Run, verify the first three fail**

```bash
docker exec loan-approval-ai-system-backend-1 python -m pytest tests/test_settings_strict_gate_defaults.py -v
```

Expected: 3 FAILs (defaults still advisory); `test_env_var_override_still_works` PASS.

- [ ] **Step 3: Apply the default flips**

Edit `backend/config/settings/base.py`. Three single-line changes around lines 241, 252, 263.

Find:

```python
CREDIT_POLICY_OVERLAY_MODE = os.environ.get("CREDIT_POLICY_OVERLAY_MODE", "shadow")
```

Replace with:

```python
CREDIT_POLICY_OVERLAY_MODE = os.environ.get("CREDIT_POLICY_OVERLAY_MODE", "enforce")
```

Find:

```python
ML_FAIRNESS_GATE_MODE = os.environ.get("ML_FAIRNESS_GATE_MODE", "warn")
```

Replace with:

```python
ML_FAIRNESS_GATE_MODE = os.environ.get("ML_FAIRNESS_GATE_MODE", "block")
```

Find:

```python
ML_PROMOTION_GATE_MODE = os.environ.get("ML_PROMOTION_GATE_MODE", "warn")
```

Replace with:

```python
ML_PROMOTION_GATE_MODE = os.environ.get("ML_PROMOTION_GATE_MODE", "block")
```

- [ ] **Step 4: Run tests to verify all 4 pass**

```bash
docker exec loan-approval-ai-system-backend-1 python -m pytest tests/test_settings_strict_gate_defaults.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Admin/loan-approval-ai-system"
git add backend/config/settings/base.py backend/tests/test_settings_strict_gate_defaults.py
git commit -m "$(cat <<'EOF'
fix(config): strict gate-mode defaults (enforce/block/block)

Defaults flipped from advisory to enforcement so a non-compliant model
cannot silently activate (Codex adversarial review finding #1):

  CREDIT_POLICY_OVERLAY_MODE: shadow -> enforce
  ML_FAIRNESS_GATE_MODE:     warn -> block
  ML_PROMOTION_GATE_MODE:    warn -> block

Env var override semantics preserved -- operators can still set
ML_FAIRNESS_GATE_MODE=warn for emergency rollback per RUNBOOK.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Revert `frontend/next-env.d.ts`

**Goal:** Drop the dev-only `./.next/dev/types/routes.d.ts` import path; restore the standard Next-generated content. Next.js regenerates this file on every dev / build run from a clean checkout.

**Files:**
- Modify: `frontend/next-env.d.ts`

- [ ] **Step 1: Replace the file with the standard content**

Set `frontend/next-env.d.ts` to:

```typescript
/// <reference types="next" />
/// <reference types="next/image-types/global" />
import "./.next/types/routes.d.ts";

// NOTE: This file should not be edited
// see https://nextjs.org/docs/basic-features/typescript for more information.
```

If the file already matches the master version (e.g. someone else reverted it), no change is needed — proceed to commit detection.

- [ ] **Step 2: Verify the change is reverted (no untracked diff)**

```bash
cd "C:/Users/Admin/loan-approval-ai-system"
git diff frontend/next-env.d.ts
```

Expected: no diff vs the committed master version (the file matches HEAD), OR a clean revert diff that drops the `./.next/dev/types/routes.d.ts` import.

If there is a diff, proceed to commit. If `git diff` shows nothing AND `git status` shows no modifications, the file was already at the standard content; skip to Task 6.

- [ ] **Step 3: Commit (only if there was a diff)**

```bash
cd "C:/Users/Admin/loan-approval-ai-system"
git add frontend/next-env.d.ts
git commit -m "$(cat <<'EOF'
fix(frontend): revert next-env.d.ts to standard Next-generated content

Drops the hand-edited `./.next/dev/types/routes.d.ts` import which is
specific to a dev build tree. Clean CI / production builds emit the
non-dev path, so the previous content risked breaking typecheck outside
the local dev environment (Codex adversarial review finding #3).

Next.js regenerates this file on every dev / build run.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: RUNBOOK — strict gate defaults section

**Goal:** Document the new defaults, the env-var rollback, and the operator playbook for what happens when a fairness gate refuses activation.

**Files:**
- Modify: `backend/docs/RUNBOOK.md` (append a new section)

- [ ] **Step 1: Append the section**

Open `backend/docs/RUNBOOK.md`. Find the last line of the file. Append:

```markdown

## Strict gate defaults — when and how to relax

The deployment defaults to enforcement on three model-governance gates:

| Variable | Default | Effect when default is active |
|---|---|---|
| `ML_FAIRNESS_GATE_MODE` | `block` | A new training run that fails the 4/5ths fairness rule raises `FairnessGateBlocked` BEFORE atomic activation. Old segment model stays `is_active=True`. |
| `ML_PROMOTION_GATE_MODE` | `block` | A new model that fails champion-challenger promotion gates (PSI / calibration / KS) is rejected pre-activation. |
| `CREDIT_POLICY_OVERLAY_MODE` | `enforce` | Out-of-scope predictions (commercial lending, applicants outside AU residency, etc.) are routed to manual review automatically rather than silently scored. |

### What you see when a gate fires

Training task wrapper releases the lock and surfaces the blocked condition in:

- Celery worker logs (`docker compose logs celery_worker_ml`)
- Flower UI (`http://localhost:5555` → failed task with the gate exception class in the traceback)
- `ModelVersion.training_metadata` on the most recent training run carries `fairness_gate_mode` / `promotion_gate_mode` plus the rejection reason

### Decision tree when a real violation surfaces

1. **Re-train with adjusted features.** Most fairness violations come from a single feature with strong protected-class correlation. Re-binning, dropping, or interacting it with a less-correlated feature usually clears the gate without sacrificing AUC.
2. **Accept the violation explicitly.** If the violation is unavoidable for the segment (e.g. limited training data for a protected group), set the env var to `warn` for ONE training run, document the operator decision in the model's MRM dossier, then flip back to `block`.
3. **Skip activation.** Train the model; do not promote. The blocked state is not destructive — the existing active model continues serving.

### Emergency rollback

If a gate misfires (false positive, e.g. due to a bug in the gate logic itself rather than a real violation), relax the relevant variable in `.env`:

```bash
ML_FAIRNESS_GATE_MODE=warn
ML_PROMOTION_GATE_MODE=warn
CREDIT_POLICY_OVERLAY_MODE=shadow
```

Restart `backend` and `celery_worker_ml`:

```bash
docker compose restart backend celery_worker_ml
```

Confirm via `docker compose logs backend` that the new mode is active. Re-trigger the training run. Once the underlying issue is fixed, restore the env vars to enforcement defaults and restart again.

See [`docs/superpowers/specs/2026-05-07-ml-fairness-gate-mode-design.md`](../../docs/superpowers/specs/2026-05-07-ml-fairness-gate-mode-design.md) for the gate-mode machinery internals.
```

- [ ] **Step 2: Commit**

```bash
cd "C:/Users/Admin/loan-approval-ai-system"
git add backend/docs/RUNBOOK.md
git commit -m "$(cat <<'EOF'
docs(runbook): strict gate defaults section

Documents the three enforcement-by-default gate modes
(ML_FAIRNESS_GATE_MODE, ML_PROMOTION_GATE_MODE, CREDIT_POLICY_OVERLAY_MODE),
what an operator sees when a gate fires, the decision tree for handling a
real violation, and the emergency rollback procedure.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Live verification on the dev stack

**Goal:** Run the new backfill against the active `1c21d19b...` model, regenerate its dossier, confirm §6 Calibration and §7 PSI sections render real tables instead of "not recorded" stubs.

- [ ] **Step 1: Backfill the active model**

```bash
docker exec loan-approval-ai-system-backend-1 \
  python manage.py backfill_psi_by_feature --all-active --sample 5000
```

Expected output: `[ok] xgb v20260508_174941: wrote psi_by_feature with N feature columns` (where N matches the bundle's `feature_distributions` keys, ~21).

- [ ] **Step 2: Regenerate the dossier**

```bash
docker exec loan-approval-ai-system-backend-1 \
  python manage.py generate_mrm_dossier --model-id 1c21d19b-f1a9-43ce-a115-fdef602d410d
```

Expected: command exits 0, dossier file at `backend/ml_models/1c21d19b-.../mrm.md` is rewritten.

- [ ] **Step 3: Verify the dossier sections**

```bash
sed -n '/## 6. Calibration/,/## 7. /p' backend/ml_models/1c21d19b-f1a9-43ce-a115-fdef602d410d/mrm.md
sed -n '/## 7. PSI/,/## 8. /p' backend/ml_models/1c21d19b-f1a9-43ce-a115-fdef602d410d/mrm.md
```

Expected:
- §6 Calibration: a table of decile rows (decile / actual rate / predicted rate / count), NOT the "Decile calibration not recorded" stub.
- §7 PSI by feature: a table of feature rows with PSI values, NOT the "No PSI data recorded" stub.

- [ ] **Step 4: Final marker commit**

```bash
cd "C:/Users/Admin/loan-approval-ai-system"
git commit --allow-empty -m "$(cat <<'EOF'
chore(ml): manual verification — codex adversarial findings closed

Confirmed against live active model 1c21d19b-f1a9-43ce-a115-fdef602d410d:
- backfill_psi_by_feature populated mv.training_metadata.psi_by_feature
- regenerated dossier shows real Calibration (§6) and PSI (§7) tables
- gate-mode defaults flipped to enforce/block/block; env-var override path
  still works (verified via test_settings_strict_gate_defaults.py)
- next-env.d.ts back to Next-generated standard content

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist (post-execution)

After all tasks land, verify against the spec:

- [ ] Dossier reads `decile_analysis.deciles` first (spec §Components.1) — ✓ Task 1
- [ ] Trainer mirrors `psi_by_feature` into `metrics["training_metadata"]` (spec §Components.2) — ✓ Task 2
- [ ] `backfill_psi_by_feature` exists with `--model-id`, `--all-active`, `--sample`, `--force` (spec §Components.3) — ✓ Task 3
- [ ] All three gate-mode defaults flipped (spec §Components.4) — ✓ Task 4
- [ ] `next-env.d.ts` matches standard Next-generated content (spec §Components.5) — ✓ Task 5
- [ ] RUNBOOK has "Strict gate defaults — when and how to relax" section (spec §Components.6) — ✓ Task 6
- [ ] All four named test files exist and pass (spec §Components.7) — ✓ Tasks 1, 2, 3, 4
- [ ] Live verification: dossier renders deciles + PSI tables (spec §Testing manual block) — ✓ Task 7
