"""L15: determinism guard for the UnderwritingEngine.compute_approval split.

compute_approval drives the ground-truth labels the ML model learns from, and
draws latent signals from a shared rng. These tests pin its determinism so the
per-gate helper extraction cannot silently shift the draw order (and thus the
labels).

compute_approval reads df["_existing_dti"] and df["_age_proxy"], which
generate() adds transiently then drops. The fixture reconstructs them so the
call does not KeyError.
"""

import numpy as np

from apps.ml_engine.services.data_generator import DataGenerator
from apps.ml_engine.services.underwriting_engine import UnderwritingEngine


def _frame(n=300, seed=7):
    df = DataGenerator().generate(num_records=n, random_seed=seed).copy()
    # Reconstruct the two transient columns generate() drops before returning.
    # _existing_dti: the non-loan DTI component (existing debts relative to income).
    df["_existing_dti"] = (df["debt_to_income"] - df["loan_amount"] / df["annual_income"]).clip(lower=0)
    # _age_proxy: an applicant-age proxy (employment_length anchored at 23yo entry).
    df["_age_proxy"] = (df["employment_length"] + 23).clip(upper=70)
    return df


def test_compute_approval_deterministic_for_same_rng():
    df = _frame()
    a1, t1, c1 = UnderwritingEngine().compute_approval(df.copy(), np.random.default_rng(99))
    a2, t2, c2 = UnderwritingEngine().compute_approval(df.copy(), np.random.default_rng(99))
    assert list(a1) == list(a2)
    assert list(t1) == list(t2)
    assert [len(x) for x in c1] == [len(x) for x in c2]


def test_compute_approval_approval_count_pinned():
    df = _frame()
    a1, _t1, _c1 = UnderwritingEngine().compute_approval(df.copy(), np.random.default_rng(99))
    # Pinned from the first live run on the pre-refactor code (captured, not invented).
    assert int(np.sum(a1)) == APPROVAL_COUNT


def test_compute_approval_returns_three_aligned_outputs():
    df = _frame()
    approved, approval_type, conditions = UnderwritingEngine().compute_approval(df.copy(), np.random.default_rng(99))
    assert len(approved) == len(df)
    assert len(approval_type) == len(df)
    assert len(conditions) == len(df)


# Pinned after first live run (see test_compute_approval_approval_count_pinned).
# _frame(n=300, seed=7), rng seed 99.
APPROVAL_COUNT = 176
