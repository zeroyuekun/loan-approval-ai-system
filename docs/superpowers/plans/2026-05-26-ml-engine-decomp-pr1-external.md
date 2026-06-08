# ml_engine decomposition PR-1 — external/ subpackage

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the seven external-integration adapters out of the flat `backend/apps/ml_engine/services/` directory into a focused `external/` subpackage, renaming them to drop the redundant `_service` suffix. Establishes the decomposition pattern the rest of the cycle follows.

**Architecture:** Pure refactor — `git mv` + path updates + a re-export `__init__.py` so any caller using the old paths keeps working. Zero behaviour change. Test suite must stay green at every commit.

**Tech Stack:** Python imports, pytest-django.

**Source spec:** [ml_engine decomposition](../specs/2026-05-25-ml-engine-decomposition-design.md).

---

## File map (one atomic commit)

**Move + rename:**
| From | To |
|------|-----|
| `backend/apps/ml_engine/services/credit_bureau_service.py` | `backend/apps/ml_engine/services/external/credit_bureau.py` |
| `backend/apps/ml_engine/services/open_banking_service.py` | `backend/apps/ml_engine/services/external/open_banking.py` |
| `backend/apps/ml_engine/services/property_data_service.py` | `backend/apps/ml_engine/services/external/property_data.py` |
| `backend/apps/ml_engine/services/macro_data_service.py` | `backend/apps/ml_engine/services/external/macro_data.py` |
| `backend/apps/ml_engine/services/plaid_patterns_service.py` | `backend/apps/ml_engine/services/external/plaid_patterns.py` |
| `backend/apps/ml_engine/services/geocoding_service.py` | `backend/apps/ml_engine/services/external/geocoding.py` |
| `backend/apps/ml_engine/services/benchmark_resolver.py` | `backend/apps/ml_engine/services/external/benchmark_resolver.py` |

**Create:**
- `backend/apps/ml_engine/services/external/__init__.py` — re-exports the public names from each module, with `__all__` listed.

**Update imports (8 sites, recon-verified):**
- `backend/apps/ml_engine/services/calibration_validator.py:47` — lazy `from apps.ml_engine.services.macro_data_service import ...`
- 7 test files under `backend/tests/`: `test_credit_bureau_service.py`, `test_open_banking_service.py`, `test_property_data_service.py`, `test_macro_data_service.py`, `test_plaid_patterns_service.py`, `test_geocoding_service.py`, `test_apra_calibration.py`

## Steps

- [ ] **Step 1: Create `external/__init__.py` with re-exports (so the OLD paths keep working via shim — important for downstream PRs)**

Create `backend/apps/ml_engine/services/external/__init__.py`:

```python
"""External integration adapters (CDR sandbox, credit bureau, property,
macro, geocoding, benchmarks).

This subpackage was extracted from the flat ml_engine/services/ directory
on 2026-05-26 as PR-1 of the decomposition cycle (see
docs/superpowers/specs/2026-05-25-ml-engine-decomposition-design.md).

Re-exports preserve public API. Direct imports from this subpackage are
preferred for new code:

    from apps.ml_engine.services.external.credit_bureau import CreditBureauService
"""
from apps.ml_engine.services.external.credit_bureau import (
    CreditBureauService,
    CreditReport,
    CREDIT_REPORT_BOUNDS,
)
from apps.ml_engine.services.external.open_banking import (
    OpenBankingProfile,
    OpenBankingService,
)
from apps.ml_engine.services.external.property_data import PropertyDataService
from apps.ml_engine.services.external.macro_data import MacroDataService
from apps.ml_engine.services.external.plaid_patterns import (
    PlaidPatternsService,
)
from apps.ml_engine.services.external.geocoding import GeocodingService
from apps.ml_engine.services.external.benchmark_resolver import (
    BenchmarkResolver,
)

__all__ = [
    "CreditBureauService",
    "CreditReport",
    "CREDIT_REPORT_BOUNDS",
    "OpenBankingProfile",
    "OpenBankingService",
    "PropertyDataService",
    "MacroDataService",
    "PlaidPatternsService",
    "GeocodingService",
    "BenchmarkResolver",
]
```

(Names verified by inspecting the source files during recon. If a public name turns out to differ, fix here.)

- [ ] **Step 2: `git mv` the seven files**

```bash
mkdir -p backend/apps/ml_engine/services/external
git mv backend/apps/ml_engine/services/credit_bureau_service.py    backend/apps/ml_engine/services/external/credit_bureau.py
git mv backend/apps/ml_engine/services/open_banking_service.py     backend/apps/ml_engine/services/external/open_banking.py
git mv backend/apps/ml_engine/services/property_data_service.py    backend/apps/ml_engine/services/external/property_data.py
git mv backend/apps/ml_engine/services/macro_data_service.py       backend/apps/ml_engine/services/external/macro_data.py
git mv backend/apps/ml_engine/services/plaid_patterns_service.py   backend/apps/ml_engine/services/external/plaid_patterns.py
git mv backend/apps/ml_engine/services/geocoding_service.py        backend/apps/ml_engine/services/external/geocoding.py
git mv backend/apps/ml_engine/services/benchmark_resolver.py       backend/apps/ml_engine/services/external/benchmark_resolver.py
```

- [ ] **Step 3: Update the single non-test import site**

Edit `backend/apps/ml_engine/services/calibration_validator.py` line 47:

```python
            from apps.ml_engine.services.macro_data_service import (
```
to:
```python
            from apps.ml_engine.services.external.macro_data import (
```

- [ ] **Step 4: Update the 7 test import sites**

```python
# backend/tests/test_credit_bureau_service.py:7
from apps.ml_engine.services.credit_bureau_service import (
# becomes:
from apps.ml_engine.services.external.credit_bureau import (

# backend/tests/test_open_banking_service.py:6
from apps.ml_engine.services.open_banking_service import (
# becomes:
from apps.ml_engine.services.external.open_banking import (

# backend/tests/test_property_data_service.py:6
from apps.ml_engine.services.property_data_service import PropertyDataService
# becomes:
from apps.ml_engine.services.external.property_data import PropertyDataService

# backend/tests/test_macro_data_service.py:10
from apps.ml_engine.services.macro_data_service import (
# becomes:
from apps.ml_engine.services.external.macro_data import (

# backend/tests/test_plaid_patterns_service.py:12
from apps.ml_engine.services.plaid_patterns_service import (
# becomes:
from apps.ml_engine.services.external.plaid_patterns import (

# backend/tests/test_geocoding_service.py:12
from apps.ml_engine.services.geocoding_service import (
# becomes:
from apps.ml_engine.services.external.geocoding import (

# backend/tests/test_apra_calibration.py:10
from apps.ml_engine.services.macro_data_service import MacroDataService
# becomes:
from apps.ml_engine.services.external.macro_data import MacroDataService
```

- [ ] **Step 5: Search for any stragglers — should find zero**

```bash
grep -rn "from apps.ml_engine.services.\(credit_bureau_service\|open_banking_service\|property_data_service\|macro_data_service\|plaid_patterns_service\|geocoding_service\)\|apps.ml_engine.services.benchmark_resolver" backend/ 2>&1 | head -10
```

Expected: empty output (all 8 sites updated). If anything appears, update those imports too.

- [ ] **Step 6: Run the targeted test files first**

```bash
docker compose exec -T backend pytest tests/test_credit_bureau_service.py tests/test_open_banking_service.py tests/test_property_data_service.py tests/test_macro_data_service.py tests/test_plaid_patterns_service.py tests/test_geocoding_service.py tests/test_apra_calibration.py -v
```

Expected: all green. Any import error here means an import path wasn't updated.

- [ ] **Step 7: Run the full backend suite**

```bash
docker compose exec -T backend pytest -v 2>&1 | tail -20
```

Expected: same pass/fail count as before the refactor (the refactor is behaviour-neutral).

- [ ] **Step 8: Commit**

```bash
git add backend/apps/ml_engine/services/external/ backend/apps/ml_engine/services/calibration_validator.py backend/tests/test_*.py
git commit -m "$(cat <<'EOF'
refactor(ml_engine): extract external/ subpackage (PR-1 of decomp)

Moves 7 external-integration adapters from the flat services/
directory into a focused external/ subpackage and drops the
redundant _service filename suffix:

  credit_bureau_service.py   -> external/credit_bureau.py
  open_banking_service.py    -> external/open_banking.py
  property_data_service.py   -> external/property_data.py
  macro_data_service.py      -> external/macro_data.py
  plaid_patterns_service.py  -> external/plaid_patterns.py
  geocoding_service.py       -> external/geocoding.py
  benchmark_resolver.py      -> external/benchmark_resolver.py

Updates the 8 import sites (1 source: calibration_validator.py;
7 tests under backend/tests/) and adds an external/__init__.py
re-exporting the public names so downstream PRs in the cycle
have a stable import target.

Pure refactor — git-mv-only except for the new __init__.py and
the 8 import-path updates. Zero behaviour change; full backend
suite passes unchanged.

Implements PR-1 of docs/superpowers/specs/2026-05-25-ml-engine-decomposition-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Acceptance

- `git diff` for each moved file is empty (proves real move via git mv).
- `grep -rn "from apps.ml_engine.services.\(credit_bureau_service\|...\)"` finds zero results.
- `docker compose exec backend pytest` passes the same number of tests as before this PR.
- `from apps.ml_engine.services.external import CreditBureauService` works (re-export).
- `from apps.ml_engine.services.external.credit_bureau import CreditBureauService` also works (direct).
