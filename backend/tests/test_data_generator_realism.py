"""Class-balance regression for ``DataGenerator`` synthetic output.

The training distribution's positive-class rate is a load-bearing property:
calibration of every downstream metric depends on it staying inside a
documented band. A future tweak to ``DataGenerator`` (a new sub-population,
a re-weighted approval threshold, a label-noise change) could silently
shift the rate without anyone noticing until production AUC moves.

These tests act as a tripwire. If they fail the change is not necessarily
wrong — but it MUST be a deliberate, documented change to
``backend/docs/CALIBRATION_SOURCES.md`` (the manifest) at the same time.

Band: ``[0.50, 0.65]``. Empirically the project runs at ~0.56
(measured 0.5595 on seed=42, n=10000; spread 0.0162 across seeds 1/42/99).
The deliberate gap to the real-world AU 90+ day arrears rate of ~1.68%
exists for ML tractability and is acknowledged in the manifest.
"""

import pytest

from apps.ml_engine.services.datagen.data_generator import DataGenerator

# Allowable band for the synthetic positive-class rate. Wide enough to
# absorb seed-level noise (observed spread 1.62pp), narrow enough to catch
# any real distribution shift.
POSITIVE_CLASS_RATE_LOWER = 0.50
POSITIVE_CLASS_RATE_UPPER = 0.65


def _positive_class_rate(num_records: int, random_seed: int) -> float:
    """Generate synthetic data and return the positive-class rate of ``approved``."""
    df = DataGenerator().generate(num_records=num_records, random_seed=random_seed)
    return float(df["approved"].mean())


def test_synthetic_positive_class_rate_within_band():
    """Positive-class rate stays inside the documented [0.50, 0.65] band.

    If this fails, either the calibration drifted or the manifest is out of
    date. Update ``backend/docs/CALIBRATION_SOURCES.md`` in the SAME PR
    that changes the rate; do not silently widen this band.
    """
    rate = _positive_class_rate(num_records=10000, random_seed=42)
    assert POSITIVE_CLASS_RATE_LOWER <= rate <= POSITIVE_CLASS_RATE_UPPER, (
        f"Synthetic positive-class rate {rate:.4f} fell outside the documented "
        f"band [{POSITIVE_CLASS_RATE_LOWER:.2f}, {POSITIVE_CLASS_RATE_UPPER:.2f}]. "
        f"Either the DataGenerator calibration drifted (re-train + investigate) "
        f"or the manifest is stale (update backend/docs/CALIBRATION_SOURCES.md "
        f"and this band in the same PR). Measured baseline: ~0.56 on seed=42, "
        f"n=10000."
    )


@pytest.mark.parametrize("seed", [1, 42, 99])
def test_synthetic_class_balance_stable_across_seeds(seed):
    """Across seeds 1/42/99 the positive-class rate spread stays ≤ 5pp.

    Empirically the spread is ~1.62pp; 5pp is a generous tripwire. A
    larger spread indicates the synthetic distribution has become
    seed-sensitive, which would undermine reproducibility of every
    downstream metric.
    """
    rates = {s: _positive_class_rate(num_records=5000, random_seed=s) for s in [1, 42, 99]}
    spread = max(rates.values()) - min(rates.values())
    assert spread <= 0.05, (
        f"Synthetic positive-class rate spread {spread:.4f} across seeds "
        f"1/42/99 exceeded 5pp tolerance. Per-seed rates: {rates}. The "
        f"distribution should be reproducible — a large seed spread suggests "
        f"non-determinism crept into DataGenerator (check rng usage)."
    )
