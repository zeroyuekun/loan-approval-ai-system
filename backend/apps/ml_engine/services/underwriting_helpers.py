"""compute_approval per-gate helpers (sibling module of underwriting_engine).

Verbatim extractions of ``UnderwritingEngine.compute_approval`` gates that do
not depend on engine instance state (or depend only on an explicitly-passed
``get_hem`` callable). They live here purely to keep ``underwriting_engine.py``
under the file-size ratchet — the bodies are unchanged.

They are called at the SAME point in sequence in ``compute_approval``, threading
the same ``rng`` in the same draw order, so the approval labels are byte-for-byte
identical. The determinism snapshot test
(``tests/test_underwriting_compute_approval.py``) guards this invariant.

``apply_tenure_shading``, ``marginal_tax`` and ``EXISTING_DEBT_MONTHLY_RATE``
are also used by the recommendation engine, so denial offers are sized with
the rules that label the training data.
"""

import numpy as np

# Monthly servicing on existing (non-new-loan) debt: ~6% over 20 years.
EXISTING_DEBT_MONTHLY_RATE = 0.0072


def simulate_latent_signals(df, n, rng):
    """Simulate latent underwriter signals not available to the model as
    features (doc quality, savings pattern, employer stability, relationship
    bonus). Verbatim extraction of compute_approval's STEP 0 — draws from
    the same rng in the same order."""
    # Documentation quality: how clean/complete the applicant's
    # paperwork is (payslips, tax returns, bank statements).
    # Strong effect on underwriter confidence. Scale 0-1.
    doc_quality = np.clip(rng.beta(5, 2, size=n), 0, 1)
    # Self-employed have messier documentation (ATO tax returns
    # vs simple PAYG summaries)
    doc_quality[df["employment_type"] == "self_employed"] *= rng.uniform(
        0.6, 0.9, size=(df["employment_type"] == "self_employed").sum()
    )
    doc_quality[df["employment_type"] == "payg_casual"] *= rng.uniform(
        0.7, 0.95, size=(df["employment_type"] == "payg_casual").sum()
    )

    # Savings history quality: demonstrates genuine savings pattern
    # (3+ months of consistent deposits). Banks assess this from
    # statements but it's not a structured feature.
    savings_pattern = rng.beta(3, 3, size=n)

    # Employer/industry stability: banks internally rate employers
    # and industries (e.g. mining vs government vs startup).
    # Not visible in application data.
    employer_stability = rng.beta(4, 2, size=n)

    # Relationship factor: existing customers with good history
    # get benefit of the doubt on borderline cases. Simulates
    # branch manager discretion.
    relationship_bonus = rng.choice(
        [0.0, 0.03, 0.06, 0.10],
        size=n,
        p=[0.50, 0.25, 0.15, 0.10],
    )
    return doc_quality, savings_pattern, employer_stability, relationship_bonus


def apply_tenure_shading(base_shade, employment_type, employment_length):
    """STEP 1 tenure overrides on top of the base ``INCOME_SHADING`` factor
    (Big 4 2025 practice; self-employed accepted from 1 year, 2 before 2025):

    - self-employed: <1yr 0.65, 1-2yr base 0.75, 2yr+ 0.82
    - casual: <1yr 0.60, 1-2yr base 0.80, 2yr+ 1.00

    compute_approval's STEP 2 still denies self-employed under 1 year and
    casual under 6 months (6-12 months only with credit 700+). Works
    element-wise on arrays/Series or on scalars, so the underwriting engine
    and the recommendation engine shade income with the same rules. No rng
    draws."""
    employment_type = np.asarray(employment_type)
    employment_length = np.asarray(employment_length)
    self_employed = employment_type == "self_employed"
    casual = employment_type == "payg_casual"
    shade = np.where(self_employed & (employment_length >= 2), 0.82, base_shade)
    shade = np.where(self_employed & (employment_length < 1), 0.65, shade)
    shade = np.where(casual & (employment_length >= 2), 1.00, shade)
    return np.where(casual & (employment_length < 1), 0.60, shade)


def marginal_tax(annual_income):
    """Annual income tax at the Stage 3 resident rates (from 1 July 2024).
    Works element-wise on arrays/Series or on a scalar (a 0-d array), so both
    engines deduct the same tax. No rng draws."""
    return np.where(
        annual_income <= 18200,
        0,
        np.where(
            annual_income <= 45000,
            (annual_income - 18200) * 0.16,
            np.where(
                annual_income <= 135000,
                4288 + (annual_income - 45000) * 0.30,
                np.where(
                    annual_income <= 190000,
                    31288 + (annual_income - 135000) * 0.37,
                    51638 + (annual_income - 190000) * 0.45,
                ),
            ),
        ),
    )


def compute_effective_expenses(df, get_hem):
    """STEP 6: declared expenses floored at the HEM benchmark. No rng draws
    (verbatim extraction). ``get_hem`` is the engine's HEM lookup."""
    hem_values = np.array(
        [
            get_hem(at, dep, inc, st)
            for at, dep, inc, st in zip(
                df["applicant_type"], df["number_of_dependants"], df["annual_income"], df["state"], strict=False
            )
        ]
    )
    return np.maximum(df["monthly_expenses"], hem_values)
