# backend/apps/ml_engine/management/commands/run_ablation.py
from __future__ import annotations

import pathlib
from typing import Any

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from apps.ml_engine.services.data_generator import DataGenerator, LABEL_LEAKING_COLUMNS
from apps.ml_engine.services.feature_engineering import compute_derived_features

TAKEAWAY_MARKER_BEGIN = "<!-- ABLATION TABLE BEGIN -->"
TAKEAWAY_MARKER_END = "<!-- ABLATION TABLE END -->"


class Command(BaseCommand):
    help = "Remove each of the top-K features and report delta-AUC and delta-PR-AUC."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--top-k", type=int, default=10)
        parser.add_argument("--num-records", type=int, default=10000)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument(
            "--output", default="docs/experiments/ablations.md"
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

        baseline_model = self._new_xgb(options["seed"])
        baseline_model.fit(X_train, y_train)
        baseline_proba = baseline_model.predict_proba(X_test)[:, 1]
        baseline_auc = roc_auc_score(y_test, baseline_proba)
        baseline_pr = average_precision_score(y_test, baseline_proba)

        importances = pd.Series(
            baseline_model.feature_importances_, index=X_train.columns
        )
        top_features = (
            importances.sort_values(ascending=False).head(options["top_k"]).index.tolist()
        )

        rows: list[dict[str, Any]] = []
        for feat in top_features:
            model = self._new_xgb(options["seed"])
            X_tr = X_train.drop(columns=[feat])
            X_te = X_test.drop(columns=[feat])
            model.fit(X_tr, y_train)
            proba = model.predict_proba(X_te)[:, 1]
            auc = roc_auc_score(y_test, proba)
            pr = average_precision_score(y_test, proba)
            rows.append(
                {
                    "Feature removed": feat,
                    "Baseline AUC": baseline_auc,
                    "AUC without feature": auc,
                    "\u0394AUC": baseline_auc - auc,
                    "\u0394PR-AUC": baseline_pr - pr,
                }
            )

        output_path = pathlib.Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        content = self._render(rows, options, baseline_auc, baseline_pr)
        self._write_preserving_takeaway(output_path, content)
        self.stdout.write(self.style.SUCCESS(f"Wrote {output_path}"))

    def _new_xgb(self, seed: int) -> XGBClassifier:
        # use_label_encoder was removed in XGBoost >=2.1; default behaviour is
        # correct for our 0/1 integer labels.
        return XGBClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            random_state=seed,
            eval_metric="logloss",
        )

    def _render(
        self,
        rows: list[dict[str, Any]],
        options: dict[str, Any],
        baseline_auc: float,
        baseline_pr: float,
    ) -> str:
        lines = [
            "# Ablation - top-K feature removal",
            "",
            f"_Generated on {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M UTC}_",
            "",
            f"- **Records:** {options['num_records']:,}",
            f"- **Seed:** {options['seed']}",
            f"- **Baseline AUC-ROC:** {baseline_auc:.4f}",
            f"- **Baseline PR-AUC:** {baseline_pr:.4f}",
            f"- **Top-K features removed (one at a time):** {options['top_k']}",
            "",
            TAKEAWAY_MARKER_BEGIN,
            "",
            "| Feature removed | AUC without | \u0394AUC | \u0394PR-AUC |",
            "|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                f"| {r['Feature removed']} | {r['AUC without feature']:.4f} | "
                f"{r['\u0394AUC']:+.4f} | {r['\u0394PR-AUC']:+.4f} |"
            )
        lines.append("")
        lines.append(TAKEAWAY_MARKER_END)
        lines.append("")
        lines.append("## Takeaway")
        lines.append("")
        lines.append(
            "_Human-written interpretation goes here. Edit freely - this section "
            "is preserved on future `make ablate` runs._"
        )
        return "\n".join(lines)

    def _write_preserving_takeaway(
        self, path: pathlib.Path, new_content: str
    ) -> None:
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if TAKEAWAY_MARKER_END in existing:
                after = existing.split(TAKEAWAY_MARKER_END, 1)[1]
                new_header = new_content.split(TAKEAWAY_MARKER_END)[0]
                path.write_text(new_header + TAKEAWAY_MARKER_END + after, encoding="utf-8")
                return
        path.write_text(new_content, encoding="utf-8")
