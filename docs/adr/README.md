# Architecture Decision Records

This directory holds Architecture Decision Records (ADRs) for the Loan Approval AI System. An ADR captures a significant, intentional decision (what we chose, what we rejected, and why) so future contributors, and future us, can understand the system's shape.

## When to write an ADR

- You're choosing between multiple plausible architectures or libraries
- You're introducing a cross-cutting pattern (error handling, auth, caching)
- You're rejecting a plausible default in favour of something else
- A reviewer asks "why did you do it this way and not X?" and the answer deserves durable writing

Skip ADRs for routine implementation choices, library version bumps, or bug fixes.

## Process

1. Copy `000-template.md` to `NNN-short-slug.md` (NNN = next integer, zero-padded).
2. Fill in the sections. Keep it short; one page is ideal.
3. Status starts as **Proposed**. Open a PR.
4. Once merged, status becomes **Accepted**.
5. If a later ADR supersedes it, mark it **Superseded by NNN-other-adr.md** at the top instead of deleting it.

## Index

This is the only ADR series in the repo. ADRs 001 to 010 moved here from `backend/docs/` and kept their original numbers. ADR 011 was numbered 001 in this directory before the two series were merged.

| ADR | Decision | Date |
|-----|----------|------|
| [001](001-synthetic-data-with-copula.md) | Synthetic data generation with Gaussian copula | 2026-03-23 |
| [002](002-xgboost-with-monotonic-constraints.md) | XGBoost with monotonic constraints | 2026-03-23 |
| [003](003-hybrid-bias-detection.md) | Hybrid bias detection system | 2026-03-23 |
| [004](004-temporal-validation-strategy.md) | Temporal validation strategy | 2026-03-23 |
| [005](005-django-over-fastapi.md) | Django over FastAPI | 2026-04-01 |
| [006](006-template-first-email-with-cost-cap.md) | Template-first email generation with cost cap | 2026-04-01 |
| [007](007-wat-architecture.md) | WAT architecture (Workflows, Agents, Tools) | 2026-04-01 |
| [008](008-security-architecture.md) | Security architecture | 2026-04-01 |
| [009](009-dice-counterfactuals-over-binary-search.md) | DiCE counterfactuals over binary search | 2026-04-16 |
| [010](010-pluggable-email-llm-backend-data-safety.md) | Pluggable email LLM backend (free Groq option) and the data-safety decision | 2026-06-10 |
| [011](011-xgboost-rf-ensemble.md) | XGBoost + Random Forest ensemble for loan scoring | 2026-04-17 |

<!-- Append new ADRs here as they're written. The next number is 012. -->
