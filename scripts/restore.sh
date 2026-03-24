#!/usr/bin/env bash
set -euo pipefail
# Restore PostgreSQL from backup
# Usage: ./scripts/restore.sh <backup_file>
#
# Environment variables:
#   PGHOST     (default: db)
#   PGPORT     (default: 5432)
#   PGUSER     (default: postgres)
#   PGDATABASE (default: loan_approval)
#
# Safety: this script does NOT drop the database. It restores into the
# existing database. For a clean restore, manually drop/create the DB first.

DB_HOST="${PGHOST:-db}"
DB_PORT="${PGPORT:-5432}"
DB_USER="${PGUSER:-postgres}"
DB_NAME="${PGDATABASE:-loan_approval}"

# ── helpers ───────────────────────────────────────────────────────────
log() { echo "[$(date -Iseconds)] $*"; }

usage() {
  echo "Usage: $0 <backup_file>"
  echo ""
  echo "  backup_file  Path to a .sql.gz backup produced by backup.sh"
  echo ""
  echo "Environment variables:"
  echo "  PGHOST     PostgreSQL host     (default: db)"
  echo "  PGPORT     PostgreSQL port     (default: 5432)"
  echo "  PGUSER     PostgreSQL user     (default: postgres)"
  echo "  PGDATABASE PostgreSQL database (default: loan_approval)"
  exit 1
}

# ── validation ────────────────────────────────────────────────────────
if [ $# -lt 1 ]; then
  usage
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
  log "ERROR: Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

if [[ "${BACKUP_FILE}" != *.sql.gz ]]; then
  log "ERROR: Expected a .sql.gz file, got: ${BACKUP_FILE}"
  exit 1
fi

# ── confirmation ──────────────────────────────────────────────────────
log "WARNING: This will restore ${BACKUP_FILE} into ${DB_NAME}@${DB_HOST}:${DB_PORT}"
log "WARNING: Existing data in tables will be overwritten."

if [ -t 0 ]; then
  read -rp "Continue? [y/N] " confirm
  if [[ "${confirm}" != [yY] ]]; then
    log "Restore cancelled."
    exit 0
  fi
else
  log "Non-interactive mode — proceeding without confirmation"
fi

# ── restore ───────────────────────────────────────────────────────────
log "Restoring from ${BACKUP_FILE} into ${DB_NAME}"

gunzip -c "${BACKUP_FILE}" | psql \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --single-transaction \
  --set ON_ERROR_STOP=1

log "Restore completed successfully"
