# AU Lending Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce `docs/research/2026-04-14-au-lending-research.md` and `docs/research/findings.json` covering 9 Australian lenders, for use by downstream ML and code sub-projects.

**Architecture:** Pure research workflow — no code is written. Each lender is scraped via WebSearch (discover URLs) + WebFetch (extract content). Raw findings are captured in a scratch file per lender under `.tmp/research/`, then consolidated into the final markdown report and JSON. Lenders are processed independently and can be parallelised if executed via subagents.

**Tech Stack:** WebSearch, WebFetch, Write, Bash (git). No code dependencies. No Python, no Playwright.

**Spec:** `docs/superpowers/specs/2026-04-14-au-lending-research-design.md`

---

## File Structure

- **Create (scratch, per lender):** `.tmp/research/<lender-slug>.md` — raw extraction notes, not committed
- **Create (deliverable 1):** `docs/research/2026-04-14-au-lending-research.md` — committed
- **Create (deliverable 2):** `docs/research/findings.json` — committed

Scratch files live under `.tmp/` per CLAUDE.md convention (disposable intermediate files).

## Lender Slugs

Used as filenames and JSON keys:
- `cba` (Commonwealth Bank)
- `nab` (NAB)
- `up` (Up)
- `judo` (Judo Bank)
- `alex` (Alex Bank)
- `plenti` (Plenti)
- `wisr` (Wisr)
- `moneyme` (MoneyMe)
- `canstar` (Canstar)

---

## Task 1: Prepare workspace

**Files:**
- Create: `.tmp/research/` (directory)
- Create: `docs/research/` (directory, already created if spec dir existed)

- [ ] **Step 1: Create scratch and output directories**

Run:
```bash
mkdir -p .tmp/research docs/research
```

Expected: no output, both directories exist.

- [ ] **Step 2: Verify `.tmp/` is gitignored**

Run:
```bash
grep -E "^\.tmp/?$" .gitignore || echo "NOT IGNORED"
```

Expected: matches `.tmp/` or `.tmp`. If output is `NOT IGNORED`, append `.tmp/` to `.gitignore` and commit:
```bash
echo ".tmp/" >> .gitignore
git add .gitignore
git commit -m "chore: ensure .tmp/ is gitignored for research scratch files"
```

---

## Task 2–10: Per-lender extraction (one task per lender)

The same procedure runs for each of the 9 lenders. Tasks 2–10 are identical in shape; only the lender name, slug, and search queries differ. A subagent can take one lender per dispatch.

### Task 2: Commonwealth Bank (slug `cba`)

**Files:**
- Create: `.tmp/research/cba.md`

- [ ] **Step 1: Discover URLs via WebSearch**

Run WebSearch with each of these queries and record the top relevant result URLs (product page, eligibility, rates, FAQ):
- `Commonwealth Bank personal loan eligibility requirements site:commbank.com.au`
- `Commonwealth Bank personal loan rates fees site:commbank.com.au`
- `Commonwealth Bank personal loan application documents site:commbank.com.au`
- `Commonwealth Bank credit assessment comprehensive credit reporting`

Expected: 3–6 URLs on `commbank.com.au` plus any useful third-party explainer.

- [ ] **Step 2: Fetch each URL with WebFetch**

For each URL from Step 1, run WebFetch with prompt:
> "Extract: (1) application fields collected, (2) eligibility criteria including minimum income/age/residency/credit, (3) risk signals mentioned (CCR, bank statement analysis, serviceability, DTI), (4) advertised rates and fees including comparison rate, (5) UX patterns around decision time, conditional approval, rate personalisation, disclosure style. Quote exact phrases where possible."

- [ ] **Step 3: Write raw findings to scratch file**

Write `.tmp/research/cba.md` with the schema:
```markdown
# CBA — Raw Findings

## URLs fetched
- <url> — <one-line what it gave us>

## Application fields
- <field> — <source quote or paraphrase>

## Eligibility
- min_income_aud: <value or null>
- min_age: <value or null>
- residency: <value or null>
- credit_notes: <quote>

## Risk signals
- <signal> — <source>

## Rates & fees
- advertised_min_apr: <value or null>
- advertised_max_apr: <value or null>
- comparison_rate_max: <value or null>
- fees: [<list>]

## UX patterns
- <pattern> — <source>

## Gaps
- <what we couldn't extract and why>
```

- [ ] **Step 4: Sanity check**

Confirm the scratch file has at least: 1 URL, 3 application fields, 1 rate value OR an explicit gap note explaining why none was available. If fewer, run one more WebSearch with different phrasing before marking done.

### Task 3: NAB (slug `nab`)

Same procedure as Task 2. Replace search queries with:
- `NAB personal loan eligibility requirements site:nab.com.au`
- `NAB personal loan rates fees site:nab.com.au`
- `NAB personal loan application required documents site:nab.com.au`
- `NAB credit assessment serviceability`

Write findings to `.tmp/research/nab.md` using the same template from Task 2 Step 3.

### Task 4: Up (slug `up`)

Same procedure. Queries:
- `Up Bank personal loan eligibility site:up.com.au`
- `Up Bank personal loan rates fees site:up.com.au`
- `Up Bank loan application process`
- `Up Bank personal loan review 2025`

Write findings to `.tmp/research/up.md`.

### Task 5: Judo Bank (slug `judo`)

Judo focuses on SME lending — note personal loan products may be limited. Queries:
- `Judo Bank personal loan site:judo.bank`
- `Judo Bank home loan eligibility site:judo.bank`
- `Judo Bank credit assessment`
- `Judo Bank loan application requirements`

Write findings to `.tmp/research/judo.md`. If no consumer personal loan product exists, record the scope as SME/home and extract whatever lending application fields are public.

### Task 6: Alex Bank (slug `alex`)

Queries:
- `Alex Bank personal loan eligibility site:alex.bank`
- `Alex Bank personal loan rates site:alex.bank`
- `Alex Bank application process`
- `Alex Bank loan review Australia`

Write findings to `.tmp/research/alex.md`.

### Task 7: Plenti (slug `plenti`)

Queries:
- `Plenti personal loan eligibility site:plenti.com.au`
- `Plenti risk-based pricing rates site:plenti.com.au`
- `Plenti application documents required`
- `Plenti credit grade pricing`

Write findings to `.tmp/research/plenti.md`.

### Task 8: Wisr (slug `wisr`)

Queries:
- `Wisr personal loan eligibility site:wisr.com.au`
- `Wisr comprehensive credit reporting site:wisr.com.au`
- `Wisr rates fees site:wisr.com.au`
- `Wisr application documents required`

Write findings to `.tmp/research/wisr.md`.

### Task 9: MoneyMe (slug `moneyme`)

Queries:
- `MoneyMe personal loan eligibility site:moneyme.com.au`
- `MoneyMe instant decision loan site:moneyme.com.au`
- `MoneyMe rates fees site:moneyme.com.au`
- `MoneyMe application process documents`

Write findings to `.tmp/research/moneyme.md`.

### Task 10: Canstar (slug `canstar`)

Canstar is a comparison site — extraction focus shifts to **cross-lender criteria** and rate tables, not single-lender details.

Queries:
- `Canstar personal loan comparison rates site:canstar.com.au`
- `Canstar personal loan eligibility criteria guide site:canstar.com.au`
- `Canstar how personal loans are assessed site:canstar.com.au`
- `Canstar comprehensive credit reporting explainer`

Write findings to `.tmp/research/canstar.md` with emphasis on:
- Cross-lender common eligibility criteria
- Rate ranges across the market
- Fee structures commonly seen
- General decisioning narrative Canstar publishes

---

## Task 11: Consolidate findings

**Files:**
- Create: `docs/research/2026-04-14-au-lending-research.md`
- Create: `docs/research/findings.json`

- [ ] **Step 1: Read all scratch files**

Read every `.tmp/research/*.md` file into working context.

- [ ] **Step 2: Compute consolidated insights**

Identify:
- Application fields present in ≥5 of the 8 non-comparison lenders → `common_application_fields`
- Risk signals present in ≥5 of the 8 non-comparison lenders → `common_risk_signals`
- Application fields or risk signals present in ≥3 lenders but **not present in our current synthetic data** → `gaps_in_our_model`
- UX/copy patterns worth adopting → `ux_recommendations`

For the "gaps" step, inspect our current synthetic data generator. Find it with:
```bash
grep -rn "def generate" backend/apps/ml_engine/ | head -20
```
Then read the file(s) to confirm which fields exist today.

- [ ] **Step 3: Write the markdown report**

Write `docs/research/2026-04-14-au-lending-research.md` with this structure:

```markdown
# Australian Lending Platform Research

**Date:** 2026-04-14
**Sources:** 9 Australian lenders (see spec for rationale)
**Feeds:** sub-project B (ML), sub-project C (code/UX)

## Executive Summary

<~300 words: what we found, what's worth acting on, what the biggest gaps in our current system are>

## Per-Lender Findings

### Commonwealth Bank
**URLs fetched:** <list>
**Application fields:** <list>
**Eligibility:** min_income_aud=<v>, min_age=<v>, residency=<v>, credit_notes=<v>
**Risk signals:** <list>
**Rates & fees:** advertised range <min>–<max>% APR, comparison rate max <v>%, fees=<list>
**UX patterns:** <list>
**Gaps:** <list>

### NAB
<same structure>

### Up
<same>

### Judo Bank
<same>

### Alex Bank
<same>

### Plenti
<same>

### Wisr
<same>

### MoneyMe
<same>

### Canstar (comparison)
<same, with cross-lender emphasis>

## Consolidated Findings

### Common application fields (≥5 lenders)
- <field> — <lender count>

### Common risk signals (≥5 lenders)
- <signal> — <lender count>

### Gaps in our current synthetic data
- <field or signal> — present in <N> lenders, absent from our generator

### UX / copy patterns worth adopting
- <pattern> — seen at <lenders>

## Recommendations

Every recommendation is tagged for downstream pickup.

- [→ B] <recommendation affecting ML / synthetic data>
- [→ C] <recommendation affecting code, UX, or email copy>
...
```

- [ ] **Step 4: Write the JSON file**

Write `docs/research/findings.json` exactly matching the schema in the spec. Every lender object must contain all keys from the schema — use `null` or `[]` for missing values, never omit keys. Validate structure before saving:
```bash
python -c "import json; json.load(open('docs/research/findings.json'))" && echo "valid JSON"
```

Expected: `valid JSON`. If it fails, fix the file and re-run.

- [ ] **Step 5: Verify success criteria from spec**

Check each of these:
1. All 9 lenders appear in both files.
2. Every lender section has a `Gaps` subsection (even if empty list, explicitly note).
3. `gaps_in_our_model` contains at least 5 entries.
4. Every item in the `Recommendations` section of the markdown is tagged `[→ B]` or `[→ C]`.
5. `findings.json` parses as JSON.

If any criterion fails, fix and re-verify before committing.

- [ ] **Step 6: Commit deliverables**

```bash
git add docs/research/2026-04-14-au-lending-research.md docs/research/findings.json
git commit -m "$(cat <<'EOF'
docs(research): add AU lending platform research (sub-project A)

9 Australian lenders scraped for application fields, eligibility
criteria, risk signals, rates, and UX patterns. Consolidated findings
identify gaps vs. our current synthetic data and recommendations
tagged [→ B] (ML) or [→ C] (code/UX) for downstream sub-projects.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds, `git status` clean (aside from untracked `.tmp/`).

---

## Done criteria

- `docs/research/2026-04-14-au-lending-research.md` committed, covering all 9 lenders with consolidated findings and tagged recommendations.
- `docs/research/findings.json` committed, schema-valid, all 9 lenders present.
- Scratch files under `.tmp/research/` preserved locally for traceability but not committed.
- Sub-project A complete. Hand off to sub-project B (ML / synthetic data) brainstorm.
