#!/usr/bin/env python3
"""
检查 repair_output 目录下的输出是否正常，并生成 repair_report.html

分三种情况（基于 failed_event_number 比较）:
1. repair 目录下的 events 个数 < failed_event_number: 没有到达 failed 的 state，需要删除重新运行
2. repair 目录下的 events 个数 > failed_event_number + 1: 修复成功
3. repair 目录下的 events 个数 == failed_event_number or == failed_event_number + 1: 可能成功也可能失败，需要人工确认

生成的 repair_report.html 在原 matching_report.html 基础上增加三列:
- Repair Events: repair 目录下的 events 个数
- Failed Events: replay 目录下失败的 event 编号
- Repair Result: Success / Failure / Need Check / Not Run
"""

import os
import sys
import glob
import csv
import argparse
import shutil
from typing import Dict, List, Tuple, Set
from bs4 import BeautifulSoup


def load_skip_cases(csv_path: str) -> Set[Tuple[str, str, str]]:
    """
    加载需要跳过的 case 列表

    Args:
        csv_path: Need_to_delete.csv 文件路径

    Returns:
        Set of (record_app, replay_app, run_count) tuples
    """
    skip_cases = set()
    if not os.path.exists(csv_path):
        print(f"WARNING: CSV 文件不存在: {csv_path}")
        return skip_cases

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            record_app = row.get('Record App', '').strip()
            replay_app = row.get('Replay App', '').strip()
            run_count = row.get('Run Count', '').strip()
            if record_app and replay_app and run_count:
                skip_cases.add((record_app, replay_app, run_count))

    print(f"已加载 {len(skip_cases)} 个需要跳过的 case")
    return skip_cases


def should_skip_case(record_app: str, replay_app: str, run_count: str,
                     skip_cases: Set[Tuple[str, str, str]]) -> bool:
    """检查是否应该跳过这个 case"""
    return (record_app, replay_app, run_count) in skip_cases


def get_failed_event_number(replay_output_dir: str) -> int:
    """
    从 replay_output 目录解析 failed_event_number
    通过查找 events 目录下最大的 event 编号来确定
    """
    events_dir = os.path.join(replay_output_dir, 'events')
    if not os.path.exists(events_dir):
        return -1

    # 查找所有 event_*.json 文件
    event_files = glob.glob(os.path.join(events_dir, 'event_*.json'))
    if not event_files:
        return -1

    # 提取最大的 event 编号
    max_event = 0
    for f in event_files:
        basename = os.path.basename(f)
        try:
            num = int(basename.replace('event_', '').replace('.json', ''))
            max_event = max(max_event, num)
        except ValueError:
            continue

    return max_event


def count_repair_events(repair_output_dir: str) -> int:
    """统计 repair 目录下的 events 个数"""
    events_dir = os.path.join(repair_output_dir, 'events')
    if not os.path.exists(events_dir):
        return -1  # -1 表示目录不存在

    event_files = glob.glob(os.path.join(events_dir, 'event_*.json'))
    return len(event_files)


def get_repair_result(repair_events: int, failed_events: int) -> str:
    """
    根据 repair_events 和 failed_events 判断修复结果
    """
    if repair_events < 0:
        return "Not Run"
    elif repair_events < failed_events:
        return "Failure"  # 未到达 failed state
    elif repair_events > failed_events + 1:
        return "Success"
    else:
        return "Need Check"


def generate_repair_report(apk_base: str, skip_cases: Set[Tuple[str, str, str]] = None,
                           repair_suffix: str = '') -> Tuple[str, Dict]:
    """
    读取 matching_report.html，添加 repair 结果列，生成 repair_report.html

    Args:
        apk_base: 数据目录
        skip_cases: 需要跳过的 case 集合
        repair_suffix: repair 输出目录后缀

    Returns:
        Tuple of (output_path, statistics)
    """
    if skip_cases is None:
        skip_cases = set()
    html_report = os.path.join(apk_base, 'html_report', 'matching_report.html')
    output_report = os.path.join(apk_base, 'html_report', 'repair_report.html')

    if not os.path.exists(html_report):
        print(f"ERROR: HTML 报告不存在: {html_report}")
        return None, {}

    # 读取原始 HTML
    with open(html_report, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    # 统计数据
    stats = {
        'success': 0,
        'failure': 0,
        'need_check': 0,
        'not_run': 0,
        'skipped': 0,
        'total': 0
    }

    # 找到表格
    table = soup.find('table')
    if not table:
        print("ERROR: 未找到表格")
        return None, {}

    # 处理表头 - 添加三列
    header_row = table.find('tr')
    if header_row:
        # 添加三个新表头
        for col_name in ['Repair Events', 'Failed Events', 'Repair Result']:
            new_th = soup.new_tag('th')
            new_th.string = col_name
            header_row.append(new_th)

    # 处理每一行数据
    rows = table.find_all('tr')[1:]  # 跳过表头
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 5:
            continue

        record_app = cells[0].get_text(strip=True)
        replay_app = cells[1].get_text(strip=True)
        run_count = cells[2].get_text(strip=True)

        # 检查是否需要跳过
        if should_skip_case(record_app, replay_app, run_count, skip_cases):
            repair_result = "Skipped"
            repair_events = -1
            failed_events = -1
            stats['total'] += 1
            stats['skipped'] += 1
        else:
            # 构建目录路径
            replay_dir = os.path.join(apk_base, f"replay_output_{replay_app}_run{run_count}_for_{record_app}")
            repair_dir = os.path.join(apk_base, f"repair_output_{replay_app}_run{run_count}_for_{record_app}{repair_suffix}")

            # 获取数据
            failed_events = get_failed_event_number(replay_dir)
            repair_events = count_repair_events(repair_dir)
            repair_result = get_repair_result(repair_events, failed_events)

            # 统计
            stats['total'] += 1
            if repair_result == 'Success':
                stats['success'] += 1
            elif repair_result == 'Failure':
                stats['failure'] += 1
            elif repair_result == 'Need Check':
                stats['need_check'] += 1
            else:
                stats['not_run'] += 1

        # 添加三个新单元格
        # Repair Events
        td_repair = soup.new_tag('td')
        td_repair.string = str(repair_events) if repair_events >= 0 else '-'
        row.append(td_repair)

        # Failed Events
        td_failed = soup.new_tag('td')
        td_failed.string = str(failed_events) if failed_events >= 0 else '-'
        row.append(td_failed)

        # Repair Result (with color)
        td_result = soup.new_tag('td')
        td_result.string = repair_result
        if repair_result == 'Success':
            td_result['style'] = 'color: green; font-weight: bold;'
        elif repair_result == 'Failure':
            td_result['style'] = 'color: red; font-weight: bold;'
        elif repair_result == 'Need Check':
            td_result['style'] = 'color: orange; font-weight: bold;'
        elif repair_result == 'Skipped':
            td_result['style'] = 'color: purple; font-weight: bold;'
        else:
            td_result['style'] = 'color: gray;'
        row.append(td_result)

    # 更新页面标题
    title = soup.find('title')
    if title:
        title.string = 'Repair Report'

    h1 = soup.find('h1')
    if h1:
        h1.string = 'Repair Report'

    # 添加统计摘要
    summary_div = soup.new_tag('div')
    summary_div['style'] = 'margin: 20px 0; padding: 15px; background: #f5f5f5; border-radius: 5px;'
    summary_html = f'''
    <h3>Repair Statistics</h3>
    <p><strong>Total:</strong> {stats['total']}</p>
    <p><span style="color: green;">✓ Success:</span> {stats['success']}</p>
    <p><span style="color: red;">✗ Failure:</span> {stats['failure']}</p>
    <p><span style="color: orange;">? Need Check:</span> {stats['need_check']}</p>
    <p><span style="color: gray;">- Not Run:</span> {stats['not_run']}</p>
    <p><span style="color: purple;">⊘ Skipped:</span> {stats['skipped']}</p>
    '''
    summary_div.append(BeautifulSoup(summary_html, 'html.parser'))

    # 插入到表格前面
    if table:
        table.insert_before(summary_div)

    # 保存新 HTML
    with open(output_report, 'w', encoding='utf-8') as f:
        f.write(str(soup))

    print(f"已生成报告: {output_report}")
    return output_report, stats


def check_repair_status(apk_base: str, skip_cases: Set[Tuple[str, str, str]] = None,
                        repair_suffix: str = '') -> Dict[str, List[str]]:
    """
    检查 HTML report 中记录的用例的 repair 状态（用于命令行输出）
    只检查 matching_report.html 里面的用例

    Args:
        apk_base: 数据目录
        skip_cases: 需要跳过的 case 集合
        repair_suffix: repair 输出目录后缀
    """
    if skip_cases is None:
        skip_cases = set()

    results = {
        'not_reached': [],
        'success': [],
        'need_check': [],
        'not_run': [],
        'skipped': []
    }

    # 从 HTML report 读取用例列表
    html_report = os.path.join(apk_base, 'html_report', 'matching_report.html')
    if not os.path.exists(html_report):
        return results

    with open(html_report, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    table = soup.find('table')
    if not table:
        return results

    rows = table.find_all('tr')[1:]  # 跳过表头
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 5:
            continue

        record_app = cells[0].get_text(strip=True)
        replay_app = cells[1].get_text(strip=True)
        run_count = cells[2].get_text(strip=True)

        # 检查是否需要跳过
        if should_skip_case(record_app, replay_app, run_count, skip_cases):
            repair_dir_name = f"repair_output_{replay_app}_run{run_count}_for_{record_app}{repair_suffix}"
            results['skipped'].append(f"{repair_dir_name}: skipped by Need_to_delete.csv")
            continue

        # 构建目录路径
        replay_dir = os.path.join(apk_base, f"replay_output_{replay_app}_run{run_count}_for_{record_app}")
        repair_dir = os.path.join(apk_base, f"repair_output_{replay_app}_run{run_count}_for_{record_app}{repair_suffix}")
        repair_dir_name = os.path.basename(repair_dir)

        failed_event_num = get_failed_event_number(replay_dir)
        if failed_event_num < 0:
            continue  # replay 没有失败，不需要 repair

        repair_events = count_repair_events(repair_dir)

        if repair_events < 0:
            # repair 目录不存在
            results['not_run'].append(f"{repair_dir_name}: failed_event={failed_event_num}")
            continue

        info = f"{repair_dir_name}: repair_events={repair_events}, failed_event={failed_event_num}"

        if repair_events < failed_event_num:
            results['not_reached'].append(info)
        elif repair_events > failed_event_num + 1:
            results['success'].append(info)
        else:
            results['need_check'].append(info)

    return results


def generate_detail_repair_reports(apk_base: str, simple: bool = True,
                                   skip_cases: Set[Tuple[str, str, str]] = None,
                                   repair_suffix: str = '') -> List[str]:
    """
    为 matching_report.html 中的每个 case 生成详细的 repair HTML 报告

    Args:
        apk_base: 数据目录
        simple: 是否使用 simple 模式（只显示 failed_event 前后的内容）
        skip_cases: 需要跳过的 case 集合
        repair_suffix: repair 输出目录后缀

    Returns:
        生成的 HTML 文件路径列表
    """
    from droidbot.utils import generate_html_report_with_repair

    if skip_cases is None:
        skip_cases = set()

    html_report = os.path.join(apk_base, 'html_report', 'matching_report.html')
    output_dir = os.path.join(apk_base, 'html_report')

    if not os.path.exists(html_report):
        print(f"ERROR: HTML 报告不存在: {html_report}")
        return []

    # 读取原始 HTML
    with open(html_report, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    table = soup.find('table')
    if not table:
        print("ERROR: 未找到表格")
        return []

    generated_files = []
    rows = table.find_all('tr')[1:]  # 跳过表头

    for idx, row in enumerate(rows, 1):
        cells = row.find_all('td')
        if len(cells) < 5:
            continue

        record_app = cells[0].get_text(strip=True)
        replay_app = cells[1].get_text(strip=True)
        run_count = cells[2].get_text(strip=True)

        # 检查是否需要跳过
        if should_skip_case(record_app, replay_app, run_count, skip_cases):
            print(f"  [{idx}] SKIP: 在 Need_to_delete.csv 中 - {record_app} <- {replay_app} run{run_count}")
            continue

        # 构建目录路径
        record_dir = os.path.join(apk_base, f"record_output_{record_app}_run{run_count}")
        replay_dir = os.path.join(apk_base, f"replay_output_{replay_app}_run{run_count}_for_{record_app}")
        repair_dir = os.path.join(apk_base, f"repair_output_{replay_app}_run{run_count}_for_{record_app}{repair_suffix}")

        # 检查目录是否存在
        if not os.path.exists(record_dir):
            print(f"  [{idx}] SKIP: record_dir 不存在: {record_dir}")
            continue
        if not os.path.exists(replay_dir):
            print(f"  [{idx}] SKIP: replay_dir 不存在: {replay_dir}")
            continue
        if not os.path.exists(repair_dir):
            print(f"  [{idx}] SKIP: repair_dir 不存在: {repair_dir}")
            continue

        # 检查 repair 目录下是否有 exploration_tmp
        exploration_tmp = os.path.join(repair_dir, 'exploration_tmp')
        if not os.path.exists(exploration_tmp):
            print(f"  [{idx}] SKIP: exploration_tmp 不存在: {exploration_tmp}")
            continue

        # 生成输出目录（每个 case 单独一个子目录存放图片）
        case_output_dir = os.path.join(output_dir, f"repair_{idx}")
        os.makedirs(case_output_dir, exist_ok=True)

        print(f"  [{idx}] Generating: {record_app} <- {replay_app} run{run_count}")

        try:
            # 调用 utils 里的方法生成 HTML
            generate_html_report_with_repair(
                record_dir=record_dir,
                replay_dir=replay_dir,
                repair_dir=repair_dir,
                out_dir=case_output_dir,
                simple=simple
            )

            # 重命名生成的 HTML 文件
            src_html = os.path.join(case_output_dir, 'action_comparison_report.html')
            dst_html = os.path.join(output_dir, f'repair_{idx}.html')

            if os.path.exists(src_html):
                # 读取 HTML，修改图片路径（从 tmp/ 改为 repair_{idx}/tmp/）
                with open(src_html, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                html_content = html_content.replace('src="tmp/', f'src="repair_{idx}/tmp/')
                with open(dst_html, 'w', encoding='utf-8') as f:
                    f.write(html_content)

                generated_files.append(dst_html)
                print(f"       -> {dst_html}")

        except Exception as e:
            print(f"  [{idx}] ERROR: {e}")
            import traceback
            traceback.print_exc()

    return generated_files


def main():
    parser = argparse.ArgumentParser(description='检查 repair_output 目录的修复状态并生成报告')
    parser.add_argument('--apk-base', required=True, help='数据目录')
    parser.add_argument('--delete-not-reached', action='store_true',
                        help='删除未到达 failed state 的 repair 目录')
    parser.add_argument('--delete-no-run', action='store_true',
                        help='删除 Not Run 类别的空目录（模拟器掉线导致的空文件夹）')
    parser.add_argument('--no-html', action='store_true',
                        help='不生成 HTML 报告，只输出命令行结果')
    parser.add_argument('--detail', action='store_true',
                        help='为每个 case 生成详细的 repair HTML 报告 (repair_1.html, repair_2.html, ...)')
    parser.add_argument('--no-simple', action='store_true',
                        help='生成详细报告时不使用 simple 模式（显示所有 events）')
    parser.add_argument('--skip-delete-cases', action='store_true',
                        help='跳过 Need_to_delete.csv 中列出的 case')
    parser.add_argument('--delete-csv', default='Need_to_delete.csv',
                        help='需要删除的 case 列表文件路径（默认: Need_to_delete.csv）')
    parser.add_argument('--repair-output-dir-suffix', default='',
                        help='repair 输出目录后缀，直接拼接在目录名后面（默认: 空）')
    args = parser.parse_args()

    if not os.path.exists(args.apk_base):
        print(f"ERROR: 目录不存在: {args.apk_base}")
        sys.exit(1)

    # 加载需要跳过的 case
    skip_cases = set()
    if args.skip_delete_cases:
        skip_cases = load_skip_cases(args.delete_csv)

    # 生成 HTML 报告
    if not args.no_html:
        output_path, stats = generate_repair_report(args.apk_base, skip_cases, args.repair_output_dir_suffix)
        if stats:
            print("\n" + "=" * 60)
            print("Repair Statistics")
            print("=" * 60)
            print(f"Total: {stats['total']}")
            print(f"Success: {stats['success']}")
            print(f"Failure: {stats['failure']}")
            print(f"Need Check: {stats['need_check']}")
            print(f"Not Run: {stats['not_run']}")
            print(f"Skipped: {stats['skipped']}")
            print("=" * 60)

    # 命令行详细输出
    results = check_repair_status(args.apk_base, skip_cases, args.repair_output_dir_suffix)

    print(f"\n【情况1】未到达 failed state (Failure): {len(results['not_reached'])} 个")
    for item in results['not_reached']:
        print(f"    - {item}")

    print(f"\n【情况2】修复成功 (Success): {len(results['success'])} 个")
    for item in results['success']:
        print(f"    - {item}")

    print(f"\n【情况3】需要人工确认 (Need Check): {len(results['need_check'])} 个")
    for item in results['need_check']:
        print(f"    - {item}")

    print(f"\n【情况4】未运行 (Not Run): {len(results['not_run'])} 个")
    for item in results['not_run']:
        print(f"    - {item}")

    print(f"\n【情况5】已跳过 (Skipped): {len(results['skipped'])} 个")
    for item in results['skipped']:
        print(f"    - {item}")

    # 删除选项
    if args.delete_not_reached and results['not_reached']:
        print("\n正在删除未到达 failed state 的目录...")
        for item in results['not_reached']:
            dir_name = item.split(':')[0]
            dir_path = os.path.join(args.apk_base, dir_name)
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path)
                print(f"  已删除: {dir_name}")
        print("删除完成")

    # 删除 Not Run 空目录
    if args.delete_no_run and results['not_run']:
        print("\n正在删除 Not Run 空目录（模拟器掉线导致）...")
        for item in results['not_run']:
            dir_name = item.split(':')[0]
            dir_path = os.path.join(args.apk_base, dir_name)
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path)
                print(f"  已删除: {dir_name}")
        print("删除完成")

    # 生成详细的 repair HTML 报告
    if args.detail:
        print("\n" + "=" * 60)
        print("Generating Detail Repair Reports")
        print("=" * 60)
        simple_mode = not args.no_simple
        generated = generate_detail_repair_reports(args.apk_base, simple=simple_mode, skip_cases=skip_cases,
                                                   repair_suffix=args.repair_output_dir_suffix)
        print(f"\n生成了 {len(generated)} 个详细报告")


if __name__ == '__main__':
    main()
