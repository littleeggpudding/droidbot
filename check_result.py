import sys
import argparse
import os
import glob
import csv
from multiprocessing import Pool, cpu_count
from droidbot.utils import generate_html_report


def find_replay_folders(parent_dir, base_app_filter=None):
    """
    在 parent_dir 下查找所有 replay_output_*_for_* 文件夹。
    如果提供 base_app_filter（例如 "3_8_0"），则仅返回 *_for_{base_app_filter} 的目录。
    """
    pattern = os.path.join(parent_dir, "replay_output_*_for_*")
    replay_folders = glob.glob(pattern)

    if base_app_filter:
        suffix = f"_for_{base_app_filter}"
        replay_folders = [p for p in replay_folders if os.path.basename(p).endswith(suffix)]

    return replay_folders


def derive_record_folder(replay_folder_name, parent_dir):
    """
    根据 replay 文件夹名推导对应的 record 文件夹名，并在 parent_dir 下查找。
    例：replay_output_6_3_0_run3_for_4_7_2 -> record_output_4_7_2_run3
    返回：basename（例如 record_output_4_7_2_run3）或 None
    """
    if "_for_" not in replay_folder_name:
        return None

    parts = replay_folder_name.split("_for_")
    if len(parts) != 2:
        return None

    target_version = parts[1]
    base_part = parts[0]
    
    # 提取run_count
    run_count = None
    if "_run" in base_part:
        run_parts = base_part.split("_run")
        if len(run_parts) == 2:
            run_count = run_parts[1]
    
    # 如果找到了run_count，尝试精确匹配
    if run_count:
        record_pattern = os.path.join(parent_dir, f"record_output_{target_version}_run{run_count}")
        if os.path.exists(record_pattern):
            return os.path.basename(record_pattern)
    
    # 如果精确匹配失败，回退到通配符匹配（保持向后兼容）
    record_pattern = os.path.join(parent_dir, f"record_output_{target_version}_run*")
    record_folders = glob.glob(record_pattern)
    if record_folders:
        return os.path.basename(record_folders[0])
    return None


def generate_report_name(replay_folder_name):
    """replay_output_* → report_output_*（仅替换首个 'replay_'）"""
    return replay_folder_name.replace("replay_", "report_", 1)


def parse_folder_names(replay_folder_name):
    """
    解析 {base_app}, {run_count}, {target_app}
    replay: replay_output_{target_app}_run{run_count}_for_{base_app}
    例如: replay_output_v9_6_0_run1_for_v6_4_1
    - target_app: v9_6_0 (在replay_output_后面，_for_前面)
    - base_app: v6_4_1 (在_for_后面)
    - run_count: 1 (在_run后面)
    """
    base_app = "unknown"
    target_app = "unknown"
    run_count = "unknown"

    # replay_folder_name: replay_output_v9_6_0_run1_for_v6_4_1
    # 按 "_for_" 分割
    replay_parts = replay_folder_name.split("_for_")
    if len(replay_parts) == 2:
        # base_app 是 _for_ 后面的部分
        base_app = replay_parts[1]
        
        # target_app 和 run_count 在 _for_ 前面的部分
        target_part = replay_parts[0].replace("replay_output_", "")
        # 按 "_run" 分割
        target_parts = target_part.split("_run")
        if len(target_parts) == 2:
            target_app = target_parts[0]
            run_count = target_parts[1]

    return {
        'base_app': base_app,
        'run_count': run_count,
        'target_app': target_app
    }


def count_replay_events_json(replay_dir):
    """
    统计 replay_dir/events 目录下的 .json 数量。
    返回 (count, events_dir_exists)
    """
    events_dir = os.path.join(replay_dir, "events")
    if not os.path.isdir(events_dir):
        return 0, False
    json_paths = glob.glob(os.path.join(events_dir, "*.json"))
    return len(json_paths), True


def classify_failure_stage(json_count, events_dir_exists):
    """
    基于 json 数量做一个粗粒度的失败阶段推断（启发式，便于快速定位）：
      - 无 events 目录：no_events_dir
      - 0：launcher_failed（未开始或极早期失败）
      - 1–9：very_early
      - 10–49：early
      - 50–99：mid
      - >=100：complete（达到既定最小阈值，通常视为覆盖充分）
    """
    if not events_dir_exists:
        return "no_events_dir"
    if json_count == 0:
        return "launcher_failed"
    if json_count < 10:
        return "very_early"
    if json_count < 50:
        return "early"
    if json_count < 100:
        return "mid"
    return "complete"


def process_single_replay(args):
    """
    处理单个replay文件夹的函数，用于并行处理
    """
    (replay_folder, parent_dir, test_mode) = args
    replay_name = os.path.basename(replay_folder)
    
    # 推导 record
    record_name = derive_record_folder(replay_name, parent_dir)
    if not record_name:
        return {
            'base_app': parse_folder_names(replay_name).get('base_app'),
            'run_count': parse_folder_names(replay_name).get('run_count'),
            'target_app': parse_folder_names(replay_name).get('target_app'),
            'replay_dir': replay_name,
            'record_dir': '',
            'report_dir': '',
            'events_json_count': 0,
            'failure_stage': 'unknown',
            'status': 'error',
            'note': 'record_not_found_or_unparsable'
        }
    
    record_path = os.path.join(parent_dir, record_name)
    if not os.path.exists(record_path):
        events_count, events_dir_exists = count_replay_events_json(replay_folder)
        failure_stage = classify_failure_stage(events_count, events_dir_exists)
        return {
            'base_app': parse_folder_names(replay_name).get('base_app'),
            'run_count': parse_folder_names(replay_name).get('run_count'),
            'target_app': parse_folder_names(replay_name).get('target_app'),
            'replay_dir': replay_name,
            'record_dir': record_name,
            'report_dir': '',
            'events_json_count': events_count,
            'failure_stage': failure_stage,
            'status': 'error',
            'note': 'record_missing_on_disk'
        }
    
    # 生成报告目录名
    report_name = generate_report_name(replay_name)
    report_path = os.path.join(parent_dir, report_name)
    
    # 解析信息
    folder_info = parse_folder_names(replay_name)
    
    # 统计 events/*.json
    events_count, events_dir_exists = count_replay_events_json(replay_folder)
    failure_stage = classify_failure_stage(events_count, events_dir_exists)
    
    # 检查是否达到100个events（表示测试完成）→ 跳过生成
    if events_count >= 100:
        return {
            'base_app': folder_info['base_app'],
            'run_count': folder_info['run_count'],
            'target_app': folder_info['target_app'],
            'replay_dir': replay_name,
            'record_dir': record_name,
            'report_dir': report_name,
            'events_json_count': events_count,
            'failure_stage': failure_stage,
            'status': 'skipped',
            'note': 'test_completed_100_events'
        }
    
    # 已存在报告 → 跳过生成
    if os.path.exists(report_path):
        return {
            'base_app': folder_info['base_app'],
            'run_count': folder_info['run_count'],
            'target_app': folder_info['target_app'],
            'replay_dir': replay_name,
            'record_dir': record_name,
            'report_dir': report_name,
            'events_json_count': events_count,
            'failure_stage': failure_stage,
            'status': 'skipped',
            'note': 'report_exists'
        }
    
    # 生成报告
    record_path_abs = os.path.abspath(record_path)
    replay_folder_abs = os.path.abspath(replay_folder)
    report_path_abs = os.path.abspath(report_path)
    
    if test_mode:
        # 测试模式：不实际执行
        return {
            'base_app': folder_info['base_app'],
            'run_count': folder_info['run_count'],
            'target_app': folder_info['target_app'],
            'replay_dir': replay_name,
            'record_dir': record_name,
            'report_dir': report_name,
            'events_json_count': events_count,
            'failure_stage': failure_stage,
            'status': 'test_mode',
            'note': 'test_mode_execution'
        }
    else:
        # 正常模式：实际执行
        try:
            result = generate_html_report(record_path_abs, replay_folder_abs, report_path_abs)
            return {
                'base_app': folder_info['base_app'],
                'run_count': folder_info['run_count'],
                'target_app': folder_info['target_app'],
                'replay_dir': replay_name,
                'record_dir': record_name,
                'report_dir': report_name,
                'events_json_count': events_count,
                'failure_stage': failure_stage,
                'status': 'processed',
                'note': ''
            }
        except Exception as e:
            return {
                'base_app': folder_info['base_app'],
                'run_count': folder_info['run_count'],
                'target_app': folder_info['target_app'],
                'replay_dir': replay_name,
                'record_dir': record_name,
                'report_dir': report_name,
                'events_json_count': events_count,
                'failure_stage': failure_stage,
                'status': 'error',
                'note': f'exception: {e}'
            }


def batch_analysis(parent_dir, base_app_filter=None, test_mode=False, parallel=False, max_workers=None):
    """在 parent_dir 下批量分析，按 base_app_filter（可选）过滤"""
    print("Starting batch analysis...")
    print(f"Parent dir: {parent_dir}")
    if base_app_filter:
        print(f"Base app filter: {base_app_filter}")
    if test_mode:
        print("🧪 TEST MODE: Will show commands instead of executing them")
    if parallel:
        workers = max_workers if max_workers else min(cpu_count(), 4)  # 默认最多4个进程
        print(f"🚀 PARALLEL MODE: Using {workers} workers")

    # 查找 replay
    replay_folders = find_replay_folders(parent_dir, base_app_filter=base_app_filter)

    if not replay_folders:
        print("No replay_output_*_for_* folders found with the given criteria.")
        return

    print(f"Found {len(replay_folders)} replay folders:")
    for folder in replay_folders:
        print(f"  - {os.path.basename(folder)}")

    # 准备参数
    process_args = [(replay_folder, parent_dir, test_mode) for replay_folder in replay_folders]

    if parallel and not test_mode:
        # 并行处理
        print(f"\n🚀 Processing {len(replay_folders)} folders in parallel...")
        with Pool(processes=workers) as pool:
            analysis_results = pool.map(process_single_replay, process_args)
    else:
        # 串行处理（测试模式或非并行模式）
        print(f"\n🔄 Processing {len(replay_folders)} folders sequentially...")
        analysis_results = []
        for i, args in enumerate(process_args, 1):
            replay_folder, parent_dir, test_mode = args
            replay_name = os.path.basename(replay_folder)
            
            if test_mode:
                print(f"[{i}/{len(process_args)}] 🧪 Testing {replay_name}")
            else:
                print(f"[{i}/{len(process_args)}] 🔄 Processing {replay_name}")
            
            result = process_single_replay(args)
            analysis_results.append(result)
            
            # 在测试模式下显示详细信息
            if test_mode and result['status'] == 'test_mode':
                print(f"   🧪 TEST MODE - Would execute:")
                print(f"      Python command: python -c \"from droidbot.utils import generate_html_report; generate_html_report('...', '...', '...')\"")
                print(f"      Arguments:")
                print(f"        - replay: {result['replay_dir']}")
                print(f"        - record: {result['record_dir']}")
                print(f"        - events count: {result['events_json_count']}")
                print(f"        - would skip (≥100 events): {'✅ YES' if result['events_json_count'] >= 100 else '❌ NO'}")

    # 统计结果
    processed_count = sum(1 for r in analysis_results if r['status'] == 'processed')
    skipped_count = sum(1 for r in analysis_results if r['status'] == 'skipped')
    error_count = sum(1 for r in analysis_results if r['status'] == 'error')
    test_mode_count = sum(1 for r in analysis_results if r['status'] == 'test_mode')

    # 生成 CSV（放在 parent_dir 下）
    csv_filename = os.path.join(parent_dir, "analysis.csv")
    try:
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'base_app', 'run_count', 'target_app',
                'replay_dir', 'record_dir', 'report_dir',
                'events_json_count', 'failure_stage', 'status', 'note'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for result in analysis_results:
                writer.writerow(result)

        print(f"\n📊 CSV report generated: {csv_filename}")
        print(f"   - Total records: {len(analysis_results)}")
    except Exception as e:
        print(f"❌ Error generating CSV: {e}")

    print(f"\nBatch analysis completed:")
    print(f"  - Processed: {processed_count}")
    print(f"  - Skipped: {skipped_count}")
    print(f"  - Errors: {error_count}")
    if test_mode:
        print(f"  - Test mode: {test_mode_count}")
    print(f"  - Total: {len(replay_folders)}")


def main():
    parser = argparse.ArgumentParser(description='Generate HTML report for DroidBot test results')
    parser.add_argument('--batch', action='store_true', help='Run batch analysis on replay folders')
    parser.add_argument('--test-mode', action='store_true', help='Test mode: show commands instead of executing them (only works with --batch)')
    parser.add_argument('--parallel', action='store_true', help='Enable parallel processing for batch mode (faster but uses more CPU)')
    parser.add_argument('--max-workers', type=int, default=None,
                        help='Maximum number of parallel workers (default: min(CPU cores, 4))')
    parser.add_argument('--deduplicate', action='store_true', help='Enable deduplication mode to find unique test cases')
    parser.add_argument('--run-count', default=None, help='Filter by specific run count for deduplication (e.g., "1")')
    parser.add_argument('--parent-dir', default=os.getcwd(),
                        help='Root directory to search for record/replay/report folders (default: CWD)')
    parser.add_argument('--base-app', default=None,
                        help='Filter replay folders by base app version (e.g., "3_8_0" to match *_for_3_8_0)')
    parser.add_argument('output_dir', nargs='?', help='Directory containing record data (original test output)')
    parser.add_argument('replay_output_dir', nargs='?', help='Directory containing replay data (optional)')
    parser.add_argument('out_dir', nargs='?', help='Output directory for the complete report (HTML + images)')

    args = parser.parse_args()

    parent_dir = os.path.abspath(args.parent_dir)

    if args.batch:
        # 验证test-mode只能与batch一起使用
        if args.test_mode and not args.batch:
            parser.error("--test-mode can only be used with --batch")
        
        # 检查是否使用去重模式
        if args.deduplicate:
            print("🔍 Running in deduplication mode...")
            deduplicated_results = de_duplicate_case(
                parent_dir=parent_dir, 
                base_app_filter=args.base_app, 
                run_count_filter=args.run_count
            )
            
            # 生成去重后的CSV报告
            csv_filename = os.path.join(parent_dir, "deduplicated_analysis.csv")
            try:
                with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = [
                        'base_app', 'run_count', 'target_app',
                        'replay_dir', 'events_json_count', 'failure_stage', 
                        'group_key', 'is_unique'
                    ]
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    for result in deduplicated_results:
                        # 解析base_app和run_count
                        folder_info = parse_folder_names(result['replay_name'])
                        writer.writerow({
                            'base_app': folder_info['base_app'],
                            'run_count': folder_info['run_count'],
                            'target_app': result['target_app'],
                            'replay_dir': result['replay_name'],
                            'events_json_count': result['events_count'],
                            'failure_stage': result['failure_stage'],
                            'group_key': result['group_key'],
                            'is_unique': result['is_unique']
                        })
                
                print(f"\n📊 Deduplicated CSV report generated: {csv_filename}")
                print(f"   - Unique cases: {len(deduplicated_results)}")
            except Exception as e:
                print(f"❌ Error generating deduplicated CSV: {e}")
            
            # 为去重后的结果生成HTML报告
            if deduplicated_results:
                print(f"\n🔄 Generating HTML reports for {len(deduplicated_results)} unique cases...")
                generate_deduplicated_reports(deduplicated_results, parent_dir, args.parallel, args.max_workers)
        else:
            # 正常batch模式
            batch_analysis(parent_dir=parent_dir, base_app_filter=args.base_app, test_mode=args.test_mode, 
                          parallel=args.parallel, max_workers=args.max_workers)
    else:
        # 单个报告生成（保持向后兼容）
        if not args.output_dir:
            parser.error("output_dir is required when not using --batch mode")

        output_dir = os.path.abspath(args.output_dir)
        replay_output_dir = os.path.abspath(args.replay_output_dir) if args.replay_output_dir else None
        out_dir = os.path.abspath(args.out_dir) if args.out_dir else None

        # 单个也统计一次 events_json（如果用户给了 replay_output_dir）
        events_count, events_dir_exists = (0, False)
        if replay_output_dir:
            events_count, events_dir_exists = count_replay_events_json(replay_output_dir)
            stage = classify_failure_stage(events_count, events_dir_exists)
            print(f"[Single] events_json_count={events_count}, failure_stage={stage}")

        result = generate_html_report(output_dir, replay_output_dir, out_dir)
        print(f"Report generated successfully: {result}")


def read_version_order_from_csv(parent_dir):
    """
    从select_apks目录读取CSV文件，获取版本的时间顺序
    使用与start_bash.py相同的方法：直接读取第7列（索引6），跳过前两行
    例如：parent_dir是com.byagowi.persiancalendar，则读取select_apks/com.byagowi.persiancalendar.csv
    """
    # 构建CSV文件路径 
    app_name = parent_dir.split("/")[-1]
    csv_path = os.path.join("droidbot/select_apks/", f"{app_name}.csv")
    
    if not os.path.exists(csv_path):
        print(f"⚠️  CSV file not found: {csv_path}")
        return None

    
    try:
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            rows = list(reader)
        
        versions = []
        for row in rows[1:]:
            if len(row) > 6 and row[6].strip():
                version = row[6].strip()
                # 去掉.apk后缀，只保留版本号
                if version.endswith('.apk'):
                    version = version[:-4]
                versions.append(version)
        
        versions.reverse()  # from old to new
        return versions
            
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return None


def de_duplicate_case(parent_dir, base_app_filter=None, run_count_filter=None):
    """
    去重报告 - 根据events_json_count的变化识别有意义的测试案例
    
    1. 从select_apks目录读取CSV文件，获取版本的时间顺序
    2. 固定一个run count，找到这些版本的replay中的events_json_count
    3. 取第一个不相同的events_json_count，生成对应的报告
    
    例如：base app是v6.4.1，target app按时间顺序是v6.4.2, v6.4.3, v6.4.4, v6.4.5, v6.4.6, v6.4.7
    events_json_count: 51, 49, 49, 32, 7, 7
    结果：需要生成报告的target app序号是1,2,4,5 (第一个不相同的events_json_count)
    """
    print("🔍 Starting deduplication analysis...")
    print(f"Parent dir: {parent_dir}")
    if base_app_filter:
        print(f"Base app filter: {base_app_filter}")
    if run_count_filter:
        print(f"Run count filter: {run_count_filter}")
    else:
        print("Run count filter: None (processing all run counts)")
    
    # 第一步：从CSV读取版本顺序
    csv_versions = read_version_order_from_csv(parent_dir)
    if not csv_versions:
        print("❌ Cannot proceed without version order from CSV")
        return []
    
    # 第二步：查找所有replay文件夹
    replay_folders = find_replay_folders(parent_dir, base_app_filter=base_app_filter)
    print(f"Found {len(replay_folders)} replay folders:")
    print(f"{replay_folders[0]}")
    
    if not replay_folders:
        print("No replay_output_*_for_* folders found.")
        return []
    
    # 第三步：按base_app和run_count分组，并按CSV版本顺序排序
    groups = {}
    for replay_folder in replay_folders:
        replay_name = os.path.basename(replay_folder)
        folder_info = parse_folder_names(replay_name)
        
        base_app = folder_info['base_app']
        run_count = folder_info['run_count']
        target_app = folder_info['target_app']

        # 如果指定了run_count_filter，只处理匹配的（默认处理所有run count）
        if run_count_filter and str(run_count) != str(run_count_filter):
            continue
            
        # 如果指定了base_app_filter，只处理匹配的
        if base_app_filter and base_app != base_app_filter:
            continue
        
        key = f"{base_app}_run{run_count}"
        if key not in groups:
            groups[key] = []
        
        # 统计events数量
        events_count, events_dir_exists = count_replay_events_json(replay_folder)
        
        groups[key].append({
            'replay_folder': replay_folder,
            'replay_name': replay_name,
            'target_app': target_app,
            'events_count': events_count,
            'events_dir_exists': events_dir_exists,
            'failure_stage': classify_failure_stage(events_count, events_dir_exists)
        })
    
    print(f"Found {len(groups)} groups to analyze:")
    for key, items in groups.items():
        print(f"  - {key}: {len(items)} target apps")
    
    # 第四步：对每个组进行去重分析
    deduplicated_results = []
    
    for group_key, items in groups.items():
        print(f"\n📊 Analyzing group: {group_key}")

        # print(f"CSV versions: {csv_versions}")
        
        # 按CSV中的版本顺序排序
        def get_version_order(item):
            target_app = item['target_app']
            # 逆向sanitize_suffix：将下划线版本转换为点号版本进行匹配
            # 例如：v9_9_1 → v9.9.1
            target_app_dots = target_app.replace('_', '.')
            try:
                return csv_versions.index(target_app_dots)
            except ValueError:
                # 如果版本不在CSV中，放到最后
                return len(csv_versions)
        
        items.sort(key=get_version_order)
        
        print(f"Target apps in CSV order: {[item['target_app'] for item in items]}")
        print(f"Events counts: {[item['events_count'] for item in items]}")
        
        # 去重逻辑：取第一个不相同的events_json_count
        unique_indices = []
        last_events_count = None
        
        for i, item in enumerate(items):
            current_events_count = item['events_count']
            
            # 如果是第一个，或者events_count与上一个不同，则保留
            if last_events_count is None or current_events_count != last_events_count:
                unique_indices.append(i)
                last_events_count = current_events_count
                print(f"  ✅ Keep {item['target_app']} (events: {current_events_count})")
            else:
                print(f"  ⏭️  Skip {item['target_app']} (events: {current_events_count}, same as previous)")
        
        # 将去重后的结果添加到最终列表
        for idx in unique_indices:
            item = items[idx]
            deduplicated_results.append({
                'replay_folder': item['replay_folder'],
                'replay_name': item['replay_name'],
                'target_app': item['target_app'],
                'events_count': item['events_count'],
                'events_dir_exists': item['events_dir_exists'],
                'failure_stage': item['failure_stage'],
                'group_key': group_key,
                'is_unique': True
            })
    
    print(f"\n🎯 Deduplication completed:")
    print(f"  - Original total: {sum(len(items) for items in groups.values())}")
    print(f"  - Unique cases: {len(deduplicated_results)}")
    print(f"  - Reduction: {sum(len(items) for items in groups.values()) - len(deduplicated_results)} cases removed")
    
    return deduplicated_results


def generate_deduplicated_reports(deduplicated_results, parent_dir, parallel=False, max_workers=None):
    """
    为去重后的结果生成HTML报告
    """
    print(f"🔄 Generating HTML reports for {len(deduplicated_results)} unique cases...")
    
    if parallel:
        workers = max_workers if max_workers else min(cpu_count(), 4)
        print(f"🚀 PARALLEL MODE: Using {workers} workers")
    
    # 准备参数
    process_args = []
    for result in deduplicated_results:
        replay_folder = result['replay_folder']
        replay_name = result['replay_name']
        
        # 推导record文件夹
        record_name = derive_record_folder(replay_name, parent_dir)
        if not record_name:
            print(f"⚠️  Could not derive record folder for {replay_name}")
            continue
            
        record_path = os.path.join(parent_dir, record_name)
        if not os.path.exists(record_path):
            print(f"⚠️  Record folder not found: {record_name}")
            continue
        
        # 生成报告目录名
        report_name = generate_report_name(replay_name)
        report_path = os.path.join(parent_dir, report_name)
        
        # 检查是否已存在报告
        if os.path.exists(report_path):
            print(f"⏭️  Skipping {replay_name} - report already exists: {report_name}")
            continue
        
        process_args.append((replay_folder, record_path, report_path))
    
    if not process_args:
        print("No reports to generate.")
        return
    
    print(f"Found {len(process_args)} reports to generate")
    
    if parallel:
        # 并行处理
        print(f"🚀 Processing {len(process_args)} reports in parallel...")
        with Pool(processes=workers) as pool:
            results = pool.map(generate_single_report, process_args)
    else:
        # 串行处理
        print(f"🔄 Processing {len(process_args)} reports sequentially...")
        results = []
        for i, args in enumerate(process_args, 1):
            print(f"[{i}/{len(process_args)}] 🔄 Processing {os.path.basename(args[0])}")
            result = generate_single_report(args)
            results.append(result)
    
    # 统计结果
    success_count = sum(1 for r in results if r['status'] == 'success')
    error_count = sum(1 for r in results if r['status'] == 'error')
    
    print(f"\nHTML report generation completed:")
    print(f"  - Success: {success_count}")
    print(f"  - Errors: {error_count}")
    print(f"  - Total: {len(process_args)}")


def generate_single_report(args):
    """
    生成单个HTML报告的函数，用于并行处理
    """
    replay_folder, record_path, report_path = args
    
    try:
        result = generate_html_report(record_path, replay_folder, report_path)
        return {
            'status': 'success',
            'replay_folder': os.path.basename(replay_folder),
            'report_path': os.path.basename(report_path),
            'result': result
        }
    except Exception as e:
        return {
            'status': 'error',
            'replay_folder': os.path.basename(replay_folder),
            'report_path': os.path.basename(report_path),
            'error': str(e)
        }


if __name__ == "__main__":
    main()


# python check_result.py --batch --deduplicate --base-app v6_4_1 --parent-dir com.byagowi.persiancalendar/ --parallel --max-workers 10