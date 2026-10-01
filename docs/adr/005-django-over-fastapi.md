# ADR 005: Django over FastAPI

## Status

Accepted

## Date

2026-04-01

## Context

The system needs an async task queue (Celery), a relational ORM with migration support, role-based access control, and an admin interface for debugging production data. The two main Python web framework options are Django 5 + Django REST Framework and FastAPI + SQLAlchemy.

## Decision

Use Django 5 with Django REST Framework for the backend API layer.

### Why Django

- **Celery integration is first-class.** Django's `django-celery-results` and `django-celery-beat` work out of the box. FastAPI needs manual Celery configuration, a separate process manager, and custom result storage, which adds operational complexity across the three separate queues (`ml`, `email`, `agents`) this system uses.
- **The admin panel is built in.** During development, the Django admin saved a lot of debugging time when inspecting `LoanDecision` records, `AgentRun` step logs, and `AuditLog` entries. FastAPI has no equivalent, and building a comparable admin UI would have been a project in itself.
- **The ORM is mature and has migrations.** Django's migration framework handles schema evolution across environments. SQLAlchemy + Alembic can do the job but needs more boilerplate and has rougher edges with complex model relationships, such as the `LoanApplication` → `LoanDecision` → `AgentRun` chain.
- **DRF serializers handle validation, business rules included.** The `LoanApplicationCreateSerializer` validates profile completeness, field ranges, and business rules in a declarative style. FastAPI's Pydantic models handle type validation well, but business rule validation needs more manual wiring.

I'd also used Django on a previous project, so the learning curve was lower. I could focus on the ML pipeline and agent orchestration instead of learning a new framework at the same time.

### Why not FastAPI

FastAPI's async-native design helps with high-concurrency IO workloads. Here, though, the ML prediction path is CPU-bound (XGBoost inference + SHAP computation) and runs in Celery workers either way. The API layer itself is not the bottleneck.

## Consequences

### Positive

- The admin panel gives immediate visibility into application state, model versions, and agent runs.
- Celery configuration is minimal: standard Django settings, no custom broker wiring.
- There is a large ecosystem of well-tested packages (django-filter, drf-spectacular, django-cors-headers).

### Negative

- Django is a heavier framework with more implicit behaviour (middleware chains, signal dispatch).
- Async views need careful handling. Django 5 supports async, but the ORM is still mostly synchronous.
- Cold starts are slower than FastAPI's, mitigated by gunicorn with `--max-requests` recycling.
