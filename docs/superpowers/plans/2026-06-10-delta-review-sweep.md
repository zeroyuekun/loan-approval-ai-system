# Delta Review & Fix Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Review every line merged since the v1.11.1 full-codebase review at high effort and fix all confirmed findings, landing one CI-gated PR per slice, so "the delta is fully reviewed and fixed" is a checkable claim.

**Architecture:** Sequential slice-by-slice sweep (agents+email_engine → ml_engine → frontend → cross-cutting tail). Each slice runs the proven #245 loop: 7 parallel finder agents → dedupe → 1 adversarial verifier per candidate → fix CONFIRMED findings test-first → full test gate → PR → owner-approved merge. Findings needing structural rework become GitHub issues, never in-sweep fixes.

**Tech Stack:** Claude Code Agent tool (general-purpose subagents), pytest in the `loan-approval-ai-system-backend-1` container, ruff on host, vitest in frontend container/host, gh CLI.

**Spec:** `docs/superpowers/specs/2026-06-10-delta-review-sweep-design.md`

---

## Shared material (used by every slice)

### Finder prompt template

Dispatch 7 Agent-tool subagents in ONE message (parallel), `subagent_type: general-purpose`. Each gets this prompt with `{ANGLE_BLOCK}` and `{SLICE_FILES}` substituted:

```text
You are a code-review finder agent ({ANGLE_NAME}) for repo C:\Users\Admin\loan-approval-ai-system
(Django + DRF backend, Next.js frontend). Review scope: the code merged since tag v1.11.1 in these
files ONLY:

{SLICE_FILES}

Get the delta yourself: run `git diff v1.11.1..HEAD -- <paths>` for those paths. Bugs in unchanged
lines of a touched function are IN scope (the delta re-exposes them). Code outside these files is
out of scope.

{ANGLE_BLOCK}

Return up to 6 candidate findings as a JSON array, each:
{"file": "...", "line": <int>, "summary": "one line", "failure_scenario": "concrete inputs/state -> wrong output/crash"}.
Pass through every candidate with a nameable failure scenario — do NOT silently drop half-believed
candidates. Return [] only if truly nothing. Your final message must be ONLY the JSON array.
```

The 7 `{ANGLE_BLOCK}` values (use verbatim):

1. **Angle A — line-by-line:** "Read every hunk line by line, then Read the full enclosing function/class. For every line ask: what input, state, timing, or platform makes this line wrong? Inverted conditions, off-by-one, None deref, falsy-zero, copy-paste wrong variable, swallowed errors, exact-string fragility, kwargs mutation, getattr fallbacks masking misconfiguration."
2. **Angle B — removed-behavior:** "For every line the delta DELETES or replaces, name the invariant it enforced and verify the new code re-establishes it. Grep for consumers of deleted attributes/functions. Find tests that pinned old behavior. Check docs/ and workflows/ for claims the delta silently invalidates."
3. **Angle C — cross-file tracer:** "For each changed function, Grep its callers and callees across backend/ and frontend/. Check: new preconditions, changed return shapes, new exceptions, ordering dependencies, parallel hardcoded lists/maps that should have been co-updated (model lists, label maps, status enums, Py↔TS parity helpers)."
4. **Reuse:** "Flag new code that re-implements something the codebase already has. Grep utils/, shared service modules, bias/helpers.py, email_engine/services, frontend lib/. Name the existing helper to call instead."
5. **Simplification:** "Flag unnecessary complexity the delta adds: redundant/derivable state, copy-paste variation, dead code, comment drift (comments restating each other in multiple files). Name the simpler form."
6. **Efficiency:** "Flag wasted work: repeated I/O or queries (N+1), redundant computation, blocking work on hot paths or Celery tasks, missing select_related/prefetch on new querysets, React re-render traps (new objects in deps, missing memo on hot lists). Also cost: any API-charged path that grew. Name the cheaper alternative."
7. **Altitude:** "Check each change is implemented at the right depth, not a bandaid. Special cases bolted onto shared infrastructure, manually-maintained parallel registries, validation at the wrong layer, config knobs without validation. Compare against this codebase's own established patterns and name the right-depth alternative."

### Verifier prompt template

After collecting candidates: dedupe (same defect + same location → keep one), then dispatch ONE verifier per surviving candidate, all in one parallel batch:

```text
You are a code-review VERIFIER for repo C:\Users\Admin\loan-approval-ai-system. Verdict rules:
PLAUSIBLE by default — do not refute for being "speculative" when the runtime state is realistic
(races, rare-but-reachable error paths, falsy-zero, boundary off-by-one, config typos).
REFUTED only when constructible from the code: factually wrong (quote the line), provably
impossible (show the type/constant/invariant), or already handled (cite the guard).

CANDIDATE: {file}:{line} — {summary}. Failure scenario: {failure_scenario}

Verify against the actual code (Read the file, Grep callers as needed; run `git diff v1.11.1..HEAD --
{file}` for context). Return "VERDICT: CONFIRMED|PLAUSIBLE|REFUTED" then 2-3 sentences with file:line cites.
```

Keep CONFIRMED + PLAUSIBLE. Drop REFUTED (record them for the closing ledger).

### Per-finding fix loop (TDD)

For each kept finding, in severity order:

1. Write a failing test that reproduces the failure scenario (in the slice's test file, see each task).
2. Run it, confirm it FAILS for the stated reason: `docker exec loan-approval-ai-system-backend-1 python -m pytest <test_path>::<test_name> -v` (frontend: `docker exec loan-approval-ai-system-frontend-1 npx vitest run <file>` or host `npx vitest run`).
3. Apply the smallest fix following existing patterns.
4. Re-run the test: PASS. Run the module's existing tests too.
5. If the proper fix is structural rework (crosses the no-big-changes guardrail) or the finding is PLAUSIBLE with a non-trivial fix: instead of fixing, `gh issue create --title "<summary>" --body "<failure_scenario + file:line + verifier verdict>"` and record the issue number.

One commit per finding or per tightly-related finding group: `git commit -m "fix(<app>): <summary> (delta-sweep S<n>-F<k>)"`.

### Slice gate (before PR)

```powershell
# backend slices
docker exec loan-approval-ai-system-backend-1 python -m pytest apps tests -q
# expected: 0 failed EXCEPT the 4 known environmental failures in tests/test_email_generator.py
#   (test_generate_approval_email, test_generate_denial_email,
#    test_template_fallback_on_api_failure, test_denial_prompt_includes_offer_and_whitelists_amount)
#   — these fail only when local .env routes to a 500ing Ollama; verified pre-existing on clean tree 2026-06-10.
#   NOTE: slice 1 fixes the "Loan Loan" subject, so the FIRST of these may change failure message; it must not be "fixed" by weakening the test.
ruff check backend; ruff format --check backend
# frontend slice adds:
npx vitest run   # in frontend/ — 0 failures
```

### PR + merge gate

```powershell
git push -u origin <branch>
gh pr create --title "<slice title>" --body-file .tmp/pr-body-s<n>.md --base master
# PR body MUST contain the findings table: # | severity | file:line | finding | disposition (fixed/issue #N/refuted)
gh pr checks <PR#>    # poll until ALL pass — no fail, no pending (skipping is OK for conditional jobs)
```

Merge ONLY after asking the owner (AskUserQuestion) and getting explicit confirmation naming the admin bypass: `gh pr merge <PR#> --squash --admin --delete-branch`. After merge: `git checkout master; git pull`.

---

### Task 0: Preflight + slice manifests

**Files:**
- Create: `.tmp/sweep/slice1_files.txt`, `.tmp/sweep/slice2_files.txt`, `.tmp/sweep/slice3_files.txt`, `.tmp/sweep/slice4_files.txt`

- [ ] **Step 1: Confirm clean baseline**

Run: `git checkout master; git pull; git status --short; git log --oneline -1`
Expected: clean tree, HEAD at or after `3b1f0e7`.

- [ ] **Step 2: Generate slice manifests**

```powershell
New-Item -ItemType Directory -Force .tmp\sweep | Out-Null
git diff --name-only v1.11.1..HEAD -- backend/apps/agents backend/apps/email_engine | Out-File .tmp\sweep\slice1_files.txt -Encoding utf8
git diff --name-only v1.11.1..HEAD -- backend/apps/ml_engine | Out-File .tmp\sweep\slice2_files.txt -Encoding utf8
git diff --name-only v1.11.1..HEAD -- frontend/src | Out-File .tmp\sweep\slice3_files.txt -Encoding utf8
git diff --name-only v1.11.1..HEAD -- backend/apps/loans backend/apps/accounts backend/config .github/workflows tools/smoke_e2e.sh | Out-File .tmp\sweep\slice4_files.txt -Encoding utf8
Get-ChildItem .tmp\sweep | ForEach-Object { "$($_.Name): $((Get-Content $_.FullName | Measure-Object -Line).Lines) files" }
```

Expected: roughly 24 / 96 / 56 / 25–40 files. Exclude from manifests any file that no longer exists on HEAD (deleted files): filter with `Where-Object { Test-Path $_ }`.

- [ ] **Step 3: Create slice-1 branch**

Run: `git checkout -b review/delta-sweep-s1-agents-email` (branch from master; the spec branch `review/delta-sweep-since-v1.11.1` gets its spec commit cherry-picked into this branch: `git cherry-pick 0f52b33`)
Expected: branch exists, spec file present.

---

### Task 1: Slice 1 known fix — "Personal Loan Loan" subject

**Files:**
- Modify: `backend/apps/email_engine/services/template_fallback.py:30-45` (`_loan_type`)
- Test: `backend/apps/email_engine/tests/test_template_loan_type.py` (create)

- [ ] **Step 1: Write the failing test**

```python
"""_loan_type must not let callers render 'Personal Loan Loan' when the purpose
value already ends in 'Loan' (callers append ' Loan' themselves)."""

from apps.email_engine.services.template_fallback import _loan_type, generate_approval_template


def test_loan_type_strips_trailing_loan_word():
    assert _loan_type("Personal Loan") == "Personal"
    assert _loan_type("personal loan") == "Personal"
    assert _loan_type("debt_consolidation_loan") == "Debt Consolidation"


def test_loan_type_mapped_values_unchanged():
    assert _loan_type("personal") == "Personal"
    assert _loan_type("home") == "Home Purchase"
    assert _loan_type("home_improvement") == "Home Improvement"


def test_approval_subject_has_single_loan_word():
    result = generate_approval_template("Alex Chen", 20000.0, "Personal Loan")
    subject = result[0] if isinstance(result, tuple) else result["subject"]
    assert "Loan Loan" not in subject
    assert subject == "Congratulations! Your Personal Loan is Approved"
```

(Adjust the `generate_approval_template` return-shape access after reading its actual return statement — keep the two assertions.)

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec loan-approval-ai-system-backend-1 python -m pytest apps/email_engine/tests/test_template_loan_type.py -v`
Expected: FAIL — `_loan_type("Personal Loan")` returns `"Personal Loan"`, subject contains `"Personal Loan Loan"`.

- [ ] **Step 3: Implement the fix**

In `_loan_type`, replace the final return:

```python
    display = mapping.get(purpose.lower(), purpose.replace("_", " ").title())
    # Callers append " Loan" to this value; strip a trailing "Loan" so purpose
    # values that already include it ("Personal Loan") don't render "Loan Loan".
    if display.lower().endswith(" loan"):
        display = display[: -len(" loan")]
    return display
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec loan-approval-ai-system-backend-1 python -m pytest apps/email_engine/tests/test_template_loan_type.py tests/test_template_fallback.py -v`
Expected: all PASS (the 34 existing template-fallback tests must stay green).

- [ ] **Step 5: Check the sibling sites**

`template_fallback.py:564` uses the same `_loan_type` (now fixed). `lifecycle.py:42` builds `f"...Your {purpose.title()} Loan Application..."` — if `purpose` can already contain "loan", switch it to `_loan_type(purpose)`; Grep callers of the lifecycle function to confirm what `purpose` holds before changing. If callers only ever pass enum keys ("personal", "home"), leave it and note it in the PR body.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/email_engine/services/template_fallback.py backend/apps/email_engine/tests/test_template_loan_type.py
git commit -m "fix(email_engine): strip trailing 'Loan' in _loan_type so subjects never render 'Loan Loan'"
```

---

### Task 2: Slice 1 review — agents + email_engine

**Files:**
- Read: `.tmp/sweep/slice1_files.txt`
- Create: `.tmp/sweep/s1_candidates.json` (your consolidated notes)

- [ ] **Step 1: Dispatch the 7 finders** (parallel, one message) using the Finder prompt template with `{SLICE_FILES}` = contents of `slice1_files.txt`. Slice-specific emphasis to append to every angle block: "High-stakes paths: guarded_api_call budget funnel (reservation/reconcile/breaker), bias reviewer pipeline and its fallbacks, EMAIL_LLM_BACKEND backends (Groq/Ollama/Anthropic) and their error taxonomy, Celery task retry/ack semantics, denial-email content rules (NO apology/sorry/disappointment language may be introduced)."

- [ ] **Step 2: Dedupe** candidates (same defect+location → one), write the survivors with sources to `.tmp/sweep/s1_candidates.json`.

- [ ] **Step 3: Dispatch one verifier per candidate** (parallel batch) using the Verifier template.

- [ ] **Step 4: Record verdicts** in `.tmp/sweep/s1_candidates.json` (add `"verdict"` and later `"disposition"` per entry). REFUTED entries keep their refutation sentence for the ledger.

---

### Task 3: Slice 1 fixes + gate + PR

**Files:**
- Modify: whatever Task 2's CONFIRMED findings name
- Test: `backend/tests/test_delta_sweep_s1.py` for funnel-level regressions; app-local test files for app-local fixes
- Create: `.tmp/pr-body-s1.md`

- [ ] **Step 1:** Apply the Per-finding fix loop to every kept finding, severity order, one commit each.
- [ ] **Step 2:** Run the Slice gate (full backend suite + ruff). Expected: only the 4 known environmental failures, minus any this slice legitimately heals.
- [ ] **Step 3:** Write `.tmp/pr-body-s1.md` with the findings table (every candidate: fixed / issue #N / refuted+why) and the Testing section.
- [ ] **Step 4:** PR + merge gate (push, `gh pr create`, poll `gh pr checks`, AskUserQuestion for the admin merge, merge, `git checkout master; git pull`).

---

### Task 4: Slice 2 — ml_engine (review, fix, PR)

**Files:**
- Read: `.tmp/sweep/slice2_files.txt`
- Create: `.tmp/sweep/s2_candidates.json`, `.tmp/pr-body-s2.md`
- Test: `backend/tests/test_delta_sweep_s2.py` + app-local test files

- [ ] **Step 1:** `git checkout -b review/delta-sweep-s2-ml-engine` from updated master.
- [ ] **Step 2:** Dispatch 7 finders (template + slice-2 emphasis): "This delta is mostly a decomposition 2nd pass: many modules extracted from large files. Focus on the SEAMS: imports that now execute at different times, module-level state split across files, duplicated constants/logic between extracted modules, circular-import near-misses, behavior that silently changed during extraction (default args, exception types, logging). Also: fairness small-group exclusion correctness (PR #222), train self-heal atomic generation (PR #233), feature-importance grouping honesty (PR #232). Do NOT re-litigate moved-but-unchanged code."
- [ ] **Step 3:** Dedupe → verifiers → record verdicts (same as Task 2 steps 2-4).
- [ ] **Step 4:** Per-finding fix loop; slice gate; `.tmp/pr-body-s2.md`; PR + merge gate. ML caution: if a fix touches training/prediction logic, additionally run `docker exec loan-approval-ai-system-backend-1 python -m pytest tests/test_trainer_pipeline.py tests/test_property_based_predictor.py -q` and state in the PR whether model behavior can change (it must not — behavior-changing ML fixes get filed as issues, per guardrail).

---

### Task 5: Slice 3 — frontend (review, fix, PR)

**Files:**
- Read: `.tmp/sweep/slice3_files.txt`
- Create: `.tmp/sweep/s3_candidates.json`, `.tmp/pr-body-s3.md`
- Test: colocated `*.test.tsx`/`*.test.ts` next to fixed components (existing vitest convention)

- [ ] **Step 1:** `git checkout -b review/delta-sweep-s3-frontend` from updated master.
- [ ] **Step 2:** Dispatch 7 finders (template + slice-3 emphasis): "Next.js + shadcn/ui + React Query dashboard. Focus: Model Metrics tabs/charts (#211/#220/#232), application detail tabs (#243), Py↔TS parity helpers (formatPurpose etc. — Grep the matching Python to verify parity holds), polling hooks (2s /tasks/{id}/status), null/undefined guards on API data (null-DI badges), accessibility on new tab/hover components, stale gcTime/debounce regressions vs PR #68."
- [ ] **Step 3:** Dedupe → verifiers → record verdicts.
- [ ] **Step 4:** Per-finding fix loop using vitest (`npx vitest run <file>` in frontend/); gate = full `npx vitest run` + `npm run lint` + backend suite untouched-check (`git diff --name-only master | Select-String backend` → empty); `.tmp/pr-body-s3.md`; PR + merge gate.

---

### Task 6: Slice 4 — cross-cutting tail (review, fix, PR)

**Files:**
- Read: `.tmp/sweep/slice4_files.txt`
- Create: `.tmp/sweep/s4_candidates.json`, `.tmp/pr-body-s4.md`
- Test: `backend/tests/test_delta_sweep_s4.py` + app-local test files

- [ ] **Step 1:** `git checkout -b review/delta-sweep-s4-tail` from updated master.
- [ ] **Step 2:** Dispatch 7 finders (template + slice-4 emphasis): "loans + accounts app deltas (auth, throttles, status transitions), backend/config (settings, env_validation — including the BIAS_REVIEWER_MODEL warning added in #245), .github/workflows (CI jobs: do they still gate what they claim? smoke-e2e #219 changes; the known gap that smoke-e2e never exercises the email-generation branch — propose the smallest CI change that would, or file it), tools/smoke_e2e.sh correctness."
- [ ] **Step 3:** Dedupe → verifiers → record verdicts.
- [ ] **Step 4:** Per-finding fix loop; slice gate; `.tmp/pr-body-s4.md`; PR + merge gate.

---

### Task 7: Closing ledger + memory

**Files:**
- Create: `docs/superpowers/specs/2026-06-10-delta-review-sweep-LEDGER.md`
- Modify: memory `project_*` notes (outside repo)

- [ ] **Step 1: Write the ledger** — one table over all slices: candidate → verdict → disposition (fixed in PR #N / issue #N / refuted: reason). Include the 4 environmental test failures and their clean-tree evidence. End with: "Delta-review baseline is now commit `<final merge sha>`; next sweep reviews `git diff <sha>..master`."
- [ ] **Step 2: Ship the ledger** in a final docs-only PR (`review/delta-sweep-ledger`) through the same PR + merge gate, or fold it into the slice-4 PR if slice 4 is still open.
- [ ] **Step 3: Update memory:** rewrite `project_pr245_sampling_params_review.md`-style note: sweep complete, PR numbers, new baseline sha, issues filed. Update `MEMORY.md` index line.
- [ ] **Step 4: Report** the final summary to the owner: PRs merged, findings counts by disposition, issues filed, new baseline.

---

## Self-review (done at write time)

- **Spec coverage:** scope source (Task 0 manifests), method (shared templates), 4 slices (Tasks 2-6), known template bug (Task 1), guardrails (fix loop step 5, ML caution, email content rules, environmental failures), done-definition (Task 7 ledger + memory). No gaps found.
- **Placeholders:** none — unknown-finding work is encoded as the concrete per-finding loop with exact commands; the one pre-known fix has full code.
- **Consistency:** branch names, manifest paths, and candidate-file names match across tasks; gate commands identical in Tasks 3/4/6 with slice-3 frontend variant spelled out.
