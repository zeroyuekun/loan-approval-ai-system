"""Unit tests for the champion/challenger shadow-scoring helper.

`score_challengers_shadow` is the block carved out of `ModelPredictor.predict()`
during Arm C Phase 1. It:

- Queries `ModelVersion` for challengers (is_active=False, 0 < traffic_pct < 100,
  excluding the champion).
- For up to `max_challengers` rows, invokes the supplied scoring callback and
  writes a `PredictionLog` row per successful score.
- Swallows per-challenger exceptions so one broken challenger doesn't block
  the others. Swallows outer exceptions so a missing `PredictionLog` table
  cannot break the hot-path decision.

Pure unit tests: we mock the ORM accessors (`ModelVersion.objects.filter`,
`PredictionLog.objects.create`) rather than hitting a real DB. This matches
the pattern used by the other extraction tests (test_prediction_features.py,
test_prediction_diagnostics.py) so the suite stays runnable without Docker.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from apps.ml_engine.services.shadow_scoring import score_challengers_shadow


def _mk_version(pk, version="v1.1.0", optimal_threshold=0.5):
    return SimpleNamespace(pk=pk, version=version, optimal_threshold=optimal_threshold)


def _patch_challengers(challenger_list, exclude_return=None):
    """Make `ModelVersion.objects.filter(...).exclude(...)` return `challenger_list`.

    The challenger set is evaluated via slicing (`challengers[:max]`), so the
    mock has to support `__getitem__` — we return a plain list.
    """
    mock_qs = MagicMock()
    mock_qs.exclude.return_value = exclude_return if exclude_return is not None else challenger_list
    return patch(
        "apps.ml_engine.services.shadow_scoring.ModelVersion.objects.filter",
        return_value=mock_qs,
    )


class TestScoreChallengersShadow:
    def test_no_challengers_is_noop(self):
        app = SimpleNamespace(pk=1)
        champion = _mk_version(pk=10, version="v1.0.0-champ")
        scorer = MagicMock()

        with (
            _patch_challengers([]),
            patch("apps.ml_engine.services.shadow_scoring.PredictionLog.objects.create") as create,
        ):
            score_challengers_shadow(
                application=app,
                champion_version=champion,
                champion_probability=0.3,
                champion_prediction_label="denied",
                features_df=pd.DataFrame([{"annual_income": 100_000}]),
                score_fn=scorer,
            )

        scorer.assert_not_called()
        create.assert_not_called()

    def test_scores_one_challenger_and_logs(self):
        app = SimpleNamespace(pk=1)
        champion = _mk_version(pk=10)
        challenger = _mk_version(pk=11, version="v1.1.0-chal")

        scorer = MagicMock(return_value=(0.72, "approved"))

        with (
            _patch_challengers([challenger]),
            patch("apps.ml_engine.services.shadow_scoring.PredictionLog.objects.create") as create,
        ):
            score_challengers_shadow(
                application=app,
                champion_version=champion,
                champion_probability=0.3,
                champion_prediction_label="denied",
                features_df=pd.DataFrame([{"annual_income": 100_000}]),
                score_fn=scorer,
            )

        scorer.assert_called_once()
        create.assert_called_once()
        kwargs = create.call_args.kwargs
        assert kwargs["model_version"] is challenger
        assert kwargs["application"] is app
        assert kwargs["prediction"] == "approved"
        assert kwargs["probability"] == 0.72

    def test_caps_at_max_challengers(self):
        app = SimpleNamespace(pk=1)
        champion = _mk_version(pk=10)
        challengers = [_mk_version(pk=i) for i in (11, 12, 13, 14)]

        scorer = MagicMock(return_value=(0.5, "approved"))

        with (
            _patch_challengers(challengers),
            patch("apps.ml_engine.services.shadow_scoring.PredictionLog.objects.create") as create,
        ):
            score_challengers_shadow(
                application=app,
                champion_version=champion,
                champion_probability=0.3,
                champion_prediction_label="denied",
                features_df=pd.DataFrame([{"annual_income": 100_000}]),
                score_fn=scorer,
                max_challengers=2,
            )

        assert scorer.call_count == 2
        assert create.call_count == 2

    def test_excludes_champion_by_pk(self):
        """We don't re-test the ORM here — but we DO verify `.exclude(pk=champion.pk)`
        is invoked by the helper, which is the mechanism the query relies on.
        """
        app = SimpleNamespace(pk=1)
        champion = _mk_version(pk=10)

        # Build a filter mock whose .exclude is inspectable.
        mock_qs = MagicMock()
        mock_qs.exclude.return_value = []
        scorer = MagicMock()

        with patch(
            "apps.ml_engine.services.shadow_scoring.ModelVersion.objects.filter",
            return_value=mock_qs,
        ) as filter_mock:
            score_challengers_shadow(
                application=app,
                champion_version=champion,
                champion_probability=0.3,
                champion_prediction_label="denied",
                features_df=pd.DataFrame([{"annual_income": 100_000}]),
                score_fn=scorer,
            )

        filter_mock.assert_called_once_with(
            is_active=False,
            traffic_percentage__gt=0,
            traffic_percentage__lt=100,
        )
        mock_qs.exclude.assert_called_once_with(pk=10)

    def test_per_challenger_exception_does_not_stop_others(self):
        app = SimpleNamespace(pk=1)
        champion = _mk_version(pk=10)
        challengers = [_mk_version(pk=11), _mk_version(pk=12)]

        scorer = MagicMock(side_effect=[RuntimeError("boom"), (0.6, "approved")])

        with (
            _patch_challengers(challengers),
            patch("apps.ml_engine.services.shadow_scoring.PredictionLog.objects.create") as create,
        ):
            score_challengers_shadow(
                application=app,
                champion_version=champion,
                champion_probability=0.3,
                champion_prediction_label="denied",
                features_df=pd.DataFrame([{"annual_income": 100_000}]),
                score_fn=scorer,
            )

        # Only the working challenger's log got written.
        assert create.call_count == 1

    def test_log_creation_failure_does_not_stop_others(self):
        app = SimpleNamespace(pk=1)
        champion = _mk_version(pk=10)
        challengers = [_mk_version(pk=11), _mk_version(pk=12)]

        scorer = MagicMock(return_value=(0.5, "approved"))

        # First .create raises, second succeeds.
        with (
            _patch_challengers(challengers),
            patch(
                "apps.ml_engine.services.shadow_scoring.PredictionLog.objects.create",
                side_effect=[RuntimeError("db write failed"), MagicMock()],
            ) as create,
        ):
            score_challengers_shadow(
                application=app,
                champion_version=champion,
                champion_probability=0.3,
                champion_prediction_label="denied",
                features_df=pd.DataFrame([{"annual_income": 100_000}]),
                score_fn=scorer,
            )

        # Both attempts made; the second succeeded. Helper did not raise.
        assert create.call_count == 2

    def test_outer_query_failure_is_swallowed(self):
        app = SimpleNamespace(pk=1)
        champion = _mk_version(pk=10)

        with patch(
            "apps.ml_engine.services.shadow_scoring.ModelVersion.objects.filter",
            side_effect=RuntimeError("db down"),
        ):
            # Must not raise.
            score_challengers_shadow(
                application=app,
                champion_version=champion,
                champion_probability=0.3,
                champion_prediction_label="denied",
                features_df=pd.DataFrame([{"annual_income": 100_000}]),
                score_fn=MagicMock(),
            )

    def test_score_fn_receives_copied_features_df(self):
        """Callers expect `score_fn` to get a DataFrame it can mutate freely."""
        app = SimpleNamespace(pk=1)
        champion = _mk_version(pk=10)
        challenger = _mk_version(pk=11)

        input_df = pd.DataFrame([{"annual_income": 100_000}])

        received = []

        def scorer(_mv, df):
            received.append(df)
            return (0.5, "approved")

        with (
            _patch_challengers([challenger]),
            patch("apps.ml_engine.services.shadow_scoring.PredictionLog.objects.create"),
        ):
            score_challengers_shadow(
                application=app,
                champion_version=champion,
                champion_probability=0.3,
                champion_prediction_label="denied",
                features_df=input_df,
                score_fn=scorer,
            )

        assert len(received) == 1
        # Must be a different DataFrame object than the caller passed in —
        # score_fn is free to mutate without affecting the champion pipeline.
        assert received[0] is not input_df
