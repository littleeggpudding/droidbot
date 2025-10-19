#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./clean_missing_replays.sh              # dry-run in current dir
#   ./clean_missing_replays.sh /path/to/dir # dry-run in target dir
#   ./clean_missing_replays.sh --delete     # actually delete (prompt)
#   ./clean_missing_replays.sh --delete --yes

print_usage() {
  cat <<'EOF'
Usage: clean_missing_replays.sh [TARGET_DIR] [--delete] [--yes] [--help]

TARGET_DIR   Directory to scan (default: current directory)
--delete     Actually delete the record_output_* dirs (default: dry-run)
--yes        When --delete is passed, skip interactive confirmation
--help       Show this help
EOF
}

TARGET_DIR="."
DO_DELETE=0
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --delete) DO_DELETE=1; shift ;;
    --yes)    ASSUME_YES=1; shift ;;
    --help|-h) print_usage; exit 0 ;;
    -*)
      echo "Unknown option: $1" >&2
      print_usage
      exit 2
      ;;
    *)
      TARGET_DIR="$1"; shift ;;
  esac
done

# ✅ 修正处：去掉了多余的反引号
TARGET_DIR="$(cd "$TARGET_DIR" 2>/dev/null && pwd)"
echo "Scanning directory: $TARGET_DIR"
echo "Mode: $( [[ $DO_DELETE -eq 1 ]] && echo "DELETE" || echo "DRY-RUN")"

# 找 record_output_* 目录（仅一层）
mapfile -d '' RECORD_DIRS < <(find "$TARGET_DIR" -maxdepth 1 -mindepth 1 -type d -name 'record_output_*' -print0)

if [[ ${#RECORD_DIRS[@]} -eq 0 ]]; then
  echo "No record_output_* directories found."
  exit 0
fi

TO_DELETE=()
for d in "${RECORD_DIRS[@]}"; do
  name="$(basename "$d")"
  replay_name="replay_output_${name#record_output_}"
  replay_path="$TARGET_DIR/$replay_name"
  [[ -d "$replay_path" ]] || TO_DELETE+=("$d")
done

if [[ ${#TO_DELETE[@]} -eq 0 ]]; then
  echo "All record_output_* have matching replay_output_*."
  exit 0
fi

echo "Will remove ${#TO_DELETE[@]} record dir(s) without matching replay:"
for d in "${TO_DELETE[@]}"; do
  echo "  - $(basename "$d")"
done

if [[ $DO_DELETE -ne 1 ]]; then
  echo
  echo "Dry-run only. Re-run with --delete to actually remove."
  exit 0
fi

if [[ $ASSUME_YES -ne 1 ]]; then
  echo
  read -r -p "Type 'yes' to DELETE these ${#TO_DELETE[@]} directories: " ans
  [[ "${ans,,}" == "yes" ]] || { echo "Aborted."; exit 0; }
fi

echo
for d in "${TO_DELETE[@]}"; do
  rm -rf -- "$d" && echo "Deleted: $(basename "$d")" || echo "Failed: $(basename "$d")" >&2
done
echo "Done."
