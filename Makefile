.PHONY: demo test lint seed train benchmark ablate model-card clean help

demo:       ## Bring up the full stack with seeded demo data
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example — edit <REQUIRED> values then re-run 'make demo'." && exit 1; fi
	docker compose up -d db redis
	docker compose run --rm backend python manage.py migrate --noinput
	docker compose run --rm backend python manage.py seed_demo
	docker compose up backend frontend

test:       ## Run full backend and frontend test suites
	docker compose run --rm backend pytest
	cd frontend && npm test -- --run

lint:       ## Run ruff on backend and eslint on frontend
	docker compose run --rm backend ruff check .
	cd frontend && npm run lint

seed:       ## Seed the demo dataset (100 applicants + Neville Zeng golden fixture)
	docker compose run --rm backend python manage.py seed_demo

train:      ## Train the active XGBoost model
	docker compose run --rm backend python manage.py train_model

benchmark:  ## Run the four-model benchmark and write docs/experiments/benchmark.md
	docker compose run --rm backend python manage.py run_benchmark

ablate:     ## Run the top-10 ablation study and write docs/experiments/ablations.md
	docker compose run --rm backend python manage.py run_ablation

model-card: ## Generate the model card for the active ModelVersion
	docker compose run --rm backend python manage.py generate_model_card --active

clean:      ## Tear down containers and remove volumes
	docker compose down -v

help:       ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
