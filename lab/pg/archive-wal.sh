#!/bin/sh
# archive_command: compress one WAL segment into the local backup tier; the .part rename makes it appear atomically.
set -eu
dir=/backup/pg/wal
[ -f "$dir/$2.gz" ] && exit 0
gzip -c "$1" > "$dir/$2.gz.part"
chmod 644 "$dir/$2.gz.part"
mv "$dir/$2.gz.part" "$dir/$2.gz"
