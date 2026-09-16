#!/usr/bin/env bash
set -euo pipefail

# --- CONFIGURATION (override via environment variables) ---
INPUT_CSV="${INPUT_CSV:-/config/Rom_Mapping.csv}"
SRC_BASE="${SRC_BASE:-/path/to/roms}"
DEST_PATH="${DEST_PATH:-/path/to/mapping}"
# -----------------------------------------------------------

if [[ ! -f "$INPUT_CSV" ]]; then
  echo "Error: Config file not found at $INPUT_CSV"
  exit 1
fi

if [[ ! -d "$SRC_BASE" ]]; then
  echo "Error: ROM source directory not found at $SRC_BASE (is the volume mounted?)"
  exit 1
fi

# Guard against wiping something important if DEST_PATH is misconfigured
case "$DEST_PATH" in
  ""|"/"|"/mnt"|"/mnt/user"|"$SRC_BASE"|"$SRC_BASE"/*)
    echo "Error: Refusing to use DEST_PATH='$DEST_PATH'"
    exit 1
    ;;
esac

# Strip carriage returns and a UTF-8 BOM (Excel likes to add both)
clean() { sed -e 's/\r$//' -e '1s/^\xEF\xBB\xBF//' "$INPUT_CSV"; }

# 1. Read header and grab mapping platforms
IFS=',' read -r -a headers < <(clean | head -n1)
mapping_names=("${headers[@]:1}")

# Load the CSV-based media toggles and locations into associative arrays
declare -A LOCAL_MEDIA_FLAGS
declare -A LOCAL_MEDIA_LOCATIONS

# Parse Media Toggle row
TOGGLE_LINE=$(clean | grep "^Media Toggle," || echo "")
if [[ -n "$TOGGLE_LINE" ]]; then
  IFS=',' read -r -a toggle_fields <<< "$TOGGLE_LINE"
  for idx in "${!mapping_names[@]}"; do
    map_name="${headers[$((idx+1))]}"
    LOCAL_MEDIA_FLAGS["$map_name"]="${toggle_fields[$((idx+1))]:-0}"
  done
fi

# Parse Media Location row
LOCATION_LINE=$(clean | grep "^Media Location," || echo "")
if [[ -n "$LOCATION_LINE" ]]; then
  IFS=',' read -r -a location_fields <<< "$LOCATION_LINE"
  for idx in "${!mapping_names[@]}"; do
    map_name="${headers[$((idx+1))]}"
    LOCAL_MEDIA_LOCATIONS["$map_name"]="${location_fields[$((idx+1))]:-}"
  done
fi

# --- CLEANUP SECTION ---
# Completely removes all contents inside the mapping directory
echo "Cleaning up all existing mappings in $DEST_PATH..."
if [[ -d "$DEST_PATH" ]]; then
  rm -rf "${DEST_PATH:?}"/*
else
  mkdir -p "$DEST_PATH"
fi

# 2. Process each system line
clean | tail -n +2 | while IFS=',' read -r -a fields; do
  folder="${fields[0]:-}"

  # Skip empty lines or configuration rows
  [[ -z "${folder//[[:space:]]/}" ]] && continue
  [[ "$folder" == "Media Toggle" ]] && continue
  [[ "$folder" == "Media Location" ]] && continue

  for idx in "${!mapping_names[@]}"; do
    map_name="${headers[$((idx+1))]}"
    map_val="${fields[$((idx+1))]:-}"
    map_val="${map_val#"${map_val%%[![:space:]]*}"}"
    map_val="${map_val%"${map_val##*[![:space:]]}"}"

    [[ -z "$map_val" ]] && continue

    # Define ROM Paths
    rom_src="$SRC_BASE/$folder"
    rom_dest="$DEST_PATH/$map_name/$map_val"

    # CREATE ROM SYMLINK
    if [[ -d "$rom_src" ]]; then
      mkdir -p "$(dirname "$rom_dest")"
      [[ ! -e "$rom_dest" ]] && ln -s "$rom_src" "$rom_dest"
    fi

    # --- IN-FOLDER MEDIA SYMLINK PROCESS ---
    media_toggle="${LOCAL_MEDIA_FLAGS[$map_name]:-0}"

    if [[ "$media_toggle" == "1" ]]; then
      local_media_src="$rom_src/media"

      if [[ -d "$local_media_src" ]]; then
        local_media_dest_sub="${LOCAL_MEDIA_LOCATIONS[$map_name]:-MEDIA_FULL}"
        media_rel_path="${map_val#*/}"
        local_media_dest="$DEST_PATH/$map_name/$local_media_dest_sub/$media_rel_path/media"

        mkdir -p "$(dirname "$local_media_dest")"
        [[ ! -e "$local_media_dest" ]] && ln -s "$local_media_src" "$local_media_dest"
      fi
    fi
  done
done

echo "Done! Structure rebuilt successfully from CSV."
