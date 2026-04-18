"""Guard test: no `datetime.utcnow()` in ml_engine services.

Python 3.13 deprecates `datetime.utcnow()`; Python 3.14+ is scheduled to
remove it. This test scans the services directory for the call and fails
if any remain.
"""
from pathlib import Path


def test_no_utcnow_in_ml_engine_services():
    services_dir = Path(__file__).resolve().parents[1] / "apps" / "ml_engine" / "services"
    offenders: list[str] = []
    for py in services_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "datetime.utcnow()" in text:
            offenders.append(str(py.relative_to(services_dir.parent.parent.parent)))
    assert not offenders, (
        "datetime.utcnow() is deprecated in Python 3.13+; "
        "use datetime.now(UTC) instead. Offenders: " + ", ".join(offenders)
    )
