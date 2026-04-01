# ADR 005: Django over FastAPI

## Status

Accepted

## Date

2026-04-01

## Context

The loan approval system requires an async task queue (Celery), a relational ORM with migration support, role-based access control, and an admin interface for debugging production data. The two primary Python web framework options are Django 5 + Django REST Framework and FastAPI + SQLAlchemy.

## Decision

Use Django 5 with Django REST Framework for the backend API layer.

### Why Django

- **Celery integration is first-class.** Django's `django-celery-results` and `django-celery-beat` work out of the box. FastAPI requires manual Celery configuration, a separate process manager, and custom result storage — adding operational complexity for the three separate queues (`ml`, `email`, `agents`) this system uses.
- **Built-in admin panel.** During development, the Django admin saved significant debugging time for inspecting `LoanDecision` records, `AgentRun` step logs, and `AuditLog` entries. FastAPI has no equivalent — building a comparable admin UI would have been a project in itself.
- **Mature ORM with migrations.** Django's migration framework handles schema evolution across environments. SQLAlchemy + Alembic is capable but requires more boilerplate and has rougher edges with complex model relationships (e.g., the `LoanApplication` → `LoanDecision` → `AgentRun` chain).
- **DRF serializers provide robust validation.** The `LoanApplicationCreateSerializer` validates profile completeness, field ranges, and business rules in a declarative style. FastAPI's Pydantic models handle type validation well but business rule validation requires more manual wiring.

### Why not FastAPI

- FastAPI's async-native design is advantageous for high-concurrency IO workloads, but the ML prediction path is CPU-bound (XGBoost inference + SHAP computation) and runs in Celery workers regardless. The API layer itself is not the bottleneck.
- FastAPI's dependency injection is elegant but Django's middleware + permission classes achieve the same outcome for auth/RBAC with more ecosystem support (e.g., `djangorestframework-simplejwt`).

## Consequences

### Positive

- Admin panel provides immediate visibility into application state, model versions, and agent runs
- Celery configuration is minimal — standard Django settings, no custom broker wiring
- Large ecosystem of battle-tested packages (django-filter, drf-spectacular, django-cors-headers)

### Negative

- Django is a heavier framework with more implicit behaviour (middleware chains, signal dispatch)
- Async views require careful handling — Django 5 supports async but the ORM is still primarily synchronous
- Slower cold starts compared to FastAPI, mitigated by gunicorn with `--max-requests` recycling
