#!/bin/bash

# 批量分析app结果的脚本
# 用法: ./generate_report_multi_app2.sh <parent_dir> [--test]
# 例如: ./generate_report_multi_app2.sh com.byagowi.persiancalendar
# 例如: ./generate_report_multi_app2.sh com.byagowi.persiancalendar --test

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "用法: $0 <parent_dir> [--test]"
    echo "例如: $0 com.byagowi.persiancalendar"
    echo "例如: $0 com.byagowi.persiancalendar --test"
    exit 1
fi

PARENT_DIR="$1"
TEST_MODE=false

if [ $# -eq 2 ] && [ "$2" = "--test" ]; then
    TEST_MODE=true
    echo "🧪 TEST MODE: 将显示命令但不执行"
fi

CSV_FILE="droidbot/select_apks/${PARENT_DIR}.csv"

# 保存当前目录
ORIGINAL_DIR=$(pwd)

# 检查CSV文件是否存在
if [ ! -f "$CSV_FILE" ]; then
    echo "错误: CSV文件不存在: $CSV_FILE"
    exit 1
fi

# 从CSV文件读取版本信息（第7列，跳过前两行）
VERSIONS=()
while IFS=',' read -r -a fields; do
    if [ ${#fields[@]} -gt 6 ] && [ -n "${fields[6]}" ]; then
        version="${fields[6]}"
        # 去掉.apk后缀，只保留版本号
        if [[ "$version" == *.apk ]]; then
            version="${version%.apk}"
        fi
        # 将点号版本转换为下划线版本
        version_underscore=$(echo "$version" | sed 's/\./_/g')
        VERSIONS+=("$version_underscore")
    fi
done < <(tail -n +3 "$CSV_FILE")

echo "找到 ${#VERSIONS[@]} 个版本，开始批量分析..."

# 为每个版本生成报告
for base_app in "${VERSIONS[@]}"; do
    echo "=========================================="
    echo "处理 base_app: $base_app"
    echo "=========================================="
    
    if [ "$TEST_MODE" = true ]; then
        echo "🧪 TEST MODE - 将执行以下命令:"
        echo "1. python check_result.py --batch --deduplicate --base-app \"$base_app\" --parent-dir \"$PARENT_DIR/\" --parallel --max-workers 10"
        echo "2. cd $PARENT_DIR"
        if [ -f "${base_app}.tar.gz" ]; then
            echo "3. ⏭️  跳过压缩 (${base_app}.tar.gz 已存在)"
        else
            echo "3. tar -czvf \"${base_app}.tar.gz\" analysis.csv report_output*"
        fi
        echo "4. rm -rf *.csv report_output*"
        echo "5. cd $ORIGINAL_DIR"
        echo ""
    else
        # 1. generate report
        python check_result.py --batch --deduplicate --base-app "$base_app" --parent-dir "$PARENT_DIR/" --parallel --max-workers 10
        
        # 2. cd to parent-dir
        cd "$PARENT_DIR" || { echo "错误: 无法切换到目录 $PARENT_DIR"; exit 1; }
        
        # 3. tar the report (如果不存在才创建)
        if [ -f "${base_app}.tar.gz" ]; then
            echo "⏭️  跳过压缩: ${base_app}.tar.gz 已存在"
        else
            tar -czvf "${base_app}.tar.gz" analysis.csv report_output*
        fi
        
        # 4. rm
        rm -rf *.csv report_output*
        
        # 5. cd back to original directory
        cd "$ORIGINAL_DIR"
    fi
done

if [ "$TEST_MODE" = true ]; then
    echo "🧪 TEST MODE 完成 - 显示了所有将要执行的命令"
else
    echo "批量分析完成！"
fi