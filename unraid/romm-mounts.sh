#!/usr/bin/env bash
# ROM Mapper - RomM platform folders as bind mounts (Unraid: Settings > User Scripts).
#
# ROM Mapper's RomM tab writes romm-mounts.tsv (source folder <TAB> RomM platform) into its config
# folder. This script mounts each source folder at <DEST_PATH>/<platform>, so RomM's roms folder only
# holds valid platform folders, named the way RomM expects. Nothing is moved or copied.
#
# Run it "At Startup of Array" (mounts don't survive a reboot) and after you change the RomM mapping.
# RomM only sees mounts made before it starts, so a running RomM is stopped and started again.
# In RomM's compose file, map DEST_PATH as its roms folder: - /path/to/shares/sets/romm:/romm/library/roms
set -euo pipefail

# --- CONFIGURATION ---
MOUNTS_FILE="/path/to/appdata/rom-mapper/romm-mounts.tsv"   # in ROM Mapper's config folder
DEST_PATH="/path/to/shares/sets/romm"                       # RomM's roms folder (a folder of its own)
CONTAINER_NAME="romm"
# ---------------------

DEST_PATH="${DEST_PATH%/}"
case "$DEST_PATH" in
  "" | "/" | /mnt | /mnt/user | /mnt/disk[0-9]* | /mnt/cache | /boot*)
    echo "Error: refusing to use '$DEST_PATH' - pick a folder of its own for RomM's roms." >&2
    exit 1 ;;
esac
if [[ ! -f "$MOUNTS_FILE" ]]; then
  echo "Error: $MOUNTS_FILE not found - open the RomM tab in ROM Mapper once to write it." >&2
  exit 1
fi

# --- stop RomM; start it again at the end, even if something below fails ---
RESTART=0
start_again() {
  if [[ $RESTART -eq 1 ]]; then
    echo "Starting '$CONTAINER_NAME' again..."
    docker start "$CONTAINER_NAME" >/dev/null
  fi
}
trap start_again EXIT
if docker ps -q -f name="^/${CONTAINER_NAME}$" | grep -q .; then
  echo "Stopping '$CONTAINER_NAME'..."
  docker stop "$CONTAINER_NAME" >/dev/null
  RESTART=1
fi

# --- unmount what an earlier run mounted under DEST_PATH (deepest first) ---
mounts_under() {
  # /proc/mounts: field 2 is the mount point (spaces etc. written as \040); exact prefix match
  awk -v d="$DEST_PATH/" 'index($2, d) == 1 {print $2}' /proc/mounts | sort -r
}
while read -r mnt; do
  [[ -z "$mnt" ]] && continue
  path="$(printf '%b' "$mnt")"
  umount "$path" 2>/dev/null || umount -l "$path"
done < <(mounts_under)
if [[ -n "$(mounts_under)" ]]; then
  echo "CRITICAL: mounts are still active under $DEST_PATH - stopping before touching anything." >&2
  exit 1
fi

# --- remove the old (now empty) mount folders; anything else is left alone ---
mkdir -p "$DEST_PATH"
find "$DEST_PATH" -mindepth 1 -maxdepth 1 -type d -empty -delete
leftover="$(find "$DEST_PATH" -mindepth 1 -maxdepth 1 | head -5)"
if [[ -n "$leftover" ]]; then
  echo "Note: these aren't empty mount folders and were left alone:"
  echo "$leftover"
fi

# --- mount each platform ---
count=0
while IFS=$'\t' read -r src slug; do
  [[ -z "$src" || "$src" == \#* ]] && continue
  if [[ ! "$slug" =~ ^[a-z0-9][a-z0-9_.-]*$ ]]; then
    echo "Skipped (not a platform name): '$slug'"; continue
  fi
  if [[ ! -d "$src" ]]; then
    echo "Skipped (folder not found): $src"; continue
  fi
  case "$src/" in "$DEST_PATH/"*) echo "Skipped (inside $DEST_PATH): $src"; continue ;; esac
  dest="$DEST_PATH/$slug"
  if [[ -e "$dest" ]]; then
    echo "Skipped ($dest already exists): $src"; continue
  fi
  mkdir "$dest"
  mount --bind "$src" "$dest"
  count=$((count + 1))
done < <(tr -d '\r' < "$MOUNTS_FILE")

echo "Done: $count platform folders mounted under $DEST_PATH."
