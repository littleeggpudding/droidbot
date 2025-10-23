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


def parse_folder_names(replay_folder_name, record_folder_name=None):
    """
    解析 {base_app}, {run_count}, {target_app}
    replay: replay_output_{base_app}_run{run_count}_for_{target_app}
    """
    base_app = "unknown"
    target_app = "unknown"
    run_count = "unknown"

    replay_parts = replay_folder_name.split("_for_")
    if len(replay_parts) == 2:
        target_app = replay_parts[1]
        base_part = replay_parts[0]
        base_parts = base_part.split("_run")
        if len(base_parts) == 2:
            run_count = base_parts[1]
            version_part = base_parts[0].replace("replay_output_", "")
            base_app = version_part.replace("_", ".")  # 6_3_0 → 6.3.0（可读性）

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
    folder_info = parse_folder_names(replay_name, record_name)
    
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


if __name__ == "__main__":
    main()


# python check_result.py --batch --parent-dir com.byagowi.persiancalendar/ --base-app v6_4_1 --test-mode --parallel --max-workers 10