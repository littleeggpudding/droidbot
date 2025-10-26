#!/bin/bash

CSV_DIR="droidbot/select_apks"

# for server173
skiped_apps=("com.mkulesh.micromath.plus" "io.github.muntashirakon.AppManager" "com.byagowi.persiancalendar" "com.red.alert" "com.amaze.filemanager" "org.secuso.privacyfriendlytodolist" "org.billthefarmer.diary")


for csv in "$CSV_DIR"/*.csv; do
    pkg=$(basename "$csv" .csv)  # 提取包名
    echo "============================"
    echo " Processing $pkg"
    echo "============================"

    if [[ " ${skiped_apps[@]} " =~ " $pkg " ]]; then
        echo "Skipping $pkg because it is in the skiped_apps list"
        continue
    fi
    
    # Replay new
    python start_bash.py replay_new \
        --csv-file "$csv" \
        --apk-base "$CSV_DIR/$pkg" \
        --max-parallel 8 \
        --run-count 3 \
        --parent-dir "$pkg"
done
