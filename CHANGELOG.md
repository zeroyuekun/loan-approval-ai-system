# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-03-24

### Performance
- Reduce XGBoost hyperparameter grid from 240 to 90 candidate fits (3x faster training)

### Fixed
- Marketing email guardrails: whitelist customer profile amounts and FCS $250k disclosure
- Approval email generation: increase max_tokens from 1024 to 4096 (was truncating tool_use JSON)
- Application status not updating to final decision after pipeline completion

## [0.4.0] - 2026-03-24

### Added
- Frontend test suite: Vitest + React Testing Library + MSW (7 test files)
- Backend test suite: 38 test files with 80% coverage enforcement in CI
- Prometheus metrics endpoint with custom ML counters (prediction latency, drift scores)
- Grafana dashboards for loan approval pipeline and ML model performance
- AlertManager rules for prediction latency, error rate, and model drift
- Kubernetes manifests with Kustomize (namespace, deployments, ingress, configmaps)
- Terraform IaC for AWS (VPC, RDS, ElastiCache, ALB, IAM)
- Architecture Decision Records (ADRs) for synthetic data, XGBoost constraints, bias detection, temporal validation
- Model Card documenting training methodology, fairness metrics, and known limitations
- Operations runbook with incident response procedures
- SLA definitions for pipeline latency and availability targets

### Fixed
- Pipeline resilience: added circuit breaker and retry logic for Claude API calls
- Mobile header overlapping navigation elements on small screens
- Email template rendering when profile context is missing
- LightGBM lazy import to avoid crash in environments without native library

## [0.3.0] - 2026-03-20

### Added
- Human review queue for escalated applications (bias flags, guardrail failures, low-confidence predictions)
- Batch orchestration endpoint for processing multiple applications
- Agent workflow timeline component showing step-by-step pipeline progress
- Resume-after-review flow: approved applications continue pipeline from where they paused
- Logo redesign and brand refresh across dashboard

### Fixed
- Orchestrator lock contention when multiple pipelines target the same application
- Timeline component not updating on WebSocket reconnect

## [0.2.0] - 2026-03-20

### Added
- Customer profile page with savings balance, checking balance, loyalty tier display
- Edit Profile functionality with form validation
- Profile link in admin dropdown navigation
- Customer experience flow documentation in README
- Staff view of customer details with banking relationship context

### Fixed
- Profile page layout breaking when optional fields are null
- Navigation not redirecting after profile update
- Missing CSRF token on profile PATCH requests

## [0.1.0] - 2026-03-19

### Added
- ML prediction pipeline: XGBoost with monotonic constraints, Platt calibration, SHAP explanations
- Synthetic data generator using Gaussian copula (calibrated against ABS/APRA/Equifax statistics)
- Claude API email generation for approval and denial decisions
- 10 deterministic guardrail checks (prohibited language, hallucinated numbers, tone, required elements)
- Hybrid bias detection: regex pre-screen + LLM review with escalation thresholds
- Next Best Offer engine with product recommendations for denied applicants
- Marketing email agent with compliance guardrails (Banking Code, NCCP Act, ASIC RG 234)
- Orchestrator pipeline chaining prediction, email, bias, NBO, and marketing steps
- Customer profile system with loyalty tiers and banking relationship tracking
- JWT authentication with role-based access (admin, loan officer, customer)
- Separate Celery queues for ML, email, and agent workloads
- Docker Compose environment with PostgreSQL 17, Redis 7, and hot-reload
- OpenAPI documentation via drf-spectacular at /api/docs/
- GitHub Actions CI: backend tests, lint, security scan, dependency audit, Docker build, GHCR deploy

## [0.0.1] - 2026-03-12

### Added
- Initial project scaffold
- Django 5 + Django REST Framework backend
- Next.js 15 frontend with shadcn/ui component library
- PostgreSQL and Redis service configuration
- Loan application model with CRUD endpoints
- Basic project structure: apps (accounts, loans, ml_engine, email_engine, agents)
