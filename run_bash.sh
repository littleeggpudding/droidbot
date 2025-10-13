#!/usr/bin/env bash
set -Eeuo pipefail

########################################
# 配置区（按需修改）
########################################
# ANDROID SDK 路径（已有全局环境就注释掉这几行）
export ANDROID_HOME=~/android-sdk
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
export PATH="$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator"

CSV_FILE="droidbot/select_apks/it.feio.android.omninotes.csv"         # 含 APK 文件名的 CSV（第7列）
APK_BASE="droidbot/select_apks/it.feio.android.omninotes"               # 第7列若是文件名，这里就是所在目录
AVD_NAME="Android10.0"                                            # 你的 AVD 名
COUNT=100                                                          # -count
MAX_PARALLEL=16                                                   # 并发上限（最多16）
HEADLESS=1                                                        # 1=无窗口; 0=有窗口
LOG_DIR="./logs"                                                  # 运行日志目录
START_PY="./start.py"                                             # 你的 start.py 路径
RUN_COUNT=20                                                       # 同一 APK 重复运行次数（例如 3 表示跑 3 次）

########################################
# 端口池（5554..5584 步长2，最多16 个）
########################################
BASE_PORT=5554
PORT_STEP=2
TOTAL_SLOTS=16

########################################
# 校验依赖
########################################
mkdir -p "$LOG_DIR"
command -v adb >/dev/null 2>&1 || { echo "ERROR: adb not found in PATH"; exit 1; }
command -v emulator >/dev/null 2>&1 || { echo "ERROR: emulator not found in PATH"; exit 1; }
command -v flock >/dev/null 2>&1 || { echo "ERROR: flock not found, please install util-linux"; exit 1; }
[[ -f "$START_PY" ]] || { echo "ERROR: $START_PY not found"; exit 1; }
[[ -f "$CSV_FILE" ]] || { echo "ERROR: CSV not found: $CSV_FILE"; exit 1; }

########################################
# 读取 CSV 第7列（跳过表头）
# 注意：简易 CSV 解析，若字段内含逗号/引号，建议改用更稳的解析方式
# +2是跳过第一行，+3是跳过第二行，最新版本的不生成
########################################
mapfile -t APKS < <(tail -n +3 "$CSV_FILE" | awk -F',' '{print $7}' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

if [[ ${#APKS[@]} -eq 0 ]]; then
  echo "ERROR: No APKs found in column 7 of $CSV_FILE"
  exit 1
fi

########################################
# 生成端口池文件（用 flock 互斥访问）
########################################
PORT_FILE="$(mktemp -t ports.XXXXXX)"
LOCK_FILE="$(mktemp -t ports.lock.XXXXXX)"
trap 'rm -f "$PORT_FILE" "$LOCK_FILE";' EXIT

# 构建最多16个端口，再裁剪到 MAX_PARALLEL
{
  for ((i=0;i<TOTAL_SLOTS;i++)); do
    port=$((BASE_PORT + i*PORT_STEP))
    echo "$port"
  done
} | head -n "$MAX_PARALLEL" > "$PORT_FILE"

########################################
# 工具函数
########################################
log() {
  # $1 device_serial / tag, $2 message
  printf '[%s] %s %s\n' "$(date '+%F %T')" "$1" "$2"
}

checkout_port() {
  # 原子取出第一个可用端口
  local port
  flock "$LOCK_FILE" bash -c '
    if [[ -s "'"$PORT_FILE"'" ]]; then
      port=$(head -n 1 "'"$PORT_FILE"'")
      tail -n +2 "'"$PORT_FILE"'" > "'"$PORT_FILE"'.tmp" && mv "'"$PORT_FILE"'.tmp" "'"$PORT_FILE"'"
      echo "$port"
    fi
  ' || true
}

release_port() {
  local port="$1"
  flock "$LOCK_FILE" bash -c 'echo "'"$port"'" >> "'"$PORT_FILE"'"'
}

wait_for_boot() {
  # $1 device_serial, $2 timeout
  local serial="$1" timeout="${2:-180}"
  local start ts
  start=$(date +%s)

  adb -s "$serial" wait-for-device || return 1
  while true; do
    if out=$(adb -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r'); then
      [[ "$out" == "1" ]] && sleep 3 && return 0
    fi
    ts=$(date +%s)
    (( ts - start > timeout )) && return 1
    sleep 2
  done
}

start_emulator() {
  # $1 AVD_NAME, $2 port, $3 headless(0/1)
  local avd="$1" port="$2" headless="${3:-1}"
  local args=( -avd "$avd" -port "$port" -read-only )
  [[ "$headless" -eq 1 ]] && args+=( -no-window )
  nohup emulator "${args[@]}" >/dev/null 2>&1 &
}

kill_emulator() {
  local serial="$1"
  adb -s "$serial" emu kill >/dev/null 2>&1 || true
}

sanitize() {
  # 清洗为输出目录名的安全片段
  local s="$1"
  s="${s##*/}"                 # 去路径
  s="${s%.apk}"                # 去后缀
  s="$(echo "$s" | tr -c '[:alnum:]._-' '_')"  # 非法字符转 _
  s="${s//./_}"                # 可选：如果你希望把点换成下划线
  s="${s%%_}"                  # 去掉结尾的下划线（重点）
  echo "${s:-apk}"
}

########################################
# 并发控制：基于后台作业 + 端口池
########################################
RUN_ONE() {
  local apk_rel="$1"
  local apk_path

  # 拼绝对路径或基目录
  if [[ -n "$APK_BASE" && ! "$apk_rel" =~ ^/ ]]; then
    apk_path="$APK_BASE/$apk_rel"
  else
    apk_path="$apk_rel"
  fi

  if [[ ! -f "$apk_path" ]]; then
    log "JOB" "APK not found: $apk_path"
    return
  fi

  local suffix
  suffix="$(sanitize "$apk_path")"

  # —— 新增：对同一 APK 重复运行 RUN_COUNT 次（逐次独立拉起/关闭模拟器）——
  local run_idx
  for ((run_idx=1; run_idx<=RUN_COUNT; run_idx++)); do
    # 取一个可用端口（阻塞等待）
    local port=""
    while [[ -z "$port" ]]; do
      port="$(checkout_port || true)"
      [[ -z "$port" ]] && sleep 0.5
    done

    local serial="emulator-$port"
    local out_dir="record_output_${suffix}_run${run_idx}"
    local run_log="$LOG_DIR/run_${suffix}_run${run_idx}_${port}.log"

    log "$serial" "START (run ${run_idx}/${RUN_COUNT}) for $apk_path"
    start_emulator "$AVD_NAME" "$port" "$HEADLESS"

    if ! wait_for_boot "$serial" 180; then
      log "$serial" "Boot timeout (run ${run_idx}), killing"
      kill_emulator "$serial"
      release_port "$port"
      continue
    fi

    # 执行你的命令
    local cmd=( python3 "$START_PY"
      -a "$apk_path"
      -o "$out_dir"
      -is_emulator
      -policy "random_exploration"
      -count "$COUNT"
      -d "$serial"
    )

    log "$serial" "CMD (run ${run_idx}): ${cmd[*]}"
    if "${cmd[@]}" >"$run_log" 2>&1; then
      log "$serial" "DONE OK (run ${run_idx}) → $out_dir"
    else
      log "$serial" "DONE FAIL (run ${run_idx}) (see $run_log)"
    fi
    # log "$serial" "TEST MODE → would run: ${cmd[*]}"
    # sleep 5  # 模拟运行时间
    # log "$serial" "TEST MODE → pretend finish OK → $out_dir"


    # 结束后关闭并释放端口
    kill_emulator "$serial"
    log "$serial" "killed, slot freed (run ${run_idx})"
    release_port "$port"
  done
}

########################################
# 主循环：最多并发 $MAX_PARALLEL
########################################
echo "=== Loaded ${#APKS[@]} APK(s); max_parallel=$MAX_PARALLEL; AVD=$AVD_NAME ==="

# 启动作业
for apk in "${APKS[@]}"; do
  RUN_ONE "$apk" &
  # 简单节流：限制后台作业数不超过 MAX_PARALLEL
  while true; do
    # 统计仍在运行的后台作业数
    running_jobs=$(jobs -rp | wc -l)
    [[ "$running_jobs" -lt "$MAX_PARALLEL" ]] && break
    sleep 0.5
  done
done

# 等待全部结束
wait
echo "=== ALL DONE ==="
