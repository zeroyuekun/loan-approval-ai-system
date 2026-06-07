"""compute_approval per-gate helpers (L15 decomposition, sibling module).

Verbatim extractions of ``UnderwritingEngine.compute_approval`` gates that do
not depend on engine instance state (or depend only on an explicitly-passed
``get_hem`` callable). They live here purely to keep ``underwriting_engine.py``
under the file-size ratchet — the bodies are unchanged.

They are called at the SAME point in sequence in ``compute_approval``, threading
the same ``rng`` in the same draw order, so the approval labels are byte-for-byte
identical. The determinism snapshot test
(``tests/test_underwriting_compute_approval.py``) guards this invariant.
"""

import numpy as np


def simulate_latent_signals(df, n, rng):
    """Simulate latent underwriter signals not available to the model as
    features (doc quality, savings pattern, employer stability, relationship
    bonus). Verbatim extraction of compute_approval's STEP 0 — draws from
    the same rng in the same order (L15)."""
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


def compute_effective_expenses(df, get_hem):
    """STEP 6: declared expenses floored at the HEM benchmark. No rng draws
    (L15 verbatim extraction). ``get_hem`` is the engine's HEM lookup."""
    hem_values = np.array(
        [
            get_hem(at, dep, inc, st)
            for at, dep, inc, st in zip(
                df["applicant_type"], df["number_of_dependants"], df["annual_income"], df["state"], strict=False
            )
        ]
    )
    return np.maximum(df["monthly_expenses"], hem_values)
