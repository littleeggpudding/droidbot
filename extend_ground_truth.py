#!/usr/bin/env python3
"""
目前生产的v1版本里面有一些case是成功的，之前是没有成功的，需要把原来的删除，把现在的v1改成之前的名称

1.我会有一个csv，里面有需要替换的case，Need_to_extend.csv，跟Need_to_delete.csv类似，但是是v1版本里面成功的case
2.你跟check_repair_data.py一样，读取Need_to_extend.csv，然后读取repair_output目录下的输出
- 有一个文件夹后缀的参数，例如v1，意思是我现在需要把这个v1里面的，改成之前没有后缀的，因为ground truth的文件夹是没有后缀的
- 首先，找到这些v1，输出每一个app有多少个，一共有多少个
- 然后rm -rf删除以前没有后缀的
- 然后把现在v1的重命名为没有后缀的
"""

import os
import sys
import csv
import shutil
import argparse
from typing import Set, Tuple, Dict, List
from collections import defaultdict


def load_extend_cases(csv_path: str) -> Set[Tuple[str, str, str]]:
    """
    加载需要扩展的 case 列表

    Args:
        csv_path: Need_to_extend.csv 文件路径

    Returns:
        Set of (record_app, replay_app, run_count) tuples
    """
    extend_cases = set()
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV 文件不存在: {csv_path}")
        return extend_cases

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            record_app = row.get('Record App', '').strip()
            replay_app = row.get('Replay App', '').strip()
            run_count = row.get('Run Count', '').strip()
            if record_app and replay_app and run_count:
                extend_cases.add((record_app, replay_app, run_count))

    print(f"已从 {csv_path} 加载 {len(extend_cases)} 个需要扩展的 case")
    return extend_cases


def find_and_count_cases(apk_base: str, extend_cases: Set[Tuple[str, str, str]], suffix: str) -> Dict[str, List[str]]:
    """
    找到所有需要扩展的 case，并按 app 分组统计

    Args:
        apk_base: 数据目录
        extend_cases: 需要扩展的 case 集合
        suffix: 后缀（如 v1）

    Returns:
        Dict: {app_name: [case_dir_names]}
    """
    cases_by_app = defaultdict(list)

    for record_app, replay_app, run_count in extend_cases:
        # 构建带后缀的目录路径
        dir_with_suffix = f"repair_output_{replay_app}_run{run_count}_for_{record_app}{suffix}"
        full_path = os.path.join(apk_base, dir_with_suffix)

        if os.path.exists(full_path):
            # 使用 replay_app 作为 app 分组的 key
            cases_by_app[replay_app].append({
                'record_app': record_app,
                'replay_app': replay_app,
                'run_count': run_count,
                'dir_with_suffix': dir_with_suffix,
                'dir_without_suffix': f"repair_output_{replay_app}_run{run_count}_for_{record_app}"
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


def extend_ground_truth(apk_base: str, cases_by_app: Dict[str, List[dict]], dry_run: bool = True):
    """
    执行扩展操作：删除旧目录，重命名新目录

    Args:
        apk_base: 数据目录
        cases_by_app: 按 app 分组的 case 信息
        dry_run: 如果为 True，只打印操作，不实际执行
    """
    print("\n" + "=" * 60)
    if dry_run:
        print("Dry Run Mode (不实际执行，只显示将要执行的操作)")
    else:
        print("Executing Ground Truth Extension")
    print("=" * 60)

    success_count = 0
    error_count = 0

    for app_name in sorted(cases_by_app.keys()):
        cases = cases_by_app[app_name]
        print(f"\n[{app_name}] 处理 {len(cases)} 个 case:")

        for case in cases:
            dir_with_suffix = case['dir_with_suffix']
            dir_without_suffix = case['dir_without_suffix']

            path_with_suffix = os.path.join(apk_base, dir_with_suffix)
            path_without_suffix = os.path.join(apk_base, dir_without_suffix)

            try:
                # Step 1: 删除旧的没有后缀的目录（如果存在）
                if os.path.exists(path_without_suffix):
                    if dry_run:
                        print(f"  [DRY] rm -rf {dir_without_suffix}")
                    else:
                        shutil.rmtree(path_without_suffix)
                        print(f"  [DEL] {dir_without_suffix}")

                # Step 2: 重命名带后缀的目录为没有后缀的
                if dry_run:
                    print(f"  [DRY] mv {dir_with_suffix} -> {dir_without_suffix}")
                else:
                    os.rename(path_with_suffix, path_without_suffix)
                    print(f"  [MV]  {dir_with_suffix} -> {dir_without_suffix}")

                success_count += 1

            except Exception as e:
                print(f"  [ERR] {dir_with_suffix}: {e}")
                error_count += 1

    print("\n" + "-" * 60)
    print(f"完成: 成功 {success_count} 个, 失败 {error_count} 个")

    return success_count, error_count


def main():
    parser = argparse.ArgumentParser(description='扩展 ground truth：用新版本的成功 case 替换旧版本')
    parser.add_argument('--apk-base', required=True, help='数据目录')
    parser.add_argument('--suffix', required=True, help='新版本的后缀（如 v1, _v1）')
    parser.add_argument('--extend-csv', default='Need_to_extend.csv',
                        help='需要扩展的 case 列表文件路径（默认: Need_to_extend.csv）')
    parser.add_argument('--execute', action='store_true',
                        help='实际执行操作（默认为 dry-run 模式，只显示将要执行的操作）')
    args = parser.parse_args()

    if not os.path.exists(args.apk_base):
        print(f"ERROR: 目录不存在: {args.apk_base}")
        sys.exit(1)

    # 加载需要扩展的 case
    extend_cases = load_extend_cases(args.extend_csv)
    if not extend_cases:
        print("没有需要扩展的 case")
        sys.exit(0)

    # 找到并统计 case
    cases_by_app = find_and_count_cases(args.apk_base, extend_cases, args.suffix)
    if not cases_by_app:
        print("没有找到任何匹配的目录")
        sys.exit(0)

    # 打印统计信息
    print_statistics(cases_by_app)

    # 执行扩展操作
    dry_run = not args.execute
    if dry_run:
        print("\n提示: 这是 dry-run 模式。如果确认要执行，请添加 --execute 参数")

    extend_ground_truth(args.apk_base, cases_by_app, dry_run=dry_run)

    if dry_run:
        print("\n提示: 以上操作未实际执行。确认无误后，请使用 --execute 参数重新运行")


if __name__ == '__main__':
    main()
