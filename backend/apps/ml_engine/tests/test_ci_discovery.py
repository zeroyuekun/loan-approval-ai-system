"""Placeholder test that proves CI now collects tests under apps/*/tests/.

This test exists to verify that the `testpaths = tests apps` entry in
pytest.ini (added in the same PR as this file) caused CI to start collecting
the six existing quote tests in this directory. Safe to delete in a
follow-up commit once CI has been observed to collect the quote tests.
"""


def test_apps_tests_directory_is_collected() -> None:
    """Trivially passes; its presence in CI output proves collection works."""
    assert 1 + 1 == 2
