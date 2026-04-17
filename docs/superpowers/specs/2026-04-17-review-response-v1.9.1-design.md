# v1.9.1 Review-Response Design

**Date:** 2026-04-17
**Trigger:** External Claude code review (2026-04-17) rating the v1.9.0 baseline at 9.2/10 and naming four specific items that would move the portfolio to 9.5+. All four items independently validated against 2026 industry best practice (IBM, Qt, GitHub, DEV Community sources — see References).

**Goal:** Land four quality items under a single `v1.9.1` release, each as its own atomic PR with test-driven acceptance.

**Success criterion:** After landing all four, the master branch shows:
- A regression test that prevents reintroducing post-outcome features into the ML training set.
- A CI-enforced backend coverage floor of 75 % (from 60 %) and a frontend coverage floor.
- Zero stale `feat/*` PRs open on the public repo.
- A split GitHub Actions workflow tree with path-based triggers and reusable-workflow shared setup.

---

## Scope

Four items land as separate PRs in dependency order.

| Order | Item | Purpose | Risk |
|---|---|---|---|
| 1 | **A — DataGenerator leak** | Correctness: remove or disclaim post-outcome features in synthetic training data | Low — isolated to `apps/ml_engine/services/data_generator.py` |
| 2 | **C — Stale feat PR triage** | Repo hygiene: merge or close PRs #1, #3, #4, #5 | Medium — each PR needs individual judgement |
| 3 | **B — Coverage 60→75 + frontend floor** | Quality gate: raise the bar CI enforces | Low — additive tests plus one config line |
| 4 | **D — Split `ci.yml`** | Maturity signal: move from 185-line monolith to path-triggered workflows | Medium — must preserve check names and avoid breaking branch protection |

The order is chosen so each step leaves the repo in a strictly better state without blocking the next step.

---

## Item A — DataGenerator post-outcome leak

### Problem

`docs/reviews` and project memory (`project_ml_accuracy_context.md`) both note that `DataGenerator` in `apps/ml_engine/services/data_generator.py` produces columns that encode the outcome (e.g. `default_within_24m`, `repayment_amount_paid_to_date`). If any of those columns appear in the feature matrix passed to training, the model is trained on target-leakage features — a methodology bug that inflates AUC and would not reproduce on real data.

### Approach

Two possible end states, discovered by audit:

**Case 1 — leak confirmed and used.**
Drop the offending features from `FEATURES_FOR_TRAINING` (or equivalent). Retrain to confirm AUC change is in the expected direction (drop, not inflate). Note the new baseline in the engineering journal.

**Case 2 — leak present but not used.**
Do not change the generator. Promote the informal knowledge into code: add a `_POST_OUTCOME_FEATURES: set[str]` constant next to `FEATURES_FOR_TRAINING`. A regression test asserts their intersection is empty.

### Test

`backend/tests/test_data_generator_no_leak.py`:

```python
from apps.ml_engine.services.data_generator import (
    DataGenerator,
    POST_OUTCOME_FEATURES,
)


def test_training_features_exclude_post_outcome_columns():
    """No feature available only AFTER a lending decision may appear in the
    feature matrix used for training. Reintroducing one is a methodology bug.
    """
    training_features = set(DataGenerator.FEATURES_FOR_TRAINING)
    leaked = training_features & POST_OUTCOME_FEATURES
    assert not leaked, (
        f"Post-outcome features leaked into training set: {sorted(leaked)}"
    )
```

### Acceptance

- Audit note in PR body identifies Case 1 vs Case 2.
- Regression test in the new file passes.
- If Case 1: a before/after AUC number recorded in the PR body.
- If Case 2: a docstring on `POST_OUTCOME_FEATURES` explaining each column's lifecycle.

### Files

- Modify: `backend/apps/ml_engine/services/data_generator.py`
- Create: `backend/tests/test_data_generator_no_leak.py`

---

## Item C — Stale feat PR triage

### Problem

Four `feat/*` PRs (#1, #3, #4, #5) are open with no recent activity. Carrying an open-PR backlog signals abandonment to a reviewer and — per GitHub's February 2026 availability report — maintainers are actively being asked to close abandoned PRs.

### Approach

Per-PR decision, in this rough order (subject to diff review):

| PR | Title | Likely call |
|---|---|---|
| #1 | AU lending research, age-maturity gate, soft-pull quote, load-test infra | Oversized; split into sub-PRs or close and cherry-pick. |
| #3 | ACL footer + NCCP Sch 1 comparison rate | Small frontend drop-in; likely mergeable. |
| #4 | benchmark + ablation commands, model card auto-gen | Likely in scope for a future Track C item; mergeable if tests exist. |
| #5 | seed_demo + demo GIF protocol | Scaffolding; close unless `seed_demo` command itself is tested. |

For each PR:

1. `gh pr diff #N` to re-read.
2. `gh pr checkout #N && git fetch origin master && git rebase origin/master`.
3. Run the full test suite locally (or push to re-trigger CI).
4. Decision:
   - **Merge** — squash with a conventional-commit message. Add tests in a follow-up commit on the same branch before merging if missing.
   - **Close** — comment with rationale (respects the user's memory: scrap half-finished scaffolding rather than ship placeholders).

### Test

Standard CI on each merged PR. Closed PRs require a close-comment documenting the reason and any follow-up issue.

### Acceptance

- `gh pr list --state open --author zeroyuekun` returns zero `feat/*` PRs.
- Every close decision is linked to either (a) a follow-up issue or (b) an explicit "scrapped — reason" comment.

### Files

Varies per PR; no repo-level files change from this item other than the merged diffs themselves.

---

## Item B — Coverage gate 60→75 and frontend floor

### Problem

`ci.yml:76` enforces `--cov-fail-under=60`. Industry baseline for production code is 70–80 %; 75 % is the accepted middle ground. Frontend tests run but no coverage floor is enforced — merging untested frontend code is currently invisible to CI.

### Approach

1. Run `cd backend && pytest --cov=apps --cov-report=term-missing` to measure current baseline.
2. Rank uncovered files by `(git log --since=3.months churn count) × (production-path criticality)`. Criticality is one of `{prod, admin, management-cmd, test-util}`; only `prod` and `admin` files weigh into the ranking.
3. Add targeted tests for the top-ranked gaps until total coverage ≥ 75 %.
4. Bump `ci.yml` to `--cov-fail-under=75`.
5. Frontend: read `frontend/vitest.config.ts`, set `coverage.thresholds.lines` / `statements` / `functions` / `branches` to the current measured floor plus 5 % — intended as a ratchet, not a bar jump.

### Test

The CI gate is itself the test. Additional verification:

- **Canary PR** — a throw-away PR that adds a trivial untested function. CI must fail the coverage gate. The PR is then reverted.
- **Pre-merge verification** — every PR from this point forward fails if coverage regresses below 75 % backend or the frontend floor.

### Acceptance

- `grep --cov-fail-under=75 .github/workflows/ci.yml` succeeds.
- Canary PR demonstrably fails CI, then is closed/reverted.
- Frontend `vitest` config includes enforced thresholds.
- Total backend coverage reported on master is ≥ 75 %.

### Files

- Modify: `.github/workflows/ci.yml` (one line, `--cov-fail-under` value)
- Modify: `frontend/vitest.config.ts` (coverage thresholds)
- Create: backend test files for identified gaps (count depends on current baseline)

---

## Item D — Split `ci.yml` into focused workflows

### Problem

A single 185-line `ci.yml` runs every job on every push. Per 2026 GitHub Actions guidance, mature repos split by concern and use path-based triggers plus reusable workflows for shared setup.

### Approach

New workflow layout under `.github/workflows/`:

| File | Jobs | Triggers |
|---|---|---|
| `lint.yml` | backend-lint (ruff), frontend-lint + typecheck | `**/*.py`, `**/*.ts`, `**/*.tsx` |
| `test.yml` | backend-tests (Postgres+Redis services), frontend-tests | `backend/**`, `frontend/**` |
| `security.yml` | bandit, trivy, secret-scan, dependency-audit, ZAP | every push to master + every PR |
| `build.yml` | docker-build | `backend/**`, `frontend/**`, `Dockerfile*`, `docker-compose*` |
| `_setup.yml` | reusable workflow — checkout, setup-python, setup-node, caching | called by the above |

### Key constraints

- **Preserve existing job names verbatim** (`Backend Tests`, `Backend Lint`, `Frontend Tests`, `Frontend Lint & Type Check`, `Security Scan`, `Dependency Audit`, `secret-scan`, `Docker Build`). Any branch protection rules — if present — reference these names exactly.
- **Concurrency groups** — each workflow uses `concurrency: group: ${{ github.workflow }}-${{ github.ref }}` and `cancel-in-progress: true` so a fresh push cancels the stale run.
- **Path filters** are additive, never subtractive of required checks — a PR that touches docs only should still satisfy branch protection if security/lint are required.

### Test

1. **`actionlint`** — validate every new workflow YAML in the PR's first commit.
2. **Docs-only trigger test** — push a commit that only touches `*.md` and confirm `test.yml` and `build.yml` do *not* fire, but `security.yml` does (security is always-on).
3. **Backend-only trigger test** — push a commit under `backend/` and confirm `lint.yml` + `test.yml` + `security.yml` + `build.yml` fire; the frontend job inside `test.yml` short-circuits because no frontend paths changed.
4. **Check-name audit** — after the split PR merges, `gh run list --limit 1 --json conclusion,jobs` on master must show the exact same set of job names as before.

### Acceptance

- `.github/workflows/ci.yml` is deleted (or reduced to a single `workflow_call` dispatcher).
- Each workflow passes `actionlint`.
- All four trigger tests behave as specified.
- Post-merge `gh run list` on master shows the same job-name set as on the pre-split master commit.

### Files

- Create: `.github/workflows/lint.yml`
- Create: `.github/workflows/test.yml`
- Create: `.github/workflows/security.yml`
- Create: `.github/workflows/build.yml`
- Create: `.github/workflows/_setup.yml` (reusable)
- Delete: `.github/workflows/ci.yml`

---

## Cross-cutting

### Commit and merge style

Squash-merge, conventional commit prefix (`fix:`, `test:`, `chore:`, `ci:`), one PR per item. Each merged PR deletes its branch.

### CHANGELOG

After the fourth merge, add a `## 1.9.1 — 2026-04-17` entry naming the four items and linking the source-of-truth external code review that motivated each.

### Memory

Update `project_portfolio_polish_complete.md` or create `project_v1_9_1_review_response.md` on completion, following existing memory structure.

### Final review

One cumulative code review in `docs/reviews/2026-04-17-v1.9.1-review-response.md` after all four items merge, following the same format as `docs/reviews/2026-04-17-p4-final.md`.

### Non-goals

- No new product features (feature work is its own track).
- No re-architecture of the WAT layer boundaries.
- No model retraining beyond what Item A requires.
- No changes to the eight Django apps' public API.

---

## References

- [Qt — Is 70 %, 80 %, 90 %, or 100 % code coverage good enough?](https://www.qt.io/quality-assurance/blog/is-70-80-90-or-100-code-coverage-good-enough)
- [IBM — What is Data Leakage in Machine Learning?](https://www.ibm.com/think/topics/data-leakage-machine-learning)
- [Wikipedia — Leakage (machine learning)](https://en.wikipedia.org/wiki/Leakage_(machine_learning))
- [DEV Community — GitHub Actions in 2026: Monorepo CI/CD Guide](https://dev.to/pockit_tools/github-actions-in-2026-the-complete-guide-to-monorepo-cicd-and-self-hosted-runners-1jop)
- [GitHub Blog — Availability report: February 2026](https://github.blog/news-insights/company-news/github-availability-report-february-2026/)
