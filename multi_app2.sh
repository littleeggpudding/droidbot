#!/bin/bash

CSV_DIR="droidbot/select_apks"

for csv in "$CSV_DIR"/*.csv; do
    pkg=$(basename "$csv" .csv)  # 提取包名
    echo "============================"
    echo " Processing $pkg"
    echo "============================"
    # Replay new
    python start_bash.py replay_new \
        --csv-file "$csv" \
        --apk-base "$CSV_DIR/$pkg" \
        --max-parallel 8 \
        --run-count 3 \
        --parent-dir "$pkg"
done
