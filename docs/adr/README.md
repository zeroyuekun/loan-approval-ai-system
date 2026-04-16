# Architecture Decision Records

This directory holds Architecture Decision Records (ADRs) for the Loan Approval AI System. An ADR captures a significant, intentional decision — what we chose, what we rejected, and why — so future contributors (and future us) can understand the system's shape.

## When to write an ADR

- You're choosing between multiple plausible architectures or libraries
- You're introducing a cross-cutting pattern (error handling, auth, caching)
- You're rejecting a plausible default in favour of something else
- A reviewer asks "why did you do it this way and not X?" and the answer deserves durable writing

Skip ADRs for routine implementation choices, library version bumps, or bug fixes.

## Process

1. Copy `000-template.md` to `NNN-short-slug.md` (NNN = next integer, zero-padded).
2. Fill in the sections. Keep it short — one page is ideal.
3. Status starts as **Proposed**. Open a PR.
4. Once merged, status becomes **Accepted**.
5. If later superseded, mark **Superseded by NNN-other-adr.md** at the top, don't delete.

## Index

- [001 — XGBoost + Random Forest ensemble](001-xgboost-rf-ensemble.md)

<!-- Append new ADRs here as they're written. -->
