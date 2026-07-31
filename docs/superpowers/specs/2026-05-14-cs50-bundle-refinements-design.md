# CS50 Bundle Refinements — Design Spec

**Date:** 2026-05-14
**Status:** Draft — pending user review
**Author:** Neville Zeng (GitHub `zeroyuekun`)
**Topic:** Six polish refinements to the CS50x submission bundle at `C:\Users\Admin\loan-approval-ai-system-cs50` before video recording
**Parent spec:** `docs/superpowers/specs/2026-05-14-cs50-final-project-design.md`
**Parent plan:** `docs/superpowers/plans/2026-05-14-cs50-final-project.md`

---

## Context

The CS50x submission bundle was packaged earlier today via the parent brainstorm → plan → execute flow. Three subsequent commits in the sibling bundle landed framing improvements: structure-first attribution (`44e266f`), humanised voiceover with the external-video reference removed (`1e78f52`), and three transcript-informed memorable beats (`5311551`).

This spec covers a final polish pass before the user records the demo video. Six issues were identified during a fresh-eyes pass over the bundle:

1. The `LICENSE` copyright line still reads `AussieLoanAI` — a placeholder name, not the author.
2. `VIDEO_SCRIPT.md` lacks practical recording-setup guidance (no instructions for Windows screen capture, audio levels, browser-tab preparation).
3. `VIDEO_SCRIPT.md` does not specify how long the title card holds on screen during the 10-second opening.
4. Inline AI-citation headers on eight key entry-point files lead with `Significant portions of this file were implemented with AI assistance`, which is honest but does not mirror the bundle's new lead framing of *"I set up the structure, AI coded over it."*
5. The bundle `README.md` closes the script on a skills summary but has no equivalent skills-demonstrated section that a recruiter or grader skimming the README would see.
6. The bundle `README.md` description section runs ~1089 words; CS50's typical sweet spot is closer to 750. Optional polish.

This is the final scoped pre-record refinement pass. After this, the bundle is ready for the user's manual TODO list (fill edX username, record video, upload unlisted, paste URL, fill CS50 form, `submit50`).

---

## Goals

1. The `LICENSE` copyright matches the bundle's stated author and the VIDEO_SCRIPT.md title-card name.
2. A user who has never recorded a CS50 demo can prepare and start recording from the bundle alone, without external research.
3. The bundle tells a single consistent story — README, AI_USAGE.md, VIDEO_SCRIPT.md, and inline citation headers all lead with structure-first framing.
4. A grader skimming the README catches the project's hireable skills inside ten seconds.
5. The README description reads cleaner on first scan (shorter, denser, no padding).

---

## Non-Goals

- Touching the active loan-approval-ai-system main repo source code (this is a sibling-bundle-only polish pass — except for the spec/plan artifacts themselves which live in `docs/superpowers/`).
- Re-running the parent CS50 plan from scratch.
- Recording the video or filling the edX username placeholder (user-only manual steps).
- Modifying the `submit50` workflow or CS50 form submission process.
- Adding any new technical content to the project (no new features, no new ML models, no new endpoints).
- Touching the uncommitted `frontend/tsconfig.json` change on the current branch (separate scope, carried over from parent spec's Non-Goals).

---

## Approach

Four atomic commits in the sibling bundle (`C:\Users\Admin\loan-approval-ai-system-cs50`), each independently revertable:

- **Commit 1 — `docs(cs50): real author name in LICENSE`** — A1 only. Single-line change.
- **Commit 2 — `docs(cs50): add recording-setup section and title-card duration to VIDEO_SCRIPT`** — B1 + B2 bundled (both touch the same file in adjacent sections).
- **Commit 3 — `chore(cs50): rewrite inline AI citation headers for structure-first consistency`** — C1 across 8 files. Identical-shape rewrite in each.
- **Commit 4 — `docs(cs50): README skills section + tighten description`** — C2 + D1 bundled (same file, same prose pass).

Each commit lands a coherent unit of work, follows the existing CS50 commit-message convention (`docs(cs50): ...`, `chore(cs50): ...`), and can be reverted independently if any specific change turns out wrong without dragging the others with it.

---

## Refinement specifications

### A1 — LICENSE copyright

**File:** `C:\Users\Admin\loan-approval-ai-system-cs50\LICENSE`
**Change:** Replace `Copyright (c) 2026 AussieLoanAI` with `Copyright (c) 2026 Neville Zeng`.
**Acceptance:** Line 3 of the file reads exactly `Copyright (c) 2026 Neville Zeng`. No other changes to the LICENSE.

### B1 — Recording setup section

**File:** `C:\Users\Admin\loan-approval-ai-system-cs50\VIDEO_SCRIPT.md`
**Location:** New section inserted between the existing `## Close — skills + URL (13 s)` section and `## Delivery tips`.
**Content:** A `## Recording setup (do this before you hit record)` section covering:

- **Screen recording on Windows:** Xbox Game Bar via `Win + G` as zero-install default; OBS Studio as the finer-control alternative; resolution recommendation of 1920×1080 minimum with downsample guidance for 4K monitors.
- **Audio check:** target peak level of −12 to −6 dB; external mic (AirPods or USB) beats built-in by a wide margin; quiet-room reminder.
- **Browser tabs to pre-load** (so the user doesn't type URLs on camera): officer dashboard with a blank application, an approved application detail page, a denied application detail page, an `AgentRun` detail page, the model-metrics dashboard.
- **Before you press record:** close Slack/Discord/email to prevent notification toasts; close other apps for thermal headroom; test-record 10s to confirm audio capture.

**Acceptance:** Section appears before `## Delivery tips`. All four sub-headings present. Practical and Windows-specific (this is the user's platform).

### B2 — Title-card duration

**File:** `C:\Users\Admin\loan-approval-ai-system-cs50\VIDEO_SCRIPT.md`
**Location:** Replace the line `Title card on screen:` (immediately after the `## Required opening (10 s)` heading) with explicit duration guidance.
**New line:** `**Title card on screen for the full 10 seconds**, then transition to the officer dashboard for the next beat:`
**Acceptance:** Title-card duration is unambiguous; user knows the card holds the full 10s before any demo footage starts.

### C1 — Inline citation headers rewrite

**Files (8):**
1. `backend/manage.py`
2. `backend/config/settings/base.py`
3. `backend/apps/ml_engine/services/predictor.py`
4. `backend/apps/email_engine/services/email_generator.py`
5. `backend/apps/agents/tasks.py`
6. `frontend/src/app/page.tsx`
7. `frontend/src/app/dashboard/page.tsx`
8. `tools/train_model.py`

**Old text** (replaced everywhere):
```
AI Usage: Significant portions of this file were implemented with AI assistance
(Claude Code by Anthropic). Design, review, and integration by the author.
```

**New text** (replaces above everywhere, with the appropriate comment prefix for each file — `#` for Python, `//` for TypeScript):
```
AI Usage: Initial project structure by the author; feature implementation
built with AI assistance (Claude Code by Anthropic) under author review.
```

The existing third line `Full attribution: AI_USAGE.md at repo root.` is preserved where present and added where missing (current state: present on 6 of 8 files; absent on `manage.py` and `tools/train_model.py`).

**Acceptance:** All 8 files lead with "Initial project structure by the author"; all 8 files reference `AI_USAGE.md` at repo root for full attribution.

### C2 — Skills demonstrated section in README

**File:** `C:\Users\Admin\loan-approval-ai-system-cs50\README.md`
**Location:** New section inserted between `##### AI Usage Acknowledgement` and `##### How to run locally`.
**Content:** A `##### Skills demonstrated` heading followed by 5–6 hireable-engineer bullets mirroring the video script's close:

- Combining classical ML (XGBoost gradient boosting) with modern LLMs (Claude) in a single decision pipeline
- Designing deterministic guardrails around probabilistic LLM outputs (no-apology filter, URL allowlist, HTML escape)
- Orchestrating multi-agent workflows with traceability (prediction → email → bias detection → next-best-offer → human-review)
- Production observability and operations (Prometheus, Grafana, SLO dashboards, k6 load tests, smoke-end-to-end CI)
- Model risk management against real regulatory benchmarks (APRA CPS 230 alignment, fairness gates, drift monitoring)
- Disciplined iteration and adversarial review (~190 atomic PRs, Codex adversarial code review at milestones)

**Acceptance:** Section reads like a recruiter could pull bullets directly into an interview-prep doc. No marketing fluff. Each bullet maps to a concrete artefact in the codebase.

### D1 — Tighten README description

**File:** `C:\Users\Admin\loan-approval-ai-system-cs50\README.md`
**Target:** Reduce from ~1089 words to ~750–850 words.
**Method:** Prose tightening pass on the existing sections — same content, less filler. No section deletions. Specifically:

- Tighten the description paragraph (line 9) — currently runs ~115 words; aim ~75.
- Trim the three-levels descriptions to land each level in 2–3 sentences (currently 4–5).
- Tighten the "Design choices and rationale" bullets — each rationale should be one sentence not two.
- Keep the tech stack list, the "What each major file does" table, and the production-posture section as-is.

**Acceptance:** Final word count between 750 and 850 (verified via `wc -w` or PowerShell equivalent). No section headings removed. All concrete facts preserved. Reads less like a wall on first scan.

---

## Verification

Sibling-bundle-only checks, run before committing each unit:

| Refinement | Verification command / check |
|------------|-------------------------------|
| A1 | `head -3 LICENSE` shows `Copyright (c) 2026 Neville Zeng` |
| B1 | `## Recording setup` section present and contains the four sub-headings; grep for `Win + G`, `OBS`, `1920`, `−6 dB`, `Pre-load` confirms key content |
| B2 | Line under `## Required opening (10 s)` mentions "full 10 seconds" explicitly |
| C1 | `grep -rn "Initial project structure by the author" backend frontend tools \| wc -l` returns 8 |
| C1 | `grep -rn "Significant portions of this file" backend frontend tools` returns 0 |
| C2 | `## Skills demonstrated` heading present in README between AI Usage and How to run locally |
| D1 | `wc -w README.md` returns between 750 and 850 |

---

## Rollback

Each commit is atomic and independently revertable. To roll back a single refinement: `git revert <sha>` in the sibling bundle. To roll back the entire pass: `git reset --hard <sha-before-A1>` (only safe because the sibling bundle has no remote — it is a local-only `submit50` source). The bundle's main repo (`zeroyuekun/loan-approval-ai-system`) is unaffected by any of these commits.

---

## After execution

Once all four commits land:

1. The bundle is ready for the user's manual TODO list (fill edX username, record video, upload unlisted, paste URL, fill CS50 form, `submit50`).
2. The parent memory note `project_cs50_final_project_pr189.md` will get a one-line update referencing the polish-pass commit range.
3. No further AI work is needed on the bundle before submission.

---

## Pre-execution open question (resolved)

**Q:** Which name on the LICENSE — Neville Zeng or Eddie Zeng?
**A:** Neville Zeng — matches user profile, VIDEO_SCRIPT.md title card, github username root. Resolved by the user before this spec was written.
