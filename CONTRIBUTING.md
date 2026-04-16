# Contributing

## Prerequisites

- Docker and Docker Compose
- Node.js 22 (for frontend development outside Docker)
- Python 3.13 (for backend development outside Docker)

## Quick Start

```bash
git clone <repo-url>
cd loan-approval-ai-system
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

make dev        # Start all services (Docker Compose)
make migrate    # Run database migrations
make seed       # Generate 10K synthetic records + train XGBoost model
```

Frontend: http://localhost:3000 | Backend API: http://localhost:8000 | Grafana: http://localhost:3001

Default login: `admin` / `admin1234`

## One-time setup

After cloning, install pre-commit hooks so they run on every commit:

```bash
pip install pre-commit
pre-commit install
```

Hooks run on staged files before commit. Run manually against everything with `pre-commit run --all-files`.

## Running Tests

```bash
# Backend (pytest, requires 80% coverage)
make test

# Specific test suites
make test-auth
make test-ml

# Frontend unit tests (Vitest, requires 30% coverage)
cd frontend && npm test

# Frontend tests with coverage report
cd frontend && npm run test:ci

# Frontend E2E tests (requires Docker stack running)
cd frontend && npx playwright test
```

## Linting and Formatting

```bash
make lint       # Ruff (backend) + ESLint (frontend)
make format     # Auto-format backend with Ruff
```

## Project Structure

| Django App | Purpose |
|------------|---------|
| `accounts` | JWT auth, three roles (admin, officer, customer), profile management |
| `loans` | Loan application CRUD, status management, audit logging |
| `ml_engine` | Data generation, model training, prediction, drift detection |
| `email_engine` | Claude API email generation, 10 deterministic guardrail checks |
| `agents` | Bias detection, next best offer, marketing agent, orchestrator pipeline |

Other directories:

| Directory | Purpose |
|-----------|---------|
| `frontend/` | Next.js 15 dashboard (shadcn/ui, TanStack Query) |
| `scripts/` | Shell scripts for DB init and seeding |
| `tools/` | Standalone Python scripts (WAT Layer 3) |
| `workflows/` | Markdown SOPs (WAT Layer 1) |
| `monitoring/` | Prometheus and Grafana configuration |

## Code Conventions

- **Service layer pattern:** views call services, services call external APIs. Keep views thin and logic in testable service modules (`backend/apps/*/services/`).
- **Separate Celery queues:** `ml` for CPU-heavy work (training, prediction), `email` for IO-bound email generation, `agents` for IO-bound orchestration and bias detection.
- **Secrets in `.env` only.** Never hardcode credentials or API keys.
- **No apology language in denial emails.** Do not add "sorry", "apologise", or "disappointment" to email prompts or templates. This is a firm project convention.
- **Model versioning:** `ModelVersion.is_active` flag controls which model serves predictions. `save()` atomically deactivates other versions.
- **Frontend polling:** Async task results are polled via `/api/v1/tasks/{id}/status/` every 2 seconds.

## Pull Request Conventions

1. **Branch naming:** `feat/description`, `fix/description`, `docs/description`
2. **Commits:** Descriptive messages. Prefix with `feat:`, `fix:`, `docs:`, `refactor:`, `test:` as appropriate.
3. **CI must pass:** Backend tests (80% coverage), frontend tests (30% coverage), Ruff lint, ESLint, TypeScript type check, Bandit SAST scan, dependency audit, Docker build.
4. **One concern per PR.** Keep changes focused and reviewable.

## References

- [`CLAUDE.md`](CLAUDE.md) — AI agent conventions and WAT architecture
- [`backend/docs/RUNBOOK.md`](backend/docs/RUNBOOK.md) — Operations runbook and incident response
- [`SECURITY.md`](SECURITY.md) — Security policy and responsible disclosure
