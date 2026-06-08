"""L24 — watchdog DB-connection reaper targets idle-in-transaction only.

Plain ``idle`` is the normal resting state of a pooled connection; terminating
it churns the pool. The real leak signal is ``idle in transaction``. The kill
must also be scoped to THIS app's connections via ``application_name`` so it
can never terminate another service's connections.

The terminate SQL is asserted as a string (it is impractical to wedge a real
idle-in-transaction backend in a unit test).
"""

import re

from apps.agents.management.commands.watchdog import IDLE_IN_TX_TERMINATE_SQL


def test_terminate_sql_targets_idle_in_transaction():
    assert "idle in transaction" in IDLE_IN_TX_TERMINATE_SQL
    assert "idle in transaction (aborted)" in IDLE_IN_TX_TERMINATE_SQL
    # Must NOT target a bare `state = 'idle'` (that would kill healthy pooled conns).
    assert not re.search(r"state\s*=\s*'idle'", IDLE_IN_TX_TERMINATE_SQL)


def test_terminate_sql_scoped_by_application_name():
    # Scoped so it cannot kill another service's connections.
    assert "application_name = %s" in IDLE_IN_TX_TERMINATE_SQL
