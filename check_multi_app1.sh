#!/bin/bash

CSV_DIR="droidbot/select_apks"

for csv in "$CSV_DIR"/*.csv; do
    pkg=$(basename "$csv" .csv)  # 提取包名
    echo "============================"
    echo " Processing $pkg"
    echo "============================"

    echo "Checking Replay:"

    # Replay
    ./check_output.sh -t replay -p "$pkg"

    echo "Checking Record:"

    # Record
    ./check_output.sh -t record -p "$pkg"
done