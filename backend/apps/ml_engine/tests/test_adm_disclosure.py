from apps.ml_engine.services.adm_disclosure import ADM_REGISTER, resolve_adm_disclosure


def test_solely_automated_decline_has_human_review_right():
    d = resolve_adm_disclosure(decision="denied", requires_human_review=False)
    assert d["mode"] == "solely_automated"
    assert d["human_review_right"] is True
    assert "credit" in " ".join(d["info_used"]).lower()
    assert d["review_request_path"] == "/api/v1/loans/decision-reviews/"


def test_escalated_decision_is_assisted():
    d = resolve_adm_disclosure(decision="denied", requires_human_review=True)
    assert d["mode"] == "assisted"
    assert d["human_review_right"] is True


def test_register_modes_are_known():
    assert {e["mode"] for e in ADM_REGISTER.values()} <= {"solely_automated", "assisted", "human"}


def test_officer_override_is_human_mode():
    d = resolve_adm_disclosure(decision="approved", human_involvement="overridden")
    assert d["mode"] == "human"
    assert "officer" in d["summary"].lower()
    assert d["human_review_right"] is True


def test_assisted_via_involvement_flag():
    d = resolve_adm_disclosure(decision="denied", human_involvement="assisted")
    assert d["mode"] == "assisted"


def test_register_includes_human_override_with_human_mode():
    assert ADM_REGISTER["human_override"]["mode"] == "human"
