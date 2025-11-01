#!/bin/bash

CSV_DIR="droidbot/select_apks"

# for server173
# for server173
skiped_apps=(
    "com.mkulesh.micromath.plus"
    "io.github.muntashirakon.AppManager"
    "com.byagowi.persiancalendar"
    "com.red.alert"
    "com.amaze.filemanager"
    "org.secuso.privacyfriendlytodolist"
    "org.billthefarmer.diary"
    "com.vrem.wifianalyzer"
    "org.zephyrsoft.trackworktime"
    "com.atul.musicplayer"
    "com.michaldrabik.showly2"
    "com.mxt.anitrend"
    "com.best.deskclock"
    "it.feio.android.omninotes"
    "net.gsantner.markor"
    "xyz.zedler.patrick.tack"
    "com.ichi2.anki"
    "com.mirfatif.permissionmanagerx"
    "org.isoron.uhabits"
    "org.billthefarmer.editor"
    "com.jlindemann.science"
    "org.secuso.privacyfriendlynotes"
    "eu.faircode.email"
    "app.familygem"
    "com.quran.labs.androidquran"
    "de.markusfisch.android.libra"
    "com.github.anrimian.musicplayer"
    "com.activitymanager"
    "hu.vmiklos.plees_tracker"
    "de.salomax.currencies"
    "com.red.alert"
)

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
    python3 start_bash.py replay_new \
        --csv-file "$csv" \
        --apk-base "$CSV_DIR/$pkg" \
        --max-parallel 8 \
        --run-count 3 \
        --parent-dir "$pkg"
done
