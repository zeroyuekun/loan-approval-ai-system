# Contributing

## Local dev in three commands

```bash
git clone https://github.com/zeroyuekun/loan-approval-ai-system.git
cd loan-approval-ai-system
cp .env.example .env   # edit <REQUIRED> values, then re-run
make demo
```

Open http://localhost:3000. See `make help` for other workflow targets. Default demo login after `make demo` seeds: `admin` / `demo-admin-password` — change this immediately for any non-local deploy.

Prerequisites:
- Docker and Docker Compose
- Node.js 22 (for frontend development outside Docker)
- Python 3.13 (for backend development outside Docker)

## Development rules

- **Tests first.** Every new service method comes with a unit test. Integration/e2e as needed.
- **Small PRs.** If a PR can be split, split it. Target ≤30 minutes of reviewer time.
- **ADRs for decisions.** If you make an architectural choice a future engineer would want to understand, add an ADR — copy `docs/adr/_template.md`, bump the integer, and commit on the same PR.
- **Conventional Commits.** `feat(app): …`, `fix(app): …`, `chore: …`, `docs: …`, `test: …`, `refactor: …`.
- **Pre-commit.** Run `make lint` before pushing; CI runs `ruff check`, `ruff format --check`, ESLint, and Prettier.

## Running tests

```bash
make test              # full backend + frontend suite
make test-auth         # auth tests only
make test-ml           # ML tests only
cd frontend && npm run test:ci     # frontend with coverage
cd frontend && npx playwright test # frontend e2e (requires Docker stack running)
```

Coverage floors enforced in CI: backend 80%, frontend 30%.

## Linting and formatting

```bash
make lint       # Ruff (backend) + ESLint (frontend)
make format     # Auto-format backend with Ruff
```

## Code conventions

- **Service layer pattern.** Views call services, services call external APIs. Keep views thin and put logic in testable service modules under `backend/apps/*/services/`.
- **Separate Celery queues.** `ml` for CPU-heavy work (training, prediction), `email` for IO-bound email generation, `agents` for orchestration and bias detection.
- **Secrets in `.env` only.** Never hardcode credentials or API keys.
- **No apology language in denial emails.** Do not add "sorry", "apologise", or "disappointment" to email prompts or templates. Firm project convention.
- **Model versioning.** `ModelVersion.is_active` controls which model serves predictions; `save()` atomically deactivates other versions.
- **Frontend polling.** Async task results are polled via `/api/v1/tasks/{id}/status/` every 2 seconds.

## Django apps

| App | Purpose |
|-----|---------|
| `accounts` | JWT auth, three roles (admin, officer, customer), profile management |
| `loans` | Loan application CRUD, status management, audit logging |
| `ml_engine` | Data generation, model training, prediction, drift detection |
| `email_engine` | Claude API email generation, 10 deterministic guardrail checks |
| `agents` | Bias detection, next best offer, marketing agent, orchestrator pipeline |

## Issue triage

- **Bugs** → reproduce locally, add a failing test, PR the fix.
- **Features** → brainstorm a spec first (`docs/superpowers/specs/`), then a plan (`docs/superpowers/plans/`), then implement.

## Pull request conventions

1. **Branch naming.** `feat/description`, `fix/description`, `docs/description`, `chore/description`.
2. **Commits.** Descriptive messages with Conventional Commits prefixes.
3. **CI must pass.** Backend tests (80% coverage), frontend tests (30% coverage), Ruff lint, ESLint, TypeScript type check, Bandit SAST scan, dependency audit, Docker build.
4. **One concern per PR.** Keep changes focused and reviewable.

## Security

See `docs/security/threat-model.md`. For responsible disclosure, email the maintainer listed in the repo root or open a GitHub security advisory.

## References

- [`CLAUDE.md`](CLAUDE.md) — AI agent conventions and WAT architecture
- [`backend/docs/RUNBOOK.md`](backend/docs/RUNBOOK.md) — operations runbook and incident response
- [`SECURITY.md`](SECURITY.md) — security policy and responsible disclosure
