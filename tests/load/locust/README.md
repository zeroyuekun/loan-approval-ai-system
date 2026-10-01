# Load testing for AussieLoanAI

## Setup
```bash
pip install -r tests/load/locust/requirements.txt
```

## Run (targeting local Docker)
```bash
cd tests/load/locust
locust -f locustfile.py --host=http://localhost:8000
```

Then open http://localhost:8089 to configure users and start the test.

## Headless mode (CI-friendly)
```bash
locust -f locustfile.py --host=http://localhost:8000 \
  --headless -u 50 -r 5 --run-time 60s \
  --csv=../results/locust
```

## User profiles
- **HealthCheckUser** (20%): hits the health endpoints
- **BrowsingUser** (50%): logs in, lists loans, views metrics
- **ApplicantUser** (30%): registers, creates an application, triggers a prediction

## Performance targets
- p95 response time < 2 seconds
- Error rate < 1%
- Throughput > 50 req/s at 50 concurrent users
