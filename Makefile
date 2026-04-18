.PHONY: dev down build test lint seed train logs health clean clean-soft clean-deep typecheck security verify deadcode

# Development
dev:                     ## Start all services
	docker compose up -d

down:                    ## Stop all services
	docker compose down

build:                   ## Rebuild all containers
	docker compose build

logs:                    ## Tail all logs
	docker compose logs -f

logs-backend:            ## Tail backend logs
	docker compose logs -f backend

logs-celery:             ## Tail Celery worker logs
	docker compose logs -f celery_worker_ml celery_worker_io

# Database
migrate:                 ## Run Django migrations
	docker compose exec backend python manage.py migrate

seed:                    ## Generate synthetic data and train model
	docker compose exec backend python manage.py generate_data --count 10000
	docker compose exec backend python manage.py train_model --algorithm xgb

shell:                   ## Open Django shell
	docker compose exec backend python manage.py shell

dbshell:                 ## Open PostgreSQL shell
	docker compose exec db psql -U postgres -d loan_approval

# Testing
test:                    ## Run all backend tests
	docker compose exec backend pytest tests/ -v --tb=short

test-auth:               ## Run auth tests only
	docker compose exec backend pytest tests/test_auth.py -v

test-ml:                 ## Run ML tests only
	docker compose exec backend pytest tests/test_predictor.py -v

# Linting
lint:                    ## Lint backend and frontend
	cd backend && ruff check . || true
	cd frontend && npm run lint || true

format:                  ## Auto-format backend code
	cd backend && ruff format .

deadcode:                ## Report unused code (ruff F401/F811/F841 + vulture)
	cd backend && ruff check --select F401,F811,F841 apps config tests || true
	cd backend && vulture apps --min-confidence 80 \
		--ignore-names "_*,test_*,setUp,tearDown,Meta,sender,view,frame,expression,connection,signum,instance,kwargs" \
		--exclude "*/migrations/*,*/tests/*"

typecheck:               ## Type-check backend (mypy) + frontend (tsc --noEmit)
	docker compose exec backend mypy --config-file mypy.ini \
		apps/ml_engine/services/feature_prep.py \
		apps/ml_engine/services/prediction_cache.py \
		apps/ml_engine/services/policy_overlay.py \
		apps/ml_engine/services/policy_recompute.py \
		apps/ml_engine/services/prediction_diagnostics.py \
		apps/ml_engine/services/prediction_explanations.py \
		apps/ml_engine/services/prediction_features.py \
		apps/ml_engine/services/shadow_scoring.py \
		apps/ml_engine/services/shap_attribution.py \
		apps/ml_engine/services/decision_assembly.py
	cd frontend && npm run typecheck

security:                ## Security scans (bandit + pip-audit + npm audit)
	docker compose exec backend bandit -r apps/ config/ -lll
	docker compose exec backend pip-audit --strict --requirement /app/requirements.txt
	cd frontend && npm audit --audit-level=high --omit=dev

verify:                  ## Full verification gate: lint + typecheck + security + tests
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) security
	docker compose exec backend pytest -x --tb=short
	cd frontend && npm test -- --run

# Health
health:                  ## Check service health
	@curl -s http://localhost:8000/api/v1/health/ | python -m json.tool
	@echo ""
	@curl -s http://localhost:8000/api/v1/health/deep/ | python -m json.tool

# Cleanup
clean-soft:              ## Clear caches + build output; KEEPS docker volumes (DB, redis, etc.)
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path "*/node_modules/*" -delete 2>/dev/null || true
	rm -rf frontend/.next frontend/coverage frontend/playwright-report frontend/test-results
	rm -rf backend/htmlcov backend/.coverage backend/.pytest_cache
	rm -f frontend/tsconfig.tsbuildinfo
	@echo "Soft-clean complete. Docker volumes preserved (postgres/redis data intact)."

clean:                   ## FULL wipe: containers + volumes + caches. Use clean-soft day-to-day.
	docker compose down -v
	$(MAKE) clean-soft
	@echo "Full clean complete. Re-run 'make build' then 'make dev' to restart. DB was wiped."

clean-deep:              ## clean + remove node_modules + .venv (forces reinstall)
	$(MAKE) clean
	rm -rf frontend/node_modules backend/.venv
	@echo "Deep-clean complete. Expect re-install before next run."

help:                    ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
