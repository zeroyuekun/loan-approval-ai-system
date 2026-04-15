.PHONY: demo dev down build logs logs-backend logs-celery migrate seed seed-demo train test test-auth test-ml lint format health benchmark ablate model-card clean help

# ===== One-shot demo =====
demo:               ## Bring up the full stack with seeded demo data (PR 4 dependency: seed_demo)
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example — edit <REQUIRED> values then re-run 'make demo'." && exit 1; fi
	docker compose up -d db redis
	docker compose run --rm backend python manage.py migrate --noinput
	docker compose run --rm backend python manage.py seed_demo
	docker compose up backend frontend

# ===== Development =====
dev:                ## Start all services in the background
	docker compose up -d

down:               ## Stop all services
	docker compose down

build:              ## Rebuild all containers
	docker compose build

logs:               ## Tail all service logs
	docker compose logs -f

logs-backend:       ## Tail backend logs
	docker compose logs -f backend

logs-celery:        ## Tail Celery worker logs
	docker compose logs -f celery_worker_ml celery_worker_io

# ===== Database / data seeding =====
migrate:            ## Run Django migrations
	docker compose exec backend python manage.py migrate

seed:               ## Generate 10k synthetic applicants and train an XGBoost model
	docker compose exec backend python manage.py generate_data --count 10000
	docker compose exec backend python manage.py train_model --algorithm xgb

seed-demo:          ## Seed the demo dataset (100 applicants + Neville Zeng golden fixture) — PR 4 dependency
	docker compose run --rm backend python manage.py seed_demo

train:              ## Train the active XGBoost model
	docker compose run --rm backend python manage.py train_model

# ===== Testing =====
test:               ## Run backend and frontend test suites (pytest discovers via pytest.ini testpaths)
	docker compose run --rm backend pytest
	cd frontend && npm test -- --run

test-auth:          ## Run auth tests only
	docker compose exec backend pytest tests/test_auth.py -v

test-ml:            ## Run ML tests only
	docker compose exec backend pytest tests/test_predictor.py -v

# ===== Linting / formatting =====
lint:               ## Run ruff on backend and eslint on frontend
	cd backend && ruff check . || true
	cd frontend && npm run lint || true

format:             ## Auto-format backend code
	cd backend && ruff format .

# ===== Experiments + model card (PR 3) =====
benchmark:          ## Run the four-model benchmark and write docs/experiments/benchmark.md
	docker compose run --rm backend python manage.py run_benchmark

ablate:             ## Run the top-K ablation study and write docs/experiments/ablations.md
	docker compose run --rm backend python manage.py run_ablation

model-card:         ## Generate the model card for the active ModelVersion
	docker compose run --rm backend python manage.py generate_model_card --active

# ===== Health / maintenance =====
health:             ## Check service health endpoints
	@curl -s http://localhost:8000/api/v1/health/ | python -m json.tool
	@echo ""
	@curl -s http://localhost:8000/api/v1/health/deep/ | python -m json.tool

clean:              ## Remove containers, volumes, and cached files
	docker compose down -v
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ===== Help =====
help:               ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
