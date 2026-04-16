# Runbooks

Operational procedures for incidents and known failure modes. Each runbook follows the same structure so it's fast to use under pressure.

## How to use

1. Match symptoms to a runbook title.
2. Follow **Diagnose** to confirm the cause — don't skip this, the remediation only works if the diagnosis is right.
3. Follow **Remediate** to restore service.
4. If remediation fails, **Escalate** tells you who to tag and what data to attach.

## Index

- [Frontend container exits with code 243](frontend-exit-243.md)
- [Celery queue backpressure](celery-backpressure.md)
- [Migration rollback](migration-rollback.md)

## Adding a runbook

Copy an existing runbook file, replace content, and add to the index above. Keep section headings identical (`## Symptoms`, `## Diagnose`, `## Remediate`, `## Escalate`) so readers develop muscle memory.
