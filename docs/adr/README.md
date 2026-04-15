# Architecture Decision Records

This directory contains short records of architecturally significant decisions made during this project's life. Each record answers: what problem needed a decision, what was decided, what was rejected and why, and what the trade-offs are.

## Index

- [ADR-0001 — WAT framework boundary](0001-wat-framework-boundary.md)
- [ADR-0002 — Shared feature-engineering module](0002-shared-feature-engineering-module.md)
- [ADR-0003 — Optuna over grid search](0003-optuna-over-grid-search.md)
- [ADR-0004 — Celery single orchestrator task](0004-celery-single-orchestrator-task.md)
- [ADR-0005 — ModelVersion A/B routing](0005-modelversion-ab-routing.md)

## Adding a new ADR

1. Copy `_template.md` to `NNNN-<short-slug>.md` (next integer, zero-padded).
2. Fill in context, decision, alternatives, consequences.
3. Commit it on the same PR as the decision it records. An ADR after the fact is worth writing, but an ADR *before* landing the change is worth more.
4. Update this README's Index.

## Format

[MADR](https://adr.github.io/madr/) — lightweight. If a decision doesn't fit the template, that's usually a signal the decision is still ambiguous and the ADR is premature.
