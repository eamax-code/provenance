#!/bin/sh
# Dump the database to a file outside Docker's disk image and keep the newest few.
#
#   BACKUP_DIR=../provenance-backups KEEP=3 scripts/backup_db.sh
#
# PG_CONTAINER set: dump through `docker exec` (local Docker Postgres).
# Otherwise: pg_dump against DATABASE_URL (the +psycopg driver suffix is removed).
# Restore steps: docs/operations.md, "Backups and recovery".
set -eu
BACKUP_DIR="${BACKUP_DIR:-../provenance-backups}"
KEEP="${KEEP:-3}"
PG_USER="${PG_USER:-provenance}"
PG_DB="${PG_DB:-provenance}"
mkdir -p "$BACKUP_DIR"
stamp=$(date -u +%Y-%m-%dT%H%MZ)
out="$BACKUP_DIR/provenance-$stamp.dump"
tmp="$out.partial"
if [ -n "${PG_CONTAINER:-}" ]; then
  docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" -Fc -Z 6 > "$tmp"
else
  pg_dump "$(printf %s "$DATABASE_URL" | sed 's/+psycopg//')" -Fc -Z 6 > "$tmp"
fi
# A dump that pg_restore cannot list is not a backup.
if [ -n "${PG_CONTAINER:-}" ]; then
  docker exec -i "$PG_CONTAINER" pg_restore --list < "$tmp" > /dev/null
else
  pg_restore --list "$tmp" > /dev/null
fi
mv "$tmp" "$out"
echo "backup $out $(du -h "$out" | cut -f1)"
# Keep the newest $KEEP timestamped dumps; older hand-made dumps are left alone.
ls -1t "$BACKUP_DIR"/provenance-20??-??-??T????Z.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f -- "$old" && echo "removed $old"
done
