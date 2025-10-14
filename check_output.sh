#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

MIN_JSON=100     # 阈值
DRY_RUN=0        # 0=真实删除；1=只打印不删

to_delete=()

# 收集当前目录下所有 record_output_* 目录
all_dirs=()
for d in record_output_*; do
  [[ -d "$d" ]] && all_dirs+=("$d")
done

# 找到含有 events 的那些父目录
has_events_parents=()
for ev in record_output_*/events; do
  [[ -d "$ev" ]] && has_events_parents+=("${ev%/events}")
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

# 2) events 下 json 少于阈值的，标记删除
for p in "${has_events_parents[@]}"; do
  cnt=$(find "$p/events" -maxdepth 1 -type f -name '*.json' | wc -l)
  if (( cnt < MIN_JSON )); then
    echo "[INSUFFICIENT] $p → only $cnt json files (min=$MIN_JSON)"
    to_delete+=("$p")
  fi
done

# 去重
if ((${#to_delete[@]})); then
  readarray -t to_delete < <(printf "%s\n" "${to_delete[@]}" | awk '!seen[$0]++')

  echo "==== Deleting ${#to_delete[@]} folder(s) ===="
  for d in "${to_delete[@]}"; do
    # 只允许删除以 record_output_ 开头的相对路径目录，做个安全防护
    if [[ -d "$d" && "$d" == record_output_* ]]; then
      if (( DRY_RUN )); then
        echo "[DRY-RUN] rm -rf -- '$d'"
      else
        echo "rm -rf -- '$d'"
        rm -rf -- "$d"
      fi
    else
      echo "[SKIP] unsafe target: $d"
    fi
  done
else
  echo "All record_output_* folders are valid (>= $MIN_JSON json files)."
fi