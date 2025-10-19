#!/bin/bash
set -u

export ANDROID_HOME=~/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$PATH
export PATH=$PATH:$ANDROID_HOME/platform-tools
export PATH=$PATH:$ANDROID_HOME/emulator

# ===== 配置 =====
AVD_NAME="Android10.0"
START_PORT=5554
NUM_EMULATORS=${1:-16}
LOG_DIR="./emulator_logs"
MAX_RETRY=3

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%F %T')] $*"; }

cleanup_device() {
  local port=$1
  adb -s emulator-$port emu kill 2>/dev/null || true
  pkill -f "emulator.*-port $port" 2>/dev/null || true
}

cleanup_all() {
  log "清理可能存在的模拟器..."
  for ((i=0; i<NUM_EMULATORS; i++)); do
    port=$((START_PORT + i*2))
    cleanup_device "$port"
  done
  pkill -f "emulator.*-avd $AVD_NAME" 2>/dev/null || true
  if [[ "${1:-}" == "from_trap" ]]; then
    exit 0
  fi
}
trap 'cleanup_all from_trap' SIGINT SIGTERM

check_avd() {
  if ! avdmanager list avd | grep -q "Name: $AVD_NAME"; then
    echo "错误: AVD '$AVD_NAME' 不存在"
    exit 1
  fi
}

start_emulator() {
  local port=$1
  emulator -avd "$AVD_NAME" \
    -port "$port" \
    -no-window \
    -read-only \
    -no-snapshot \
    -no-snapshot-save \
    -no-boot-anim \
    -accel on \
    -gpu swiftshader_indirect \
    >/dev/null 2>&1 &
  echo $!
}

wait_for_device() {
  local device_serial=$1
  local timeout_sec=${2:-120}
  if timeout "$timeout_sec" adb -s "$device_serial" wait-for-device 2>/dev/null; then
    return 0
  else
    return 1
  fi
}

wait_for_boot() {
  local device_serial=$1
  local timeout_sec=${2:-180}
  local start=$(date +%s)
  while (( $(date +%s) - start < timeout_sec )); do
    local boot_completed
    boot_completed=$(adb -s "$device_serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n')
    if [[ "$boot_completed" == "1" ]]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

try_boot_emulator() {
  local port=$1
  local device="emulator-$port"
  local attempt=1

  while (( attempt <= MAX_RETRY )); do
    log "[$device] 启动尝试 #$attempt ..."
    cleanup_device "$port"
    sleep 2
    start_emulator "$port" >/dev/null
    sleep 3

    if ! wait_for_device "$device" 180; then
      log "[$device] 连接失败 (尝试 #$attempt)"
      attempt=$((attempt+1))
      continue
    fi

    if wait_for_boot "$device" 300; then
      log "[$device] 启动成功 (尝试 #$attempt)"
      echo "$device" >> "$LOG_DIR/ready_devices.txt"
      return 0
    else
      log "[$device] 启动超时 (尝试 #$attempt)"
    fi

    attempt=$((attempt+1))
  done

  log "[$device] 启动失败 (重试 $MAX_RETRY 次后)"
  echo "$device" >> "$LOG_DIR/failed_devices.txt"
  return 1
}

main() {
  check_avd
  cleanup_all || true
  sleep 2

  : > "$LOG_DIR/ready_devices.txt"
  : > "$LOG_DIR/failed_devices.txt"

  local start_time=$(date +%s)
  log "开始启动 $NUM_EMULATORS 个模拟器..."

  # 并发启动
  for ((i=0; i<NUM_EMULATORS; i++)); do
    port=$((START_PORT + i*2))
    try_boot_emulator "$port" &
    sleep 1
  done
  
  # ✅ 关键改进: 等待所有后台任务完成
  log "等待所有模拟器启动完成..."
  wait

  local end_time=$(date +%s)
  local total_time=$((end_time - start_time))

  echo
  log "=== 启动完成报告 ==="
  log "结束时间: $(date)"
  log "总耗时: ${total_time} 秒"
  
  local success_count
  success_count=$(wc -l < "$LOG_DIR/ready_devices.txt" 2>/dev/null || echo 0)
  local fail_count
  fail_count=$(wc -l < "$LOG_DIR/failed_devices.txt" 2>/dev/null || echo 0)
  
  log "成功就绪: $success_count/$NUM_EMULATORS"
  log "失败: $fail_count/$NUM_EMULATORS"

  if (( success_count > 0 )); then
    echo "就绪设备："
    cat "$LOG_DIR/ready_devices.txt"
  fi
  if (( fail_count > 0 )); then
    echo "失败设备："
    cat "$LOG_DIR/failed_devices.txt"
  fi
  echo

  log "日志目录: $LOG_DIR/"
  
  if (( success_count == NUM_EMULATORS )); then
    log "✓ 所有 $NUM_EMULATORS 个模拟器启动成功"
    exit 0
  elif (( success_count > 0 )); then
    log "⚠ 部分成功: $success_count/$NUM_EMULATORS"
    exit 0  # 部分成功也返回 0，让 Python 继续
  else
    log "✗ 所有模拟器启动失败"
    exit 1
  fi
}

main "$@"