#!/usr/bin/env bash
set -euo pipefail
# PostgreSQL backup with rotation
# Usage: ./scripts/backup.sh [backup_dir]
#
# Environment variables:
#   PGHOST     (default: db)
#   PGPORT     (default: 5432)
#   PGUSER     (default: postgres)
#   PGDATABASE (default: loan_approval)

BACKUP_DIR="${1:-/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DAY_OF_WEEK=$(date +%u)

DB_HOST="${PGHOST:-db}"
DB_PORT="${PGPORT:-5432}"
DB_USER="${PGUSER:-postgres}"
DB_NAME="${PGDATABASE:-loan_approval}"

DAILY_DIR="${BACKUP_DIR}/daily"
WEEKLY_DIR="${BACKUP_DIR}/weekly"

KEEP_DAILY=7
KEEP_WEEKLY=4

# ── helpers ───────────────────────────────────────────────────────────
log() { echo "[$(date -Iseconds)] $*"; }

ensure_dir() {
  if [ ! -d "$1" ]; then
    mkdir -p "$1"
    log "Created directory: $1"
  fi
}

# ── main ──────────────────────────────────────────────────────────────
log "Starting PostgreSQL backup for ${DB_NAME}@${DB_HOST}:${DB_PORT}"

ensure_dir "${DAILY_DIR}"
ensure_dir "${WEEKLY_DIR}"

BACKUP_FILE="${DAILY_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

log "Dumping database to ${BACKUP_FILE}"
pg_dump \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --no-owner \
  --no-privileges \
  --format=plain \
  | gzip > "${BACKUP_FILE}"

FILESIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
log "Backup complete: ${BACKUP_FILE} (${FILESIZE})"

# Weekly copy on Sundays (day 7)
if [ "${DAY_OF_WEEK}" -eq 7 ]; then
  WEEKLY_FILE="${WEEKLY_DIR}/${DB_NAME}_weekly_${TIMESTAMP}.sql.gz"
  cp "${BACKUP_FILE}" "${WEEKLY_FILE}"
  log "Weekly backup saved: ${WEEKLY_FILE}"
fi

# ── rotation ──────────────────────────────────────────────────────────
log "Rotating daily backups (keeping ${KEEP_DAILY})"
ls -1t "${DAILY_DIR}"/${DB_NAME}_*.sql.gz 2>/dev/null | tail -n +$((KEEP_DAILY + 1)) | while read -r old; do
  log "Removing old daily backup: ${old}"
  rm -f "${old}"
done

log "Rotating weekly backups (keeping ${KEEP_WEEKLY})"
ls -1t "${WEEKLY_DIR}"/${DB_NAME}_weekly_*.sql.gz 2>/dev/null | tail -n +$((KEEP_WEEKLY + 1)) | while read -r old; do
  log "Removing old weekly backup: ${old}"
  rm -f "${old}"
done

log "Backup and rotation finished successfully"
