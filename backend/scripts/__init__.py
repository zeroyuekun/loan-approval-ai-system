"""Standalone ML / ops scripts.

These modules live outside Django apps because they are not part of the
request-handling code path. They are run via ``python scripts/<name>.py``
or via Makefile targets (see the ``benchmark-gmsc`` target).
"""
