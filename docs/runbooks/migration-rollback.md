# Migration rollback

**Severity:** depends on the migration — critical if it's already partially applied in production.

## Symptoms

- A deploy included a Django migration that caused errors / data corruption / unacceptable slowness
- `python manage.py migrate` failed halfway
- A new column / constraint is making existing queries blow up

## Diagnose

1. **Find the bad migration:**
   ```bash
   docker compose exec backend python manage.py showmigrations --plan | tail -20
   ```

   The latest `[X]` applied entry is where rollback starts.

2. **Check if the migration is reversible:**
   ```bash
   grep -n "migrations.RunPython" backend/apps/*/migrations/<NNNN>*.py
   ```

   `RunPython` without a `reverse_code` function is **irreversible** — you need a forward-only compensating migration, not a rollback.

3. **Check data changes:**
   If the migration ran `RunPython` that modified rows, rolling back the schema won't unmodify the data. You may need a data repair migration.

## Remediate

**For a reversible migration on a single app:**

```bash
docker compose exec backend python manage.py migrate <app_label> <previous_migration_number>
# Example: migrate loans 0023_before_bad_migration
```

**For an irreversible migration:**

1. Author a **forward-only compensating migration** in the same app:
   ```bash
   docker compose exec backend python manage.py makemigrations --empty <app_label>
   ```
2. Fill in the compensating operations (drop column, re-add dropped constraint, restore data from backup).
3. Commit via the normal PR flow — **no emergency bypass**, CI must still pass.
4. Deploy and apply the compensating migration.

**For a migration that corrupted data:**

1. Stop writes to the affected tables if safe (maintenance mode).
2. Restore the affected tables from the most recent Postgres backup:
   ```bash
   # from the db container:
   pg_restore -U postgres -d loan_approval -t <table_name> /backups/latest.dump
   ```
3. Re-author the migration with the corruption fixed.

## Post-mortem

Every rollback gets a post-mortem:
- What did the migration do?
- Why did local / CI testing not catch it?
- What test would catch it next time? (Add it.)
- Do we need pre-deploy migration review for a class of changes (e.g., anything touching `Application` table)?

File the post-mortem under `docs/postmortems/YYYY-MM-DD-<slug>.md`.

## Escalate

- Tag Backend owners immediately if production is affected.
- If data loss is suspected: stop writes, notify stakeholders, do not attempt "quick fixes" against production without a plan.
