"""GMSC external benchmark — train the production pipeline on real borrower data.

Trains the *same* XGBoost + Optuna + isotonic-calibration pipeline used in
production on Kaggle's "Give Me Some Credit" (2011) dataset — 150,000 real
anonymised borrowers. Reports 5-fold stratified CV AUC and compares against
published leaderboard results.

This is a sibling artifact of the production pipeline, not a replacement:
it exists to answer the question *"does this pipeline generalise off
synthetic data?"* honestly.

Design: ``docs/superpowers/specs/2026-04-18-gmsc-benchmark-validation-design.md``
Results: ``docs/experiments/gmsc_benchmark.md``

Run:
    docker compose exec backend python scripts/benchmark_gmsc.py
    # or
    make benchmark-gmsc
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from xgboost import XGBClassifier

logger = logging.getLogger("benchmark_gmsc")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GMSC_URL = (
    "https://raw.githubusercontent.com/"
    "DrIanGregory/Kaggle-GiveMeSomeCredit/master/data/GiveMeSomeCredit-training.csv"
)
EXPECTED_ROWS = 150_000
# SHA256 of the mirror-hosted CSV, pinned 2026-04-18. Re-pinning is only
# legitimate if the upstream mirror is intentionally updated — inspect first.
EXPECTED_SHA256: str | None = (
    "e333eb8001576d7eb140cdfad9801c6b000ddfa6a528b6268a640230eb2a9994"
)

TARGET_COL = "SeriousDlqin2yrs"
FEATURE_COLS = [
    "RevolvingUtilizationOfUnsecuredLines",
    "age",
    "NumberOfTime30-59DaysPastDueNotWorse",
    "DebtRatio",
    "MonthlyIncome",
    "NumberOfOpenCreditLinesAndLoans",
    "NumberOfTimes90DaysLate",
    "NumberRealEstateLoansOrLines",
    "NumberOfTime60-89DaysPastDueNotWorse",
    "NumberOfDependents",
]

RANDOM_STATE = 42
OPTUNA_TRIALS = 50
CV_FOLDS = 5
MAX_AUC_STD = 0.02  # Fold-to-fold AUC instability threshold


# ---------------------------------------------------------------------------
# Data acquisition
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    """Return a ``.tmp/gmsc/`` cache dir next to the backend package.

    Resolves to ``<backend>/.tmp/gmsc/`` in both host and container layouts
    (``/app/.tmp/gmsc`` inside the container, ``<repo>/backend/.tmp/gmsc``
    on the host). The repo-level ``.gitignore`` matches ``.tmp/`` at any
    depth, so this path is never committed.
    """
    base = Path(__file__).resolve().parents[1]
    d = base / ".tmp" / "gmsc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def download_gmsc(assume_yes: bool = False) -> Path:
    """Ensure the GMSC CSV is cached locally; verify SHA256 if pinned.

    Returns the path to the cached CSV. Raises if integrity check fails.
    """
    target = _cache_dir() / "cs-training.csv"
    if target.exists():
        logger.info("Using cached GMSC CSV at %s", target)
    else:
        if not assume_yes and sys.stdin.isatty():
            resp = input(f"Download ~7MB GMSC CSV from {GMSC_URL}? [y/N] ").strip().lower()
            if resp not in {"y", "yes"}:
                raise SystemExit("Aborted by user")
        logger.info("Downloading GMSC CSV from %s", GMSC_URL)
        urllib.request.urlretrieve(GMSC_URL, target)  # noqa: S310 (URL is constant)

    sha = _sha256_file(target)
    if EXPECTED_SHA256 is None:
        logger.warning(
            "EXPECTED_SHA256 is not pinned. Got SHA256=%s. "
            "Pin this hash in the script for future runs.",
            sha,
        )
    elif sha != EXPECTED_SHA256:
        raise RuntimeError(
            f"SHA256 mismatch: expected {EXPECTED_SHA256}, got {sha}. "
            "The upstream mirror may have changed. Inspect before re-pinning."
        )
    return target


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------


def load_and_preprocess(csv_path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Load GMSC CSV and apply standard preprocessing.

    Steps:
      1. Drop the unnamed index column
      2. Assert row count
      3. Median-impute ``MonthlyIncome`` NaNs
      4. Zero-impute ``NumberOfDependents`` NaNs
      5. Cap ``DebtRatio`` and ``MonthlyIncome`` at 99th percentile

    No SMOTE / oversampling — we report performance on the natural
    imbalance (~6.7% positive class).
    """
    df = pd.read_csv(csv_path)
    if "Unnamed: 0" in df.columns:
        df = df.drop(columns=["Unnamed: 0"])

    if len(df) != EXPECTED_ROWS:
        raise RuntimeError(
            f"Expected {EXPECTED_ROWS} rows, got {len(df)}. Wrong file?"
        )

    missing = set(FEATURE_COLS + [TARGET_COL]) - set(df.columns)
    if missing:
        raise RuntimeError(f"Missing expected columns: {sorted(missing)}")

    # Median / zero imputation
    df["MonthlyIncome"] = df["MonthlyIncome"].fillna(df["MonthlyIncome"].median())
    df["NumberOfDependents"] = df["NumberOfDependents"].fillna(0).astype(int)

    # 99th-percentile outlier cap — standard GMSC treatment
    for col in ("DebtRatio", "MonthlyIncome"):
        cap = df[col].quantile(0.99)
        df[col] = df[col].clip(upper=cap)

    X = df[FEATURE_COLS].copy()
    y = df[TARGET_COL].astype(int)
    return X, y


# ---------------------------------------------------------------------------
# Optuna + XGBoost + isotonic calibration
# ---------------------------------------------------------------------------


def _optuna_objective(trial: optuna.Trial, X: pd.DataFrame, y: pd.Series) -> float:
    params = {
        "max_depth": trial.suggest_int("max_depth", 3, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        "gamma": trial.suggest_float("gamma", 0.0, 5.0),
    }
    model = XGBClassifier(
        objective="binary:logistic",
        eval_metric="auc",
        tree_method="hist",
        random_state=RANDOM_STATE,
        n_jobs=-1,
        **params,
    )
    # 3-fold for speed during search; final eval is 5-fold
    cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=RANDOM_STATE)
    scores = cross_val_score(model, X, y, cv=cv, scoring="roc_auc", n_jobs=1)
    return float(scores.mean())


def search_best_params(X: pd.DataFrame, y: pd.Series, n_trials: int = OPTUNA_TRIALS) -> dict:
    """Run Optuna search, return best params."""
    sampler = optuna.samplers.TPESampler(seed=RANDOM_STATE)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(
        lambda trial: _optuna_objective(trial, X, y),
        n_trials=n_trials,
        show_progress_bar=False,
    )
    logger.info("Best Optuna AUC (3-fold): %.4f", study.best_value)
    return dict(study.best_params)


def build_calibrated_pipeline(best_params: dict) -> CalibratedClassifierCV:
    """Build XGBoost + isotonic calibration wrapper matching production."""
    base = XGBClassifier(
        objective="binary:logistic",
        eval_metric="auc",
        tree_method="hist",
        random_state=RANDOM_STATE,
        n_jobs=-1,
        **best_params,
    )
    return CalibratedClassifierCV(base, method="isotonic", cv=3)


# ---------------------------------------------------------------------------
# 5-fold CV evaluation
# ---------------------------------------------------------------------------


def _ks_statistic(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """Kolmogorov-Smirnov statistic = max separation between class CDFs."""
    order = np.argsort(y_proba)
    y_sorted = y_true[order]
    cum_pos = np.cumsum(y_sorted) / max(y_sorted.sum(), 1)
    cum_neg = np.cumsum(1 - y_sorted) / max((1 - y_sorted).sum(), 1)
    return float(np.max(np.abs(cum_pos - cum_neg)))


def run_cv(X: pd.DataFrame, y: pd.Series, best_params: dict) -> dict:
    """Run 5-fold stratified CV on the calibrated pipeline."""
    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    aucs: list[float] = []
    ks_scores: list[float] = []
    briers: list[float] = []

    for fold_idx, (train_idx, test_idx) in enumerate(cv.split(X, y), start=1):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        pipeline = build_calibrated_pipeline(best_params)
        pipeline.fit(X_train, y_train)

        proba = pipeline.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, proba)
        ks = _ks_statistic(y_test.to_numpy(), proba)
        brier = brier_score_loss(y_test, proba)

        aucs.append(auc)
        ks_scores.append(ks)
        briers.append(brier)
        logger.info(
            "Fold %d/%d — AUC=%.4f  KS=%.4f  Brier=%.4f",
            fold_idx, CV_FOLDS, auc, ks, brier,
        )

    auc_mean = float(np.mean(aucs))
    auc_std = float(np.std(aucs))
    if auc_std > MAX_AUC_STD:
        raise RuntimeError(
            f"CV AUC std {auc_std:.4f} > {MAX_AUC_STD} — unstable. Investigate."
        )

    return {
        "auc_mean": auc_mean,
        "auc_std": auc_std,
        "auc_per_fold": aucs,
        "ks_mean": float(np.mean(ks_scores)),
        "ks_per_fold": ks_scores,
        "brier_mean": float(np.mean(briers)),
        "brier_per_fold": briers,
        "cv_folds": CV_FOLDS,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _versions() -> dict:
    import sklearn
    import xgboost

    return {
        "python": sys.version.split()[0],
        "xgboost": xgboost.__version__,
        "optuna": optuna.__version__,
        "sklearn": sklearn.__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="GMSC external benchmark")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip download prompt")
    parser.add_argument(
        "--trials", type=int, default=OPTUNA_TRIALS, help="Optuna trial count",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Results JSON output path (default: .tmp/gmsc/benchmark_results.json)",
    )
    args = parser.parse_args()

    t0 = time.time()
    csv_path = download_gmsc(assume_yes=args.yes)
    X, y = load_and_preprocess(csv_path)
    logger.info(
        "Loaded %d rows, %d features, positive rate %.2f%%",
        len(X), X.shape[1], 100 * y.mean(),
    )

    # Sub-sample for Optuna to keep wall time reasonable; full 150k for CV eval.
    X_search, _, y_search, _ = train_test_split(
        X, y, train_size=30_000, stratify=y, random_state=RANDOM_STATE,
    )
    logger.info("Running Optuna search (%d trials) on 30k stratified sample...", args.trials)
    best_params = search_best_params(X_search, y_search, n_trials=args.trials)
    logger.info("Best params: %s", best_params)

    logger.info("Running %d-fold stratified CV on full %d rows...", CV_FOLDS, len(X))
    cv_results = run_cv(X, y, best_params)

    elapsed = time.time() - t0
    results = {
        "dataset": "Kaggle Give Me Some Credit (2011)",
        "source_url": GMSC_URL,
        "sha256": _sha256_file(csv_path),
        "rows": len(X),
        "features": FEATURE_COLS,
        "positive_rate": float(y.mean()),
        "optuna_trials": args.trials,
        "best_params": best_params,
        **cv_results,
        "published_top_1pct_auc": 0.869,
        "elapsed_seconds": round(elapsed, 1),
        "versions": _versions(),
    }

    out_path = args.output or (_cache_dir() / "benchmark_results.json")
    out_path.write_text(json.dumps(results, indent=2))

    logger.info("=" * 70)
    logger.info(
        "RESULT — 5-fold CV AUC: %.4f ± %.4f  (top-1%% leaderboard: 0.869)",
        cv_results["auc_mean"], cv_results["auc_std"],
    )
    logger.info("KS mean: %.4f  |  Brier mean: %.4f", cv_results["ks_mean"], cv_results["brier_mean"])
    logger.info("Elapsed: %.1fs  |  Results written to %s", elapsed, out_path)
    logger.info("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
