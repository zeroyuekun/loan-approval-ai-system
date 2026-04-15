# backend/apps/ml_engine/management/commands/run_benchmark.py
from __future__ import annotations

import pathlib
import time
from typing import Any

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from apps.ml_engine.services.data_generator import DataGenerator, LABEL_LEAKING_COLUMNS
from apps.ml_engine.services.feature_engineering import compute_derived_features

TAKEAWAY_MARKER_BEGIN = "<!-- BENCHMARK TABLE BEGIN -->"
TAKEAWAY_MARKER_END = "<!-- BENCHMARK TABLE END -->"


class Command(BaseCommand):
    help = "Train LR, RF, XGBoost, LightGBM on identical splits and write a comparison table."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--num-records", type=int, default=10000)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument(
            "--output",
            default="docs/experiments/benchmark.md",
            help="Output path (default: docs/experiments/benchmark.md)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        np.random.seed(options["seed"])
        df = DataGenerator().generate(
            num_records=options["num_records"], random_seed=options["seed"]
        )
        df = compute_derived_features(df)

        y = df["approved"].astype(int).to_numpy()
        X = df.drop(columns=["approved", *LABEL_LEAKING_COLUMNS], errors="ignore")
        X = X.select_dtypes(include=[np.number]).fillna(0.0)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=options["seed"], stratify=y
        )
        scaler = StandardScaler().fit(X_train)
        X_train_scaled = scaler.transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        models = self._build_models(options["seed"])
        results = []
        for name, model, uses_scaler in models:
            t0 = time.time()
            if uses_scaler:
                model.fit(X_train_scaled, y_train)
                proba = model.predict_proba(X_test_scaled)[:, 1]
            else:
                model.fit(X_train, y_train)
                proba = model.predict_proba(X_test)[:, 1]
            train_secs = time.time() - t0
            results.append(
                {
                    "Model": name,
                    "AUC-ROC": roc_auc_score(y_test, proba),
                    "PR-AUC": average_precision_score(y_test, proba),
                    "Brier": brier_score_loss(y_test, proba),
                    "Train time (s)": train_secs,
                }
            )

        output_path = pathlib.Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        table = self._render_table(results, options)
        self._write_preserving_takeaway(output_path, table)
        self.stdout.write(self.style.SUCCESS(f"Wrote {output_path}"))

    def _build_models(self, seed: int) -> list[tuple[str, Any, bool]]:
        # Local imports keep pytest collection fast and isolate the dev-only
        # lightgbm dependency check to this command.
        from xgboost import XGBClassifier

        try:
            from lightgbm import LGBMClassifier
        except ImportError as exc:  # pragma: no cover - hit only if dev deps not installed
            raise RuntimeError(
                "lightgbm is a dev-only dependency required by the benchmark command. "
                "Install via `pip install -r requirements-dev.txt`."
            ) from exc

        return [
            (
                "LogisticRegression",
                LogisticRegression(max_iter=2000, random_state=seed),
                True,
            ),
            (
                "RandomForest",
                RandomForestClassifier(n_estimators=100, random_state=seed, n_jobs=-1),
                False,
            ),
            (
                "XGBoost",
                # use_label_encoder was removed in XGBoost >=2.1; default behaviour
                # is correct for our 0/1 integer labels.
                XGBClassifier(
                    n_estimators=100,
                    max_depth=6,
                    learning_rate=0.1,
                    random_state=seed,
                    eval_metric="logloss",
                ),
                False,
            ),
            (
                "LightGBM",
                LGBMClassifier(
                    n_estimators=100,
                    max_depth=-1,
                    learning_rate=0.1,
                    random_state=seed,
                    verbose=-1,
                ),
                False,
            ),
        ]

    def _render_table(self, results: list[dict[str, Any]], options: dict[str, Any]) -> str:
        lines = [
            "# Benchmark - XGBoost vs LR vs RF vs LightGBM",
            "",
            f"_Generated on {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M UTC}_",
            "",
            f"- **Records:** {options['num_records']:,}",
            f"- **Seed:** {options['seed']}",
            "- **Split:** stratified 80/20",
            "- **Features:** numeric after `compute_derived_features`, imputed to 0, StandardScaler for LR only",
            "",
            TAKEAWAY_MARKER_BEGIN,
            "",
            "| Model | AUC-ROC | PR-AUC | Brier | Train time (s) |",
            "|---|---|---|---|---|",
        ]
        for r in results:
            lines.append(
                f"| {r['Model']} | {r['AUC-ROC']:.4f} | {r['PR-AUC']:.4f} | "
                f"{r['Brier']:.4f} | {r['Train time (s)']:.2f} |"
            )
        lines.append("")
        lines.append(TAKEAWAY_MARKER_END)
        lines.append("")
        lines.append("## Takeaway")
        lines.append("")
        lines.append(
            "_Human-written interpretation goes here. Edit freely - this section "
            "is preserved on future `make benchmark` runs._"
        )
        return "\n".join(lines)

    def _write_preserving_takeaway(
        self, path: pathlib.Path, new_content: str
    ) -> None:
        """Write new table; preserve any human takeaway below the end marker."""
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if TAKEAWAY_MARKER_END in existing:
                after = existing.split(TAKEAWAY_MARKER_END, 1)[1]
                # Replace only the header+table section; keep existing takeaway.
                new_header = new_content.split(TAKEAWAY_MARKER_END)[0]
                path.write_text(new_header + TAKEAWAY_MARKER_END + after, encoding="utf-8")
                return
        path.write_text(new_content, encoding="utf-8")
