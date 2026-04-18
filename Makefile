.PHONY: dev down build test lint seed train logs health clean clean-deep typecheck security verify deadcode

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

# Health
health:                  ## Check service health
	@curl -s http://localhost:8000/api/v1/health/ | python -m json.tool
	@echo ""
	@curl -s http://localhost:8000/api/v1/health/deep/ | python -m json.tool

# Cleanup
clean:                   ## Nuke ephemerals (containers, caches, build output)
	docker compose down -v
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path "*/node_modules/*" -delete 2>/dev/null || true
	rm -rf frontend/.next frontend/coverage frontend/playwright-report frontend/test-results
	rm -rf backend/htmlcov backend/.coverage backend/.pytest_cache
	rm -f frontend/tsconfig.tsbuildinfo
	@echo "Clean complete. Re-run 'make build' then 'make dev' to restart."

clean-deep:              ## clean + remove node_modules + .venv (forces reinstall)
	$(MAKE) clean
	rm -rf frontend/node_modules backend/.venv
	@echo "Deep-clean complete. Expect re-install before next run."

help:                    ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
