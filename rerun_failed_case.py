#!/usr/bin/env python3
"""
目前生产的v1版本里面有一些case是由于代码bug导致的failed，需要把现在的v1删除

1.我会有一个csv，里面有需要删除的case，Need_to_rerun.csv，跟Need_to_extend.csv类似,是v1版本里面失败的case
2.你跟check_repair_data.py一样，读取Need_to_rerun.csv，然后读取repair_output目录下的输出
- 有一个文件夹后缀的参数，例如v1，意思是我现在需要把这个v1删除
"""

import os
import sys
import csv
import shutil
import argparse
from typing import Set, Tuple, Dict, List
from collections import defaultdict


def load_rerun_cases(csv_path: str) -> Set[Tuple[str, str, str]]:
    """
    加载需要重新运行的 case 列表

    Args:
        csv_path: Need_to_rerun.csv 文件路径

    Returns:
        Set of (record_app, replay_app, run_count) tuples
    """
    rerun_cases = set()
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV 文件不存在: {csv_path}")
        return rerun_cases

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            record_app = row.get('Record App', '').strip()
            replay_app = row.get('Replay App', '').strip()
            run_count = row.get('Run Count', '').strip()
            if record_app and replay_app and run_count:
                rerun_cases.add((record_app, replay_app, run_count))

    print(f"已从 {csv_path} 加载 {len(rerun_cases)} 个需要重新运行的 case")
    return rerun_cases


def find_and_count_cases(apk_base: str, rerun_cases: Set[Tuple[str, str, str]], suffix: str) -> Dict[str, List[dict]]:
    """
    找到所有需要删除的 case，并按 app 分组统计

    Args:
        apk_base: 数据目录
        rerun_cases: 需要重新运行的 case 集合
        suffix: 后缀（如 v1）

    Returns:
        Dict: {app_name: [case_info]}
    """
    cases_by_app = defaultdict(list)

    for record_app, replay_app, run_count in rerun_cases:
        # 构建带后缀的目录路径
        dir_with_suffix = f"repair_output_{replay_app}_run{run_count}_for_{record_app}{suffix}"
        full_path = os.path.join(apk_base, dir_with_suffix)

        if os.path.exists(full_path):
            # 使用 replay_app 作为 app 分组的 key
            cases_by_app[replay_app].append({
                'record_app': record_app,
                'replay_app': replay_app,
                'run_count': run_count,
                'dir_with_suffix': dir_with_suffix
            })
        else:
            print(f"WARNING: 带后缀的目录不存在: {full_path}")

    return cases_by_app


def print_statistics(cases_by_app: Dict[str, List[dict]]):
    """打印统计信息"""
    print("\n" + "=" * 60)
    print("Case Statistics")
    print("=" * 60)

    total = 0
    for app_name in sorted(cases_by_app.keys()):
        cases = cases_by_app[app_name]
        count = len(cases)
        total += count
        print(f"  {app_name}: {count} 个")

    print("-" * 60)
    print(f"  总计: {total} 个")
    print("=" * 60)

    return total


def delete_failed_cases(apk_base: str, cases_by_app: Dict[str, List[dict]], dry_run: bool = True):
    """
    执行删除操作：删除带后缀的目录

    Args:
        apk_base: 数据目录
        cases_by_app: 按 app 分组的 case 信息
        dry_run: 如果为 True，只打印操作，不实际执行
    """
    print("\n" + "=" * 60)
    if dry_run:
        print("Dry Run Mode (不实际执行，只显示将要执行的操作)")
    else:
        print("Executing Delete Failed Cases")
    print("=" * 60)

    success_count = 0
    error_count = 0

    for app_name in sorted(cases_by_app.keys()):
        cases = cases_by_app[app_name]
        print(f"\n[{app_name}] 删除 {len(cases)} 个 case:")

        for case in cases:
            dir_with_suffix = case['dir_with_suffix']
            path_with_suffix = os.path.join(apk_base, dir_with_suffix)

            try:
                # 删除带后缀的目录
                if os.path.exists(path_with_suffix):
                    if dry_run:
                        print(f"  [DRY] rm -rf {dir_with_suffix}")
                    else:
                        shutil.rmtree(path_with_suffix)
                        print(f"  [DEL] {dir_with_suffix}")
                    success_count += 1
                else:
                    print(f"  [SKIP] 目录不存在: {dir_with_suffix}")

            except Exception as e:
                print(f"  [ERR] {dir_with_suffix}: {e}")
                error_count += 1

    print("\n" + "-" * 60)
    print(f"完成: 成功 {success_count} 个, 失败 {error_count} 个")

    return success_count, error_count


def main():
    parser = argparse.ArgumentParser(description='删除失败的 case 目录，以便重新运行')
    parser.add_argument('--apk-base', required=True, help='数据目录')
    parser.add_argument('--suffix', required=True, help='需要删除的目录后缀（如 v1, _v1）')
    parser.add_argument('--rerun-csv', default='Need_to_rerun.csv',
                        help='需要重新运行的 case 列表文件路径（默认: Need_to_rerun.csv）')
    parser.add_argument('--execute', action='store_true',
                        help='实际执行操作（默认为 dry-run 模式，只显示将要执行的操作）')
    args = parser.parse_args()

    if not os.path.exists(args.apk_base):
        print(f"ERROR: 目录不存在: {args.apk_base}")
        sys.exit(1)

    # 加载需要重新运行的 case
    rerun_cases = load_rerun_cases(args.rerun_csv)
    if not rerun_cases:
        print("没有需要重新运行的 case")
        sys.exit(0)

    # 找到并统计 case
    cases_by_app = find_and_count_cases(args.apk_base, rerun_cases, args.suffix)
    if not cases_by_app:
        print("没有找到任何匹配的目录")
        sys.exit(0)

    # 打印统计信息
    print_statistics(cases_by_app)

    # 执行删除操作
    dry_run = not args.execute
    if dry_run:
        print("\n提示: 这是 dry-run 模式。如果确认要执行，请添加 --execute 参数")

    delete_failed_cases(args.apk_base, cases_by_app, dry_run=dry_run)

    if dry_run:
        print("\n提示: 以上操作未实际执行。确认无误后，请使用 --execute 参数重新运行")


if __name__ == '__main__':
    main()
