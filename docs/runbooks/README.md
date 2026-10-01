# Runbooks

Operational procedures for incidents and known failure modes. Each runbook follows the same structure so it's fast to use under pressure.

## How to use

1. Match symptoms to a runbook title.
2. Follow **Diagnose** to confirm the cause. Don't skip this step: the remediation only works if the diagnosis is right.
3. Follow **Remediate** to restore service.
4. If remediation fails, **Escalate** tells you who to tag and what data to attach.

## Index

- [Operations runbook](operations.md): service architecture, API and health endpoints, monitoring, common incidents, operational commands, rollback, scheduled tasks, escalation and gate enablement. It predates the template below and uses its own layout.
- [Frontend container exits with code 243](frontend-exit-243.md)
- [Celery queue backpressure](celery-backpressure.md)
- [Migration rollback](migration-rollback.md)
- [CI gate and image deployment](ci-deployment.md): the `ci-gate` required check, deploy gating, the `PUBLIC_API_URL` variable

## Adding a runbook

Copy an existing runbook file, replace its content, and add it to the index above. Keep section headings identical (`## Symptoms`, `## Diagnose`, `## Remediate`, `## Escalate`) so readers develop muscle memory.
