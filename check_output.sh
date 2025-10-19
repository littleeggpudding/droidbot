#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

########################################
# 参数解析
########################################
usage() {
    echo "用法: $0 [选项]"
    echo "选项:"
    echo "  -t, --target TARGET    目标类型: record 或 replay (默认: replay)"
    echo "  -p, --parent-dir DIR   父目录路径 (默认: 当前目录)"
    echo "  -j, --min-json NUM     events 下最少 json 文件数 (默认: 100)"
    echo "  -s, --min-states NUM   states 下期望的状态数量 (默认: 99)"
    echo "  -h, --help            显示帮助信息"
    exit 1
}

# 默认值
TARGET="replay"
PARENT_DIR=""
MIN_JSON=100
MIN_STATES=99

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--target)
            TARGET="$2"
            shift 2
            ;;
        -p|--parent-dir)
            PARENT_DIR="$2"
            shift 2
            ;;
        -j|--min-json)
            MIN_JSON="$2"
            shift 2
            ;;
        -s|--min-states)
            MIN_STATES="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "未知参数: $1"
            usage
            ;;
    esac
done

# 验证参数
if [[ "$TARGET" != "record" && "$TARGET" != "replay" ]]; then
    echo "❌ TARGET 只能是 'record' 或 'replay'，当前: $TARGET"
    exit 1
fi

# 设置工作目录
if [[ -n "$PARENT_DIR" ]]; then
    if [[ ! -d "$PARENT_DIR" ]]; then
        echo "❌ 父目录不存在: $PARENT_DIR"
        exit 1
    fi
    cd "$PARENT_DIR"
    echo "📁 工作目录: $(pwd)"
fi

########################################
# 根据 TARGET 决定前缀
########################################
case "$TARGET" in
  record) PREFIX="record_output_" ;;
  replay) PREFIX="replay_output_" ;;
  *) echo "❌ TARGET 只能是 'record' 或 'replay'，当前: $TARGET"; exit 1 ;;
esac

to_delete=()

# 收集当前目录下所有 ${PREFIX}* 目录
# all_dirs=()
# for d in ${PREFIX}*; do
#   [[ -d "$d" ]] && all_dirs+=("$d")
# done
# 收集当前目录下所有 ${PREFIX}* 目录（但排除 *_for_* 的）
all_dirs=()
for d in ${PREFIX}*; do
  [[ -d "$d" ]] || continue
  if [[ "$TARGET" == "replay" && "$d" == *"_for_"* ]]; then
    # 跳过 replay_output_*_for_* 这样的目录
    continue
  fi
  all_dirs+=("$d")
done


# 找到含有 events 的那些父目录（只看当前前缀）
has_events_parents=()
for ev in ${PREFIX}*/events; do
  [[ -d "$ev" ]] && has_events_parents+=("${ev%/events}")
done

# 找到含有 states 的那些父目录（只看当前前缀）
has_states_parents=()
for st in ${PREFIX}*/states; do
  [[ -d "$st" ]] && has_states_parents+=("${st%/states}")
done

# 1) 没有 events 的，标记删除
for d in "${all_dirs[@]}"; do
  found=false
  for p in "${has_events_parents[@]}"; do
    [[ "$p" == "$d" ]] && found=true && break
  done
  if ! $found; then
    echo "[MISSING] $d → no events folder"
    to_delete+=("$d")
  fi
done

# 1b) 没有 states 的，标记删除
for d in "${all_dirs[@]}"; do
  found=false
  for p in "${has_states_parents[@]}"; do
    [[ "$p" == "$d" ]] && found=true && break
  done
  if ! $found; then
    echo "[MISSING] $d → no states folder"
    to_delete+=("$d")
  fi
done

# 2) events 下 json 少于阈值的，标记删除
for p in "${has_events_parents[@]}"; do
  cnt=$(find "$p/events" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')
  if (( cnt < MIN_JSON )); then
    echo "[INSUFFICIENT] $p → only $cnt json files in events (min=$MIN_JSON)"
    to_delete+=("$p")
  fi
done

# 3) states 数量不等于 MIN_STATES 的，标记删除
for p in "${has_states_parents[@]}"; do
  # 优先按文件计数：state_*.json
  if compgen -G "$p/states/state_*.json" > /dev/null; then
    scnt=$(find "$p/states" -maxdepth 1 -type f -name 'state_*.json' | wc -l | tr -d ' ')
  else
    # 兜底：按目录计数 state_*
    scnt=$(find "$p/states" -maxdepth 1 -type d -name 'state_*' | wc -l | tr -d ' ')
  fi

  if [[ "$scnt" != "$MIN_STATES" ]]; then
    echo "[BAD-STATES] $p → states count=$scnt (expect=$MIN_STATES)"
    to_delete+=("$p")
  fi
done

# 去重并执行删除（仅限当前 PREFIX）
if ((${#to_delete[@]})); then
  readarray -t to_delete < <(printf "%s\n" "${to_delete[@]}" | awk '!seen[$0]++')

  echo "==== 发现 ${#to_delete[@]} 个需要删除的文件夹 ===="
  echo "目标类型: $TARGET"
  echo "工作目录: $(pwd)"
  echo ""
  echo "将要删除的文件夹:"
  for d in "${to_delete[@]}"; do
    if [[ -d "$d" && "$d" == ${PREFIX}* ]]; then
      echo "  - $d"
    else
      echo "  - [SKIP] $d (不安全的目标)"
    fi
  done
  echo ""
  
  # 用户确认删除
  read -p "确认删除这些文件夹吗？输入 'yes' 确认: " confirm
  if [[ "$confirm" == "yes" ]]; then
    echo "开始删除..."
    for d in "${to_delete[@]}"; do
      if [[ -d "$d" && "$d" == ${PREFIX}* ]]; then
        echo "删除: $d"
        rm -rf -- "$d"
      else
        echo "[SKIP] 不安全的目标: $d"
      fi
    done
    echo "✅ 删除完成"
  else
    echo "❌ 取消删除"
  fi
else
  echo "✅ All ${PREFIX}* folders are valid (events >= $MIN_JSON json, states == $MIN_STATES)."
fi
