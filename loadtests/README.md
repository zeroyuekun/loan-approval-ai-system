# Load Testing — AussieLoanAI

## Setup
```bash
pip install -r loadtests/requirements.txt
```

## Run (targeting local Docker)
```bash
cd loadtests
locust -f locustfile.py --host=http://localhost:8000
```

Then open http://localhost:8089 to configure users and start the test.

## Headless mode (CI-friendly)
```bash
locust -f locustfile.py --host=http://localhost:8000 \
  --headless -u 50 -r 5 --run-time 60s \
  --csv=results/load_test
```

## User profiles
- **HealthCheckUser** (20%): Hits health endpoints
- **BrowsingUser** (50%): Login, list loans, view metrics
- **ApplicantUser** (30%): Register, create application, trigger prediction

## Performance targets
- p95 response time < 2 seconds
- Error rate < 1%
- Throughput > 50 req/s at 50 concurrent users
