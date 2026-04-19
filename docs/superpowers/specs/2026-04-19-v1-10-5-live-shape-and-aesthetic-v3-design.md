# v1.10.5 — Live Denial Shape Fix + Aesthetic v3

**Status:** Draft (awaiting user review)
**Date:** 2026-04-19
**Author:** Claude (brainstorming session with user delegation — "decide the recommendation for me")
**Scope:** Fix a latent parser bug that silently degraded live denial emails, escalate staff re-run clicks that would otherwise no-op, ship aesthetic v3 polish, land release packaging. Four atomic PRs.
**Supersedes:** none
**Target version:** v1.10.4 → v1.10.5

## 1. Goal

Close the most visible correctness gap in the production email pipeline and land the polish it surfaced, without expanding scope into the HTML-escape parity work that has been deferred since v1.10.3.

Concretely:

1. The Python + TypeScript renderers silently fell back to plaintext rendering on live Claude denial output, because the parsers only recognised the templated fixture shape (plain `Label:` factors and explicit `Free Credit Report:` header). Live Claude produces bullet-form factors and prose-intro credit blocks. Customers receiving real denials therefore saw a degraded visual shape — no factor card, no credit-report card, no green "what you can do" panel. The fix is a two-regex parser upgrade mirrored byte-for-byte across both renderers, anchored by a new `denial_06_live_shape` fixture derived from the actual Claude output captured during debugging.
2. The staff "Re-run AI Pipeline" button silently no-ops when a completed `AgentRun` already exists because the backend short-circuits `POST /orchestrate` with `{status: "already_completed"}` and the frontend hook never checked for it. Escalate to `POST /force-rerun` with a reason string when this happens.
3. Land aesthetic v3 — denial hero loses the orange ⓘ icon ball, the brand header gets a white `$` badge, marketing gets a warm closing paragraph between offers and the CTA, bulleted/numbered list spacing tightens when a list continues and relaxes when it ends, legacy-body ABN/Ph/Website special case is removed because the signature block already renders those lines.
4. Ship packaging (APP_VERSION, CHANGELOG) with the README guardrail-count + container-count corrections and the engineering-journal v1.9.x→v1.10.x sprint retro that were drafted during this WIP.

## 2. Non-negotiable principles

1. **Parser fix must ship as its own PR.** It is a production defect. The aesthetic changes are opinion-dependent polish. A reviewer must be able to revert one without the other; the bug fix must be independently cherry-pickable to a hypothetical support branch.
2. **Python and TypeScript renderers stay byte-identical.** Every change that touches `html_renderer.py` must land simultaneously in `emailHtmlRenderer.ts`, guarded by the existing snapshot parity test. If Python changes alone, CI must fail.
3. **Golden fixtures come from real Claude output, not synthetic reconstruction.** `denial_06_live_shape.txt` is the exact plaintext body that exposed the bug during live testing; the corresponding `.html` snapshot is what the fixed renderer produces against it.
4. **No scope creep into HTML-escape parity.** That work (coordinated snapshot regen for byte-for-byte escape parity + the unsubscribe-URL protocol allowlist) stays queued for v1.10.6. This release ships the regression fix the WIP surfaced, nothing more.
5. **Every deliverable is mergeable in isolation.** If we stop after PR #124 we have already shipped the bug fix and closed the regression.
6. **Atomic PR cadence holds.** Matching v1.10.1 (6 PRs) / v1.10.2 (7) / v1.10.3 (5) / v1.10.4 (5). One logical change per PR, green CI before merge, tagged release at the end.
7. **Pre-flight cleanup BEFORE any commit.** The WIP left four debug PNGs at repo root and three MRM artefacts under `backend/ml_models/<uuid>/` that must not enter git history.

## 3. Scope: 4 Deliverables

Merge order: **#125 (independent) → #124 → #126 (stacked on #124) → #127 (release cut).** #125 is independent of the email work so it can ship first; #126 is intentionally stacked on #124 so the 18-snapshot regen happens against the correct parser output. Per the user's stacked-PR rule: retarget #126 to master before merging #124 with `--delete-branch`.

### PR #124 — `fix(email): parse live Claude denial shape`

**Branch:** `fix/email-live-denial-shape`

**Motivation:** The `extractFactorParagraphs` parser matched only `Label: explanation.` on its own line; live Claude output is `•  Label: explanation.` with a leading bullet. `extractFreeCreditReportBlock` required an explicit `Free Credit Report:` header; live Claude writes a prose intro (`"You are entitled to a free copy of your credit report..."`) immediately followed by two or more bureau bullets. Both parsers returned empty matches on real output, causing the structured denial renderer to fall through to legacy plaintext — no factor card, no credit card, no green "what you can do" panel in production denials.

**Changes:**

- **`backend/apps/email_engine/services/html_renderer.py`:**
  - Add `BUREAU_BULLET_RE = re.compile(r"^[\u2022•]\s*(Equifax|Illion|Experian)\b", re.I)` to the module-level regex block.
  - Extend `_extract_factor_paragraphs` to accept a leading bullet prefix by matching `BULLET_LINE_RE` first and stripping to the inner content before applying `FACTOR_LINE_RE`.
  - Rename `_extract_free_credit_report_block` → `_extract_credit_report_block`. Keep the explicit-header branch. Add a second branch that scans for ≥2 consecutive bureau bullets and walks backward from the first bullet to find the prose-intro line mentioning "credit report", bounded by `SECTION_LABELS`, `CLOSINGS`, or another bullet. Return `(start, last_bureau)`.
  - Update the single caller in `_render_denial_body`.
- **`frontend/src/lib/emailHtmlRenderer.ts`:** byte-identical mirror — same regex, same new helper name, same control flow. The test suite's parity assertion will catch any drift.
- **`backend/tests/fixtures/email_bodies/denial_06_live_shape.txt`:** new — the exact plaintext body captured during live debugging.
- **`backend/tests/fixtures/email_snapshots/denial_06_live_shape.html`:** new — the HTML the fixed renderer produces against `denial_06_live_shape.txt` (rendered with parser fix only, not aesthetic v3).
- **`backend/tests/fixtures/email_snapshots/denial_01_serviceability.html` through `denial_05_policy.html`:** regenerated — the rewritten forward-walk in `_extract_credit_report_block` consumes the prose-intro line that was previously spilling into the legacy body as duplicate bureau URLs. Net change per snapshot is the removal of those duplicate plaintext URLs. Rendered with parser fix only, not aesthetic v3.
- **`frontend/src/__tests__/fixtures/email_bodies/denial_06_live_shape.txt`** and **`frontend/src/__tests__/fixtures/email_snapshots/denial_0{1..6}*.html`:** byte-identical mirrors (frontend test runner reads from its own tree).
- **`backend/tests/test_html_renderer.py`:** add `"denial_06_live_shape"` to `ALL_FIXTURE_STEMS`.
- **`frontend/src/__tests__/lib/emailHtmlRenderer.test.ts`:** add `"denial_06_live_shape"` to the parity-fixture list.
- **Inline comment** in `_extract_credit_report_block` (both py and ts) at the inner-backward-walk `break`-on-blank line, explaining the asymmetry with the outer walk's `continue`-on-blank (the outer walks across paragraph boundaries searching for the "credit report" prose intro; the inner stops at paragraph boundaries to keep the intro bounded to a single paragraph).

**Test gate:**
- `cd backend && pytest tests/test_html_renderer.py -q` green (including the new fixture and the existing 15).
- `cd frontend && npm test -- emailHtmlRenderer` green, parity snapshots match backend byte-for-byte.
- Manual spot check: render `denial_06_live_shape.txt` through `render_html(body, email_type="denial")` and confirm three structured cards are emitted (factor / what-you-can-do / credit-report).

**Non-goals:** aesthetic changes, unrelated parser cleanup, HTML-escape parity.

**Commit message:** `fix(email): parse live Claude denial shape (bullet factors + prose credit block)`

### PR #125 — `fix(frontend): escalate to force-rerun when orchestrate short-circuits`

**Branch:** `fix/frontend-rerun-escalation`

**Motivation:** Staff clicking "Re-run AI Pipeline" on the application detail page expect a fresh `AgentRun`. The backend `POST /agents/orchestrate/` short-circuits with `{status: "already_completed"}` when a completed `AgentRun` already exists, which is correct idempotent behaviour for the *general* case — but the staff re-run path on the dashboard wants the escalation. Without this fix the click is silently swallowed, no error surfaces, and the staff user has no feedback.

**Changes:**

- **`frontend/src/hooks/usePipelineOrchestration.ts`:**
  - Add `useForceRerun` to the import from `@/hooks/useAgentStatus`.
  - Store the mutation alongside `orchestrate` in the hook body.
  - After `await orchestrate.mutateAsync(String(applicationId))`, inspect the returned object. If `result?.status === 'already_completed'`, immediately call `forceRerun.mutateAsync({ loanId: String(applicationId), reason: 'Staff re-run from application detail page' })`. The dashboard is staff-only, so this code path is never reachable by customers.
  - Explanatory comment on the escalation block naming the backend contract.

**Test gate:**
- `cd frontend && npm test -- usePipelineOrchestration` green. Two escalation-branch cases required: (a) positive — `orchestrate` returns `{status: 'already_completed'}`, assert `forceRerun.mutateAsync` is called exactly once with the right payload and `pipelineQueued` becomes true; (b) failure — same short-circuit but `forceRerun.mutateAsync` rejects, assert `pipelineError` surfaces and `pipelineQueued` stays false. The existing hook test already exercises the normal-success and outer-orchestrate-failure happy/error paths.

**Non-goals:** any change to backend orchestrate/force-rerun endpoints, any change to the re-run button's loading UX beyond what the existing hook already handles.

**Commit message:** `fix(frontend): escalate staff re-run to force-rerun when orchestrate short-circuits`

### PR #126 — `style(email): v3 polish (no denial icon, brand badge, marketing closing, list spacing)`

**Branch:** `style/email-aesthetic-v3` (based on `fix/email-live-denial-shape`)

**Motivation:** Five small visual improvements surfaced during the live-denial investigation. None are correctness fixes; all sharpen the Australian Big 4 / neobank aesthetic. Bundled together because they all touch `html_renderer.py` + `emailHtmlRenderer.ts` + all 16 snapshots (the 15 pre-existing fixtures plus `denial_06_live_shape` added by #124), so splitting them guarantees rebase hell and duplicated snapshot regen.

**Changes:**

1. **Denial hero loses the orange ⓘ icon ball.** In `_render_hero`, when `email_type == "denial"` set `icon_html = ""` and adjust the headline margin to `0 0 4px 0`. The coloured caution ball read as error-state; removing it matches CommBank / Westpac decline letters, which lead with a clean text headline only.
2. **Brand header `$` badge.** In `_render_header`, prepend a 24×24 white circular badge containing `$` in `TOKENS["BRAND_PRIMARY"]` before the "AussieLoanAI" wordmark. Both spans get `vertical-align:middle` to cope with Outlook's baseline weirdness.
3. **Marketing closing paragraph.** New `_render_marketing_closing(first_name)` helper emitting a short, low-pressure paragraph between the offer cards and the CTA button. Phrasing deliberately avoids every term in `MARKETING_AI_GIVEAWAY_TERMS` (`"rest assured"`, `"please feel free to"`, `"we wish you"`, etc.). Called once from `_render_marketing_body` right after the offer loop.
4. **Bullet / numbered-list spacing.** In `_render_legacy_body`, add a local `_next_nonblank_matches(idx, pattern, use_raw)` helper that looks ahead for the next non-blank line and tests whether it's another bullet (or numbered item). If yes, bottom margin is `2px` (tight — keeps list items together); if no (list just ended), bottom margin is `12px` (breathes before the next paragraph). Uniform `2px` everywhere previously produced a run-on look when a list butted up against prose.
5. **Legacy body ABN/Ph/Email/Website special case removed.** The loop currently generates `<p style="margin:0;font-size:12px;color:#888;">…</p>` for lines starting with those prefixes. The signature block (`_render_signature`) already renders the same lines with better styling, so the legacy branch is dead code that produced duplicate muted-grey lines in some fixture paths. Also remove the `<div style="height:12px;"></div>` emitted for empty lines inside the legacy body — it stacks awkwardly against the new bullet-end margin.
6. **Frontend parity:** mirror every change byte-for-byte in `emailHtmlRenderer.ts`, including the inline comment on `renderMarketingClosing` pointing at the backend helper.
7. **Test updates:**
   - Rename `test_denial_renders_caution_hero` → `test_denial_hero_omits_orange_info_icon`. Assert the orange info icon entity `&#9432;` is **not** in the output and that the headline `"Update on Your Application"` is.
   - Regenerate all 16 snapshots (approval ×5, denial ×5 pre-existing + `denial_06_live_shape` added by #124, marketing ×5). The aesthetic changes affect every rendered email, so the six denial snapshots that landed with parser-only output in #124 are regenerated here on top with aesthetic v3; the other 10 regenerate for the first time. Backend and frontend fixture copies must be byte-identical.

**Test gate:**
- `cd backend && pytest tests/test_html_renderer.py -q` green (16 snapshots total — 15 pre-existing plus `denial_06_live_shape`).
- `cd frontend && npm test -- emailHtmlRenderer` green with full parity.
- Visual review: open each regenerated snapshot in a browser preview and confirm the five changes are visible; compare against the four WIP debug PNGs (`denial-live-1-current.png` vs `denial-live-2-fixed.png`) to confirm the fix matches the intended design.

**Non-goals:** HTML-escape parity, new email types, content or copy rewrites beyond the marketing closing paragraph.

**Commit message:** `style(email): v3 polish — no denial icon, brand $ badge, marketing closing, tighter list spacing`

### PR #127 — `chore(release): v1.10.5 — APP_VERSION bump + CHANGELOG`

**Branch:** `chore/release-v1.10.5`

**Motivation:** Standard release cut after #124, #125, and #126 all merge. Includes the README accuracy corrections and engineering-journal sprint retro that were drafted during this WIP but should land as a single release-packaging PR, not smuggled into the code PRs.

**Changes:**

- **`backend/config/settings/base.py`:** bump `APP_VERSION` from `"1.10.4"` to `"1.10.5"`.
- **`CHANGELOG.md`:** new `## [1.10.5] — 2026-04-19` entry summarising the three code PRs. Follow the v1.10.4 entry's format: one-line per PR with the commit-message subject and the PR number.
- **`README.md`:**
  - Stack table: `7 containers` → `8 containers`, add `watchdog recovery` after `separate ML and IO Celery workers`.
  - Email-guardrails section: rewrite list of 10 checks to the accurate 17, matching `backend/apps/email_engine/services/guardrails/engine.py`.
  - Testing section: `~1000 tests across 66 files. 60% backend coverage floor` → `~1,125 tests across 84 files. 63% backend coverage floor`, mention the `workflow_dispatch` smoke-e2e job and the high-severity / high-confidence Bandit gate.
  - Monitoring section: add the SLO histogram list (`pipeline_e2e_seconds`, per-algorithm `ml_prediction_latency_seconds`, `bias_review_ttr_seconds`, `email_generation_total`) and cross-reference `docs/slo.md` + the two alert rules `PipelineE2ESLOBurn` + `EmailGenerationErrorBudgetBurn`.
- **`docs/engineering-journal.md`:**
  - Update header: timeline `project start → v1.10.4 SLO instrumentation (2026-04-19)`; current version `v1.10.4`.
  - Append new section `## 13. The v1.9.x → v1.10.x sprint (2026-04-17 → 2026-04-19)` — the retrospective narrative drafted during this WIP.
  - The "what's left" paragraph explicitly names HTML-escape parity + unsubscribe-URL protocol allowlist as the queued v1.10.6 scope.
- **Memory:** append a `project_v1_10_5_live_shape_aesthetic.md` memory entry after the release tag lands. Not part of the PR diff, but tracked as a post-merge action.

**Test gate:**
- `grep -n "APP_VERSION" backend/config/settings/base.py` shows `1.10.5`.
- CHANGELOG parses with the markdown linter the repo uses (if any).
- CI green on the release PR (backend tests, frontend tests, linting, security scans).

**Non-goals:** any code changes; any doc changes unrelated to v1.10.5 scope.

**Commit message:** `chore(release): bump APP_VERSION 1.10.4 → 1.10.5 + CHANGELOG`

## 4. Pre-flight cleanup (BEFORE any commit on any branch)

These are in the current WIP working tree and must be dealt with before cutting PR branches, to prevent debug artefacts leaking into git history:

1. **Delete** the four root-level debug screenshots:
   - `denial-cards-live.png`
   - `denial-credit-card.png`
   - `denial-live-1-current.png`
   - `denial-live-2-fixed.png`
   Add `/*.png` or an explicit `denial-*.png` line to `.gitignore` as a prophylactic. These screenshots served their debugging purpose; if any are worth keeping they belong in `docs/screenshots/` or attached to PR descriptions, not tracked at repo root.
2. **Gitignore** `backend/ml_models/*/mrm.md`. These Model Risk Management artefacts are auto-generated per training run (one per `ModelVersion` UUID) and should not accumulate in the repo.
3. **Verify** `docs/screenshots/01-dashboard.png` through `docs/screenshots/05-emails.png` (currently shown as modified) are the *new* aesthetic. If they're stale / mid-regen, exclude them from #126 and regenerate at release time. They ship with the release PR (#127) if fresh.

Pre-flight is a local cleanup — no PR. Ideally done as a single `chore: cleanup debug artifacts` local commit on `master` before branching, or as the first commit on PR #124's branch with explicit sign-off.

## 5. Rollout

**Hour 0:**
- Pre-flight cleanup on a clean `master`.
- Cut branch `fix/frontend-rerun-escalation` from `master`. Implement PR #125. Push, open PR, wait for green CI, merge with `--delete-branch`.

**Hour 0 + ~30 min:**
- Cut branch `fix/email-live-denial-shape` from updated `master`. Implement PR #124. Push, open PR.

**Hour 0 + ~30 min (parallel):**
- Cut branch `style/email-aesthetic-v3` *from* `fix/email-live-denial-shape` (stacked). Implement PR #126. Push. Open PR with the base set to `fix/email-live-denial-shape`.

**Hour 0 + CI time:**
- Once #124 CI green: **retarget #126's base from `fix/email-live-denial-shape` to `master` via the GitHub API BEFORE merging #124** (per user's stacked-PR rule — otherwise `--delete-branch` on #124's merge auto-closes #126). Merge #124 with `--delete-branch`.
- Rebase `style/email-aesthetic-v3` on the now-merged `master` (should be a no-op because the parser work is already in master). Push. Wait for CI. Merge #126 with `--delete-branch`.

**Hour 0 + ~1 hour:**
- Cut `chore/release-v1.10.5` from fresh `master`. Implement PR #127. Wait for CI. Merge with `--delete-branch`.
- Tag `v1.10.5` locally, push tag: `git tag v1.10.5 && git push origin v1.10.5`.

**Hour 0 + release + a few minutes:**
- Append memory entry.
- Update `MEMORY.md` index.

## 6. Risks

1. **Parser bug-fix changes the five pre-existing denial snapshots (beneficial side-effect, not a regression).** The rename `_extract_free_credit_report_block` → `_extract_credit_report_block` also rewrote the forward-walk of the explicit-header branch: under the old parser, the prose-intro line between the `Free Credit Report:` label and the bureau URLs didn't match the `equifax|experian|illion` substring, so it was left to legacy rendering — producing duplicate plaintext bureau URLs below the structured card. The new parser consumes the entire block, removing those duplicates. Consequence: `denial_01`–`denial_05` snapshots regenerate under PR #124 (parser-only) as well as `denial_06_live_shape`. This is a strict improvement — the old output had duplicate links — but it means PR #124 is NOT a zero-snapshot-diff parser fix. The regen is in PR #124 against parser-only output, then PR #126 regenerates all 16 snapshots again on top with aesthetic v3. Mitigated by the existing `ALL_FIXTURE_STEMS` parity test running on every CI build. The bullet-prefix tolerance in `_extract_factor_paragraphs` IS additive — templated denial fixtures that don't use bullet-form factors still take the original code path unchanged.
2. **Python / TypeScript drift during implementation.** Mitigated by the existing parity test, which byte-compares backend vs frontend fixture output. Explicit cross-file review on #124 and #126 before push.
3. **Snapshot regen on #126 misses one of the 16 fixtures.** Mitigated by the explicit `ALL_FIXTURE_STEMS` list; any missed regen shows up as a diff in the next CI run.
4. **Stacked PR mishap — #124 merge auto-closes #126.** Mitigated by the explicit "retarget #126 to master BEFORE merging #124" step in §5, per the user's stacked-PR rule from memory.
5. **Debug PNGs accidentally committed.** Mitigated by the pre-flight cleanup in §4 and by `git status` review before `git add`.

## 7. Performance

- `_extract_credit_report_block` new branch walks backward from the first bureau bullet to find the prose intro. Worst case is O(n²) if called on a pathological body where every line matches the bullet pattern. Email bodies are bounded at ~50–80 lines (hard ceiling from the `word_count` guardrail ~400 words), so real-world cost is O(80 × 80) = 6400 ops per denial — microseconds. No concern.
- No other algorithmic changes.
- Snapshot test count grows 17 → 18. Test-suite wall-clock impact is negligible (<100ms).

## 8. Rejected alternatives

- **One mega-PR "v1.10.5 email polish."** Rejected. File overlap would be convenient, but it bundles a production bug fix (revert-worthy-on-its-own) with opinion-dependent aesthetic changes. A reviewer can't separate the two; if the aesthetic changes need iteration, the bug fix gets held back. Violates the atomic-PR discipline held since v1.9.1.
- **Ship HTML-escape parity in the same release.** Rejected. The senior review that flagged it (v1.10.3) also noted it required coordinated byte-for-byte snapshot regen + an unsubscribe-URL protocol allowlist — too wide for a "safe" release PR. The WIP does not touch HTML-escape anyway. Keeps v1.10.6 as the natural landing slot.
- **Split aesthetic v3 into five micro-PRs (one per visual change).** Rejected. They all touch the same two files and the same 16 snapshots. Five separate PRs = five snapshot regens = four unnecessary rebases. One bundled "aesthetic v3" PR matches how v1.8.x aesthetic v2 was handled (PRs #69–#74 per memory).
- **Skip PR #125 and just document the staff re-run no-op.** Rejected. It's a real UX bug, small and isolated, and already fixed in WIP — shipping it is cheaper than writing a caveat.

## 9. Out of scope (queued for v1.10.6 or later)

- HTML-escape parity between `emailHtmlRenderer.ts` and `html_renderer.py` (coordinated byte-for-byte snapshot regen across Python + TypeScript).
- Unsubscribe-URL protocol allowlist (bundles with the escape parity work).
- Any new email type, new guardrail, new template, or new Claude prompt.
- Backend orchestrate / force-rerun endpoint changes.
- Celery queue / task changes.
- ML model or training changes.
- Frontend routing / layout / component changes outside `usePipelineOrchestration.ts`.
- Test coverage expansion beyond the new fixture in #124.

## 10. Definition of done

- Four PRs (#124, #125, #126, #127) merged to `master` with green CI.
- Tag `v1.10.5` pushed to origin.
- `backend/config/settings/base.py` `APP_VERSION = "1.10.5"`.
- `CHANGELOG.md` top entry is `[1.10.5] — 2026-04-19`.
- `docs/engineering-journal.md` contains section 13 and header dates reflect v1.10.5.
- `git status` on a clean checkout of `master` is empty (no leftover debug PNGs or MRM artefacts).
- No open PRs on the repo related to this scope.
- Memory entry `project_v1_10_5_live_shape_aesthetic.md` written and indexed in `MEMORY.md`.
