/**
 * k6 Load Test — Loan Approval Pipeline
 *
 * Tests the full orchestration pipeline under concurrent load to validate
 * SLA targets defined in the weekly pipeline SLA computation.
 *
 * Prerequisites:
 *   - k6 installed: https://k6.io/docs/getting-started/installation/
 *   - Backend running at BASE_URL with seeded test data
 *   - At least one admin/officer user for authenticated endpoints
 *
 * Run:
 *   k6 run tests/load/pipeline_load_test.js
 *
 * Run with custom options:
 *   k6 run --vus 50 --duration 2m tests/load/pipeline_load_test.js
 *
 * Environment variables:
 *   BASE_URL       - Backend URL (default: http://localhost:8500)
 *   TEST_USERNAME  - Admin username (default: admin)
 *   TEST_PASSWORD  - Admin password (default: admin123)
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// ── Custom metrics ──
const pipelineQueuedRate = new Rate('pipeline_queued_success');
const healthCheckDuration = new Trend('health_check_duration', true);
const loginDuration = new Trend('login_duration', true);
const applicationListDuration = new Trend('application_list_duration', true);
const pipelineTriggerDuration = new Trend('pipeline_trigger_duration', true);

// ── Configuration ──
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8500';
const API = `${BASE_URL}/api/v1`;
const USERNAME = __ENV.TEST_USERNAME || 'admin';
const PASSWORD = __ENV.TEST_PASSWORD || 'admin123';

// ── SLA Targets (from pipeline SLA computation) ──
// These match the thresholds in compute_pipeline_sla task
const SLA = {
  health_p95: 200,           // Health check < 200ms
  login_p95: 1000,           // Login < 1s
  application_list_p95: 500, // List applications < 500ms
  pipeline_trigger_p95: 500, // Queue a pipeline task < 500ms
};

// ── Load profile ──
export const options = {
  scenarios: {
    // Ramp up to simulate realistic traffic patterns
    smoke: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      tags: { test_type: 'smoke' },
    },
    load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 20 },  // Ramp up
        { duration: '1m', target: 20 },   // Sustained load
        { duration: '30s', target: 50 },  // Peak
        { duration: '30s', target: 0 },   // Ramp down
      ],
      startTime: '30s',  // Start after smoke test
      tags: { test_type: 'load' },
    },
  },
  thresholds: {
    // SLA assertions — test fails if these are breached
    'health_check_duration': [`p(95)<${SLA.health_p95}`],
    'login_duration': [`p(95)<${SLA.login_p95}`],
    'application_list_duration': [`p(95)<${SLA.application_list_p95}`],
    'pipeline_trigger_duration': [`p(95)<${SLA.pipeline_trigger_p95}`],
    'pipeline_queued_success': ['rate>0.95'],  // 95% success rate
    'http_req_failed': ['rate<0.05'],          // <5% error rate
  },
};

// ── Helpers ──
function getCSRFToken(jar) {
  const csrfRes = http.get(`${API}/auth/csrf/`, { jar });
  return csrfRes.cookies['csrftoken']
    ? csrfRes.cookies['csrftoken'][0].value
    : '';
}

function login(jar) {
  const csrf = getCSRFToken(jar);
  const res = http.post(
    `${API}/auth/login/`,
    JSON.stringify({ username: USERNAME, password: PASSWORD }),
    {
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf,
      },
      jar,
    }
  );
  loginDuration.add(res.timings.duration);
  return res;
}

// ── Test scenario ──
export default function () {
  const jar = http.cookieJar();
  jar.set(BASE_URL, 'csrftoken', '');

  group('Health check', () => {
    const res = http.get(`${API}/health/ready/`);
    healthCheckDuration.add(res.timings.duration);
    check(res, {
      'health returns 200': (r) => r.status === 200,
      'health status healthy': (r) => {
        try {
          return JSON.parse(r.body).status === 'healthy';
        } catch {
          return false;
        }
      },
    });
  });

  group('Authentication', () => {
    const res = login(jar);
    check(res, {
      'login returns 200': (r) => r.status === 200,
    });
  });

  // Get CSRF token for mutating requests
  const csrf = getCSRFToken(jar);
  const authHeaders = {
    'Content-Type': 'application/json',
    'X-CSRFToken': csrf,
  };

  let applicationId = null;

  group('List applications', () => {
    const res = http.get(`${API}/loans/applications/?page=1`, { jar });
    applicationListDuration.add(res.timings.duration);
    check(res, {
      'applications returns 200': (r) => r.status === 200,
      'applications has results': (r) => {
        try {
          const body = JSON.parse(r.body);
          if (body.results && body.results.length > 0) {
            applicationId = body.results[0].id;
            return true;
          }
          return false;
        } catch {
          return false;
        }
      },
    });
  });

  if (applicationId) {
    group('Trigger pipeline', () => {
      const res = http.post(
        `${API}/agents/orchestrate/${applicationId}/`,
        '{}',
        { headers: authHeaders, jar }
      );
      pipelineTriggerDuration.add(res.timings.duration);
      const queued = check(res, {
        'pipeline returns 202': (r) => r.status === 202,
        'pipeline has task_id': (r) => {
          try {
            return JSON.parse(r.body).task_id !== undefined;
          } catch {
            return false;
          }
        },
      });
      pipelineQueuedRate.add(queued ? 1 : 0);

      // Poll task status (simulates frontend polling)
      if (res.status === 202) {
        try {
          const taskId = JSON.parse(res.body).task_id;
          for (let i = 0; i < 3; i++) {
            sleep(2);
            http.get(`${API}/tasks/${taskId}/status/`, { jar });
          }
        } catch {
          // Task polling is best-effort in load tests
        }
      }
    });
  }

  sleep(1); // Think time between iterations
}

// ── Summary report ──
export function handleSummary(data) {
  const summary = {
    timestamp: new Date().toISOString(),
    sla_targets: SLA,
    results: {
      health_p95: data.metrics.health_check_duration
        ? data.metrics.health_check_duration.values['p(95)']
        : null,
      login_p95: data.metrics.login_duration
        ? data.metrics.login_duration.values['p(95)']
        : null,
      application_list_p95: data.metrics.application_list_duration
        ? data.metrics.application_list_duration.values['p(95)']
        : null,
      pipeline_trigger_p95: data.metrics.pipeline_trigger_duration
        ? data.metrics.pipeline_trigger_duration.values['p(95)']
        : null,
      pipeline_success_rate: data.metrics.pipeline_queued_success
        ? data.metrics.pipeline_queued_success.values.rate
        : null,
      http_error_rate: data.metrics.http_req_failed
        ? data.metrics.http_req_failed.values.rate
        : null,
    },
    total_requests: data.metrics.http_reqs
      ? data.metrics.http_reqs.values.count
      : 0,
    total_duration: data.metrics.iteration_duration
      ? data.metrics.iteration_duration.values.med
      : null,
  };

  return {
    'tests/load/results/summary.json': JSON.stringify(summary, null, 2),
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
  };
}

// k6 built-in text summary
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.2/index.js';
