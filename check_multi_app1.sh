#!/bin/bash

CSV_DIR="droidbot/select_apks"

# for server173
skiped_apps=("com.mkulesh.micromath.plus" "io.github.muntashirakon.AppManager" "com.byagowi.persiancalendar")


for csv in "$CSV_DIR"/*.csv; do
    pkg=$(basename "$csv" .csv)  # 提取包名
    echo "============================"
    echo " Processing $pkg"
    echo "============================"

    if [[ " ${skiped_apps[@]} " =~ " $pkg " ]]; then
        echo "Skipping $pkg because it is in the skiped_apps list"
        continue
    fi

    echo "Checking Replay:"

    # Replay
    ./check_output.sh -t replay -p "$pkg"

    echo "Checking Record:"

    # Record
    ./check_output.sh -t record -p "$pkg"

    # Delete useless record
    ./check_useless_record.sh "$pkg" --delete
done