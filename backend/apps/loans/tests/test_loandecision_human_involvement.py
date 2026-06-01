def test_human_involvement_field_defaults_to_none():
    from apps.loans.models import LoanDecision

    field = LoanDecision._meta.get_field("human_involvement")
    assert field.default == "none"
    assert {c[0] for c in field.choices} == {"none", "assisted", "overridden"}
