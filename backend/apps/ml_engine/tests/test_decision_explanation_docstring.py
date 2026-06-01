import apps.ml_engine.services.decision_explanation as de


def test_module_docstring_scopes_consolidation_to_structured_surfaces():
    doc = (de.__doc__ or "").lower()
    # The consolidation claim must be scoped to the STRUCTURED customer surfaces.
    assert "structured" in doc
    # The email prose path is intentionally separate — the docstring must say so
    # explicitly and must NOT claim this module owns the email ranking.
    assert "email" in doc
    assert "separate" in doc
    assert "does not own the email" in doc
