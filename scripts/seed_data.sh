#!/usr/bin/env bash
set -euo pipefail

echo "Generating seed data..."
python manage.py generate_data

echo "Training ML model..."
python manage.py train_model

echo "Seed data and model training complete."
