#!/usr/bin/env bash
# Daily SQLite backup with rotation.
# Install:
#   sudo install -m 0755 backup.sh /usr/local/bin/mytoolbox-backup
#   sudo crontab -e
#   0 3 * * * /usr/local/bin/mytoolbox-backup

set -euo pipefail

SRC="/opt/mytoolbox/instance/app.db"
DEST_DIR="/var/backups/mytoolbox"
RETENTION_DAYS=14
TS="$(date +%Y%m%d-%H%M%S)"
DEST="$DEST_DIR/app-$TS.db"

if [[ ! -f "$SRC" ]]; then
    echo "[mytoolbox-backup] source DB not found: $SRC" >&2
    exit 1
fi

mkdir -p "$DEST_DIR"

# Safe online backup via sqlite3 .backup
sqlite3 "$SRC" ".backup '$DEST'"
gzip "$DEST"

# Rotate
find "$DEST_DIR" -name "app-*.db.gz" -mtime +$RETENTION_DAYS -delete

echo "[mytoolbox-backup] wrote $DEST.gz"
