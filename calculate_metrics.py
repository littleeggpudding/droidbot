"""
根据 ground truth, 统计正确率

Ground Truth:
- repair_output 后面没有后缀的

New method for comparison:
- repair_output 后面有后缀的（e.g. _v1）

比较的方法：
1. 读取matching_report.html，获取Case编号，Replay App，Record App，Run Count
2. 通过Need_to_delete.csv，获取需要跳过的case
3. 遍历repair_output，获取repair_output 后面没有后缀的和有后缀的
4. 比较两个repair_output，统计正确率
- 判断的依据是：
 -failed_event里面我们exploration里面的matched_view和ground truth的matched_view是否一致
 - 并且下一个event里面的matched_view和ground truth的matched_view是否一致
 - matched_view的判断依据是：
 （1）
   - 四个属性： id, class, text, contentDescription + Activity Name
   - 如果四个属性跟Activity Name都一致，则认为matched_view一致
  （2）
   - 四个属性： id, class, contentDescription, bounds + Activity Name
   - 如果四个属性跟Activity Name都一致，则认为matched_view一致

"""

import os
import sys
import json
import glob
import csv
import argparse
from typing import Dict, List, Tuple, Set, Optional
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

    print(f"已从 {csv_path} 加载 {len(skip_cases)} 个需要跳过的 case")
    return skip_cases


def should_skip_case(record_app: str, replay_app: str, run_count: str,
                     skip_cases: Set[Tuple[str, str, str]]) -> bool:
    """检查是否应该跳过这个 case"""
    return (record_app, replay_app, run_count) in skip_cases


def parse_matching_report(html_report_path: str) -> List[Dict]:
    """
    解析 matching_report.html，获取所有 case 信息

    Returns:
        List of dicts with keys: idx, record_app, replay_app, run_count, result, method
    """
    if not os.path.exists(html_report_path):
        print(f"ERROR: HTML 报告不存在: {html_report_path}")
        return []

    with open(html_report_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    # 找到 summary 表格
    summary_div = soup.find('div', class_='summary')
    if not summary_div:
        # 尝试直接找 table
        table = soup.find('table')
    else:
        table = summary_div.find('table')

    if not table:
        print("ERROR: 未找到表格")
        return []

    rows = table.find_all('tr')[1:]  # 跳过表头
    cases = []

    for idx, row in enumerate(rows, 1):
        cells = row.find_all('td')
        if len(cells) < 5:
            continue

        record_app = cells[0].get_text(strip=True)
        replay_app = cells[1].get_text(strip=True)
        run_count = cells[2].get_text(strip=True)
        result = cells[3].get_text(strip=True)
        method = cells[4].get_text(strip=True)

        cases.append({
            'idx': idx,
            'record_app': record_app,
            'replay_app': replay_app,
            'run_count': run_count,
            'result': result,
            'method': method
        })

    print(f"从 HTML 报告中解析到 {len(cases)} 个 case")
    return cases


def calculate_iou(bounds1, bounds2) -> float:
    """
    计算两个 bounds 的 IoU（交并比）

    Args:
        bounds1: [[left, top], [right, bottom]]
        bounds2: [[left, top], [right, bottom]]

    Returns:
        IoU 值 (0.0 ~ 1.0)
    """
    if not bounds1 or not bounds2:
        return 0.0

    try:
        # 解析 bounds
        x1_min, y1_min = bounds1[0]
        x1_max, y1_max = bounds1[1]
        x2_min, y2_min = bounds2[0]
        x2_max, y2_max = bounds2[1]

        # 计算交集
        inter_x_min = max(x1_min, x2_min)
        inter_y_min = max(y1_min, y2_min)
        inter_x_max = min(x1_max, x2_max)
        inter_y_max = min(y1_max, y2_max)

        # 检查是否有交集
        if inter_x_max <= inter_x_min or inter_y_max <= inter_y_min:
            return 0.0

        inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)

        # 计算并集
        area1 = (x1_max - x1_min) * (y1_max - y1_min)
        area2 = (x2_max - x2_min) * (y2_max - y2_min)
        union_area = area1 + area2 - inter_area

        if union_area <= 0:
            return 0.0

        return inter_area / union_area
    except (TypeError, IndexError):
        return 0.0


def bounds_match(bounds1, bounds2, iou_threshold: float = 0.8) -> bool:
    """
    检查两个 bounds 是否匹配：左上角坐标相同 + IoU > 阈值

    Args:
        bounds1: [[left, top], [right, bottom]]
        bounds2: [[left, top], [right, bottom]]
        iou_threshold: IoU 阈值，默认 0.8

    Returns:
        True if bounds match
    """
    if not bounds1 or not bounds2:
        return False

    try:
        # 检查左上角坐标是否相同
        if bounds1[0] != bounds2[0]:
            return False

        # 计算 IoU
        iou = calculate_iou(bounds1, bounds2)
        return iou > iou_threshold
    except (TypeError, IndexError):
        return False


def get_matched_view_keys(view: Optional[Dict], activity: Optional[str] = None) -> Tuple[Optional[Tuple], Optional[Tuple]]:
    """
    从 matched_view 中提取用于比较的 key（两种比较方式）

    比较依据1: resource_id, class, text, content_description + activity_name
    比较依据2: resource_id, class, content_description, bounds + activity_name（bounds 使用模糊匹配）

    Returns:
        Tuple of (key1, key2) where:
        - key1: (resource_id, class, text, content_description, activity)
        - key2: (resource_id, class, content_description, bounds, activity)
    """
    if view is None:
        return None, None

    # 条件1: id, class, text, contentDescription + Activity
    key1 = (
        view.get('resource_id'),
        view.get('class'),
        view.get('text'),
        view.get('content_description'),
        activity
    )

    # 条件2: id, class, contentDescription, bounds + Activity
    key2 = (
        view.get('resource_id'),
        view.get('class'),
        view.get('content_description'),
        view.get('bounds'),
        activity
    )

    return key1, key2


def matched_view_equal(gt_keys: Tuple, new_keys: Tuple, skip_activity: bool = False) -> bool:
    """
    比较两个 view 是否一致（满足任一条件即可）

    条件1: id, class, text, contentDescription + Activity 完全一致
    条件2: id, class, contentDescription + Activity 完全一致，且 bounds 左上角相同 + IoU > 0.8

    Args:
        gt_keys: (key1, key2) from ground truth
        new_keys: (key1, key2) from new method
        skip_activity: 是否跳过 activity 比较

    Returns:
        True if any comparison matches
    """
    gt_key1, gt_key2 = gt_keys
    new_key1, new_key2 = new_keys

    print(f"gt_key1: {gt_key1}")
    print(f"new_key1: {new_key1}")
    print(f"gt_key2: {gt_key2}")
    print(f"new_key2: {new_key2}")
    print(f"skip_activity: {skip_activity}")

    # 条件1: text 方式完全匹配
    if gt_key1 and new_key1:
        # key1 格式: (resource_id, class, text, content_description, activity)
        if skip_activity:
            # 比较除了 activity 以外的属性
            if gt_key1[:4] == new_key1[:4]:
                return True
        else:
            if gt_key1 == new_key1:
                return True

    # 条件2: bounds 方式模糊匹配
    if gt_key2 and new_key2:
        # key2 格式: (resource_id, class, content_description, bounds, activity)
        # 比较除了 bounds 以外的属性
        if skip_activity:
            # 不比较 activity，只比较 id, class, desc
            gt_without_bounds = (gt_key2[0], gt_key2[1], gt_key2[2])
            new_without_bounds = (new_key2[0], new_key2[1], new_key2[2])
        else:
            gt_without_bounds = (gt_key2[0], gt_key2[1], gt_key2[2], gt_key2[4])  # id, class, desc, activity
            new_without_bounds = (new_key2[0], new_key2[1], new_key2[2], new_key2[4])

        if gt_without_bounds == new_without_bounds:
            # 属性匹配，检查 bounds
            gt_bounds = gt_key2[3]
            new_bounds = new_key2[3]
            if bounds_match(gt_bounds, new_bounds, iou_threshold=0.8):
                return True

    return False


def get_activity_from_state(repair_dir: str) -> Optional[str]:
    """
    从 state_same_page_*.json 中编号最大的文件读取 foreground_activity

    因为 match_found 之后 repair 就结束了，所以最后一个 state 文件就是 match_found 时的状态

    Args:
        repair_dir: repair 输出目录

    Returns:
        foreground_activity 或 None
    """
    states_dir = os.path.join(repair_dir, 'exploration_tmp', 'states')

    if not os.path.exists(states_dir):
        return None

    # 找到编号最大的 state_same_page_*.json
    state_files = glob.glob(os.path.join(states_dir, 'state_same_page_*.json'))
    if not state_files:
        return None

    max_num = -1
    max_file = None
    for f in state_files:
        basename = os.path.basename(f)
        # state_same_page_0.json -> 0
        try:
            num = int(basename.replace('state_same_page_', '').replace('.json', ''))
            if num > max_num:
                max_num = num
                max_file = f
        except ValueError:
            continue

    if max_file is None:
        return None

    try:
        with open(max_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
            return state.get('foreground_activity')
    except Exception as e:
        print(f"  ERROR loading {max_file}: {e}")
        return None


def load_repair_trace(repair_dir: str, verbose: bool = False) -> Optional[Dict]:
    """
    加载 repair_trace_event_*.json (每个目录只有一个)

    Returns:
        repair trace dict or None
    """
    repair_logs_dir = os.path.join(repair_dir, 'exploration_tmp', 'repair_logs')

    if not os.path.exists(repair_dir):
        if verbose:
            print(f"    DEBUG: repair_dir 不存在: {repair_dir}")
        return None

    if not os.path.exists(os.path.join(repair_dir, 'exploration_tmp')):
        if verbose:
            print(f"    DEBUG: exploration_tmp 不存在")
        return None

    if not os.path.exists(repair_logs_dir):
        if verbose:
            print(f"    DEBUG: repair_logs 不存在")
        return None

    # 查找 repair_trace_event_*.json 文件
    trace_files = glob.glob(os.path.join(repair_logs_dir, 'repair_trace_event_*.json'))
    if not trace_files:
        if verbose:
            print(f"    DEBUG: 没有找到 repair_trace_event_*.json 文件")
        return None

    # 只取第一个（每个目录只有一个）
    trace_path = trace_files[0]

    try:
        with open(trace_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ERROR loading {trace_path}: {e}")
        return None


def get_next_event_info(repair_dir: str, failed_event_number: int) -> Tuple[Optional[Dict], Optional[str]]:
    """
    从 repair_output/events/ 和 repair_output/states/ 获取下一个 event 的 view 和 activity

    Args:
        repair_dir: repair 输出目录
        failed_event_number: failed event 编号

    Returns:
        Tuple of (view_dict, activity_str) or (None, None)
    """
    next_event_num = failed_event_number + 1

    print(f"next_event_num: {next_event_num}")

    # 读取下一个 event 的 view
    event_path = os.path.join(repair_dir, 'events', f'event_{next_event_num}.json')
    if not os.path.exists(event_path):
        return None, None

    try:
        with open(event_path, 'r', encoding='utf-8') as f:
            event_data = json.load(f)
            view = event_data.get('event', {}).get('view')
    except Exception as e:
        print(f"  ERROR loading {event_path}: {e}")
        return None, None

    # 读取对应 state 的 activity
    # state_N.json 对应 event_N 执行后的状态
    state_path = os.path.join(repair_dir, 'states', f'state_{next_event_num}.json')
    activity = None
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
                activity = state_data.get('foreground_activity')
        except Exception as e:
            print(f"  ERROR loading {state_path}: {e}")

    return view, activity


def compare_next_result(
    gt_repair_dir: str,
    new_repair_dir: str,
    failed_event_number: int,
    skip_activity: bool = False
) -> Dict:
    """
    比较下一个 event (failed_event + 1) 的 view 和 activity

    Args:
        gt_repair_dir: ground truth repair 目录
        new_repair_dir: 新方法 repair 目录
        failed_event_number: failed event 编号

    Returns:
        Dict with comparison results
    """
    # 获取 ground truth 的下一个 event 信息
    gt_view, gt_activity = get_next_event_info(gt_repair_dir, failed_event_number)

    # 获取新方法的下一个 event 信息
    new_view, new_activity = get_next_event_info(new_repair_dir, failed_event_number)

    # 生成比较 key（两种方式）
    gt_keys = get_matched_view_keys(gt_view, gt_activity)
    new_keys = get_matched_view_keys(new_view, new_activity)

    # 如果没有 next event，默认为 True（无法比较时认为一致）
    if gt_view is not None and new_view is not None:
        next_event_same = matched_view_equal(gt_keys, new_keys, skip_activity=skip_activity)
    else:
        next_event_same = True  # 没有 next event 时默认为 True

    result = {
        'next_event_same': next_event_same,
        'gt_next_view': gt_keys[0],  # 保存 key1 用于显示
        'new_next_view': new_keys[0],
        'gt_next_activity': gt_activity,
        'new_next_activity': new_activity,
        'gt_has_next': gt_view is not None,
        'new_has_next': new_view is not None
    }

    return result


def compare_repair_results(
    ground_truth_trace: Dict,
    new_method_trace: Dict,
    gt_repair_dir: str,
    new_repair_dir: str,
    skip_activity: bool = False
) -> Dict:
    """
    比较两个 repair trace 的结果

    Args:
        ground_truth_trace: ground truth 的 repair trace
        new_method_trace: 新方法的 repair trace
        gt_repair_dir: ground truth repair 目录（用于读取 state 文件获取 activity）
        new_repair_dir: 新方法 repair 目录

    Returns:
        Dict with comparison results
    """
    result = {
        'gt_success': ground_truth_trace.get('repair_success', False),
        'new_success': new_method_trace.get('repair_success', False),
        'gt_steps': ground_truth_trace.get('total_steps', 0),
        'new_steps': new_method_trace.get('total_steps', 0),
        'matched_view_same': False,
        'details': []
    }

    gt_trace = ground_truth_trace.get('trace', [])
    new_trace = new_method_trace.get('trace', [])

    # 找到 match_found 的 matched_view
    gt_match_view = None
    new_match_view = None

    for step_data in gt_trace:
        if step_data.get('action') == 'match_found' and step_data.get('matched_view'):
            gt_match_view = step_data.get('matched_view')
            break

    for step_data in new_trace:
        if step_data.get('action') == 'match_found' and step_data.get('matched_view'):
            new_match_view = step_data.get('matched_view')
            break

    # 获取 activity_name（从编号最大的 state_same_page_*.json 读取）
    gt_activity = get_activity_from_state(gt_repair_dir)
    new_activity = get_activity_from_state(new_repair_dir)

    # 生成比较 key（两种方式）
    gt_keys = get_matched_view_keys(gt_match_view, gt_activity)
    new_keys = get_matched_view_keys(new_match_view, new_activity)

    # 满足任一条件即认为一致
    if gt_match_view is not None and new_match_view is not None:
        result['matched_view_same'] = matched_view_equal(gt_keys, new_keys, skip_activity=skip_activity)
    else:
        result['matched_view_same'] = False

    result['gt_matched_view'] = gt_keys[0]  # 保存 key1 用于显示
    result['new_matched_view'] = new_keys[0]
    result['gt_activity'] = gt_activity
    result['new_activity'] = new_activity

    return result


def calculate_metrics(
    apk_base: str,
    suffix: str,
    skip_cases: Set[Tuple[str, str, str]] = None,
    verbose: bool = False
) -> Dict:
    """
    计算新方法相对于 ground truth 的指标

    Args:
        apk_base: 数据目录
        suffix: 新方法的 repair_output 后缀 (e.g. "_v1")
        skip_cases: 需要跳过的 case

    Returns:
        统计结果
    """
    if skip_cases is None:
        skip_cases = set()

    html_report = os.path.join(apk_base, 'html_report', 'matching_report.html')
    cases = parse_matching_report(html_report)

    if not cases:
        return {}

    stats = {
        'total': 0,
        'skipped': 0,
        'gt_not_found': 0,
        'new_not_found': 0,
        'both_success': 0,
        'both_failure': 0,
        'gt_success_new_failure': 0,
        'gt_failure_new_success': 0,
        # failed event 的 matched_view 比较
        'matched_view_same': 0,
        'matched_view_diff': 0,
        # 下一个 event 的比较
        'next_event_same': 0,
        'next_event_diff': 0,
        'next_event_missing': 0,  # GT 或 New 没有下一个 event
        # 综合判断：两个都匹配才算成功
        'both_match': 0,  # matched_view_same AND next_event_same
        'failed_view_only': 0,  # matched_view_same but not next_event_same
        'next_event_only': 0,  # next_event_same but not matched_view_same
        'both_mismatch': 0,  # neither matched
        'details': []
    }

    for case in cases:
        record_app = case['record_app']
        replay_app = case['replay_app']
        run_count = case['run_count']
        idx = case['idx']

        # 检查是否跳过
        if should_skip_case(record_app, replay_app, run_count, skip_cases):
            stats['skipped'] += 1
            continue

        stats['total'] += 1

        # 构建目录路径
        gt_repair_dir = os.path.join(apk_base, f"repair_output_{replay_app}_run{run_count}_for_{record_app}")
        new_repair_dir = os.path.join(apk_base, f"repair_output_{replay_app}_run{run_count}_for_{record_app}{suffix}")

        if verbose:
            print(f"  [{idx}] Processing: {record_app} <- {replay_app} run{run_count}")
            print(f"    gt_repair_dir: {gt_repair_dir}")
            print(f"    new_repair_dir: {new_repair_dir}")

        # 加载 ground truth trace
        gt_trace = load_repair_trace(gt_repair_dir, verbose=verbose)
        if gt_trace is None:
            print(f"  [{idx}] SKIP: Ground truth trace 不存在")
            stats['gt_not_found'] += 1
            continue

        # 加载 new method trace
        new_trace = load_repair_trace(new_repair_dir, verbose=verbose)
        if new_trace is None:
            print(f"  [{idx}] SKIP: New method trace 不存在")
            stats['new_not_found'] += 1
            continue

        # 从 trace 中获取 failed_event_number
        failed_event_num = gt_trace.get('failed_event_number', -1)
        if verbose:
            print(f"    failed_event_num: {failed_event_num}")

        # 特殊处理：org.zephyrsoft.trackworktime 不比较 activity
        skip_activity = 'org.zephyrsoft.trackworktime' in apk_base
        print(f"apk_base: {apk_base}")
        print(f"first time skip_activity: {skip_activity}")

        # 比较 failed event 的 matched_view
        comparison = compare_repair_results(gt_trace, new_trace, gt_repair_dir, new_repair_dir, skip_activity=skip_activity)

        # 比较下一个 event
        next_comparison = compare_next_result(gt_repair_dir, new_repair_dir, failed_event_num, skip_activity=skip_activity)

        # 统计 repair 成功/失败
        gt_success = comparison['gt_success']
        new_success = comparison['new_success']

        if gt_success and new_success:
            stats['both_success'] += 1
        elif not gt_success and not new_success:
            stats['both_failure'] += 1
        elif gt_success and not new_success:
            stats['gt_success_new_failure'] += 1
        else:
            stats['gt_failure_new_success'] += 1

        # 统计 matched_view 比较
        matched_view_same = comparison['matched_view_same']
        if matched_view_same:
            stats['matched_view_same'] += 1
        else:
            stats['matched_view_diff'] += 1

        # 统计下一个 event 比较
        next_event_same = next_comparison['next_event_same']
        if not next_comparison['gt_has_next'] or not next_comparison['new_has_next']:
            stats['next_event_missing'] += 1
        elif next_event_same:
            stats['next_event_same'] += 1
        else:
            stats['next_event_diff'] += 1

        # 综合判断：两个都匹配才算成功
        if matched_view_same and next_event_same:
            stats['both_match'] += 1
        elif matched_view_same and not next_event_same:
            stats['failed_view_only'] += 1
        elif not matched_view_same and next_event_same:
            stats['next_event_only'] += 1
        else:
            stats['both_mismatch'] += 1

        stats['details'].append({
            'idx': idx,
            'record_app': record_app,
            'replay_app': replay_app,
            'run_count': run_count,
            **comparison,
            **next_comparison
        })

        # 输出：只有两个都匹配才显示成功
        overall_match = matched_view_same and next_event_same
        print(f"  [{idx}] GT: {'✓' if gt_success else '✗'}, New: {'✓' if new_success else '✗'}, "
              f"FailedView: {'✓' if matched_view_same else '✗'}, "
              f"NextEvent: {'✓' if next_event_same else '✗'}, "
              f"Overall: {'✓' if overall_match else '✗'}")

    return stats


def write_csv(stats: Dict, csv_path: str):
    """将详细结果写入 CSV 文件"""
    details = stats.get('details', [])
    if not details:
        print("WARNING: 没有详细数据可写入 CSV")
        return

    # 定义 CSV 列
    fieldnames = [
        'idx', 'record_app', 'replay_app', 'run_count',
        'gt_steps', 'new_steps',
        'matched_view_same',
        'gt_activity', 'new_activity',
        'next_event_same',
        'gt_has_next', 'new_has_next',
        'gt_next_activity', 'new_next_activity',
        'overall_match'
    ]

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()

        for row in details:
            # 添加 overall_match 字段
            row['overall_match'] = row.get('matched_view_same', False) and row.get('next_event_same', False)
            writer.writerow(row)


def print_summary(stats: Dict):
    """打印统计摘要"""
    print("\n" + "=" * 60)
    print("Metrics Summary")
    print("=" * 60)

    total = stats.get('total', 0)
    if total == 0:
        print("No cases to compare")
        return

    print(f"Total cases: {total}")
    print(f"Skipped: {stats.get('skipped', 0)}")
    print(f"GT not found: {stats.get('gt_not_found', 0)}")
    print(f"New not found: {stats.get('new_not_found', 0)}")
    print()

    both_success = stats.get('both_success', 0)
    both_failure = stats.get('both_failure', 0)
    gt_success_new_failure = stats.get('gt_success_new_failure', 0)
    gt_failure_new_success = stats.get('gt_failure_new_success', 0)

    compared = both_success + both_failure + gt_success_new_failure + gt_failure_new_success

    print(f"Compared cases: {compared}")
    print(f"  Both Success: {both_success} ({both_success/compared*100:.1f}%)" if compared > 0 else "  Both Success: 0")
    print(f"  Both Failure: {both_failure} ({both_failure/compared*100:.1f}%)" if compared > 0 else "  Both Failure: 0")
    print(f"  GT ✓ New ✗: {gt_success_new_failure} ({gt_success_new_failure/compared*100:.1f}%)" if compared > 0 else "  GT ✓ New ✗: 0")
    print(f"  GT ✗ New ✓: {gt_failure_new_success} ({gt_failure_new_success/compared*100:.1f}%)" if compared > 0 else "  GT ✗ New ✓: 0")
    print()

    # Failed Event 的 matched_view 比较
    matched_same = stats.get('matched_view_same', 0)
    matched_diff = stats.get('matched_view_diff', 0)
    print(f"Failed Event View:")
    print(f"  Same: {matched_same}")
    print(f"  Different: {matched_diff}")
    print()

    # 下一个 Event 比较
    next_same = stats.get('next_event_same', 0)
    next_diff = stats.get('next_event_diff', 0)
    next_missing = stats.get('next_event_missing', 0)
    print(f"Next Event:")
    print(f"  Same: {next_same}")
    print(f"  Different: {next_diff}")
    print(f"  Missing: {next_missing}")
    print()

    # 综合判断（两个都匹配才算成功）
    both_match = stats.get('both_match', 0)
    failed_view_only = stats.get('failed_view_only', 0)
    next_event_only = stats.get('next_event_only', 0)
    both_mismatch = stats.get('both_mismatch', 0)

    print(f"Overall Match (FailedView AND NextEvent):")
    print(f"  Both Match: {both_match} ({both_match/compared*100:.1f}%)" if compared > 0 else f"  Both Match: {both_match}")
    print(f"  FailedView Only: {failed_view_only}")
    print(f"  NextEvent Only: {next_event_only}")
    print(f"  Both Mismatch: {both_mismatch}")

    if compared > 0:
        accuracy = both_match / compared * 100
        print(f"\n*** Overall Accuracy: {accuracy:.1f}% ({both_match}/{compared}) ***")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='计算 repair 方法的正确率')
    parser.add_argument('--apk-base', required=True, help='数据目录')
    parser.add_argument('--suffix', required=True, help='新方法的 repair_output 后缀 (e.g. "_v1")')
    parser.add_argument('--no-skip-delete-cases', action='store_true',
                        help='不跳过 Need_to_delete.csv 中列出的 case（默认会跳过）')
    parser.add_argument('--delete-csv', default='Need_to_delete.csv',
                        help='需要删除的 case 列表文件路径（默认: Need_to_delete.csv）')
    parser.add_argument('--output-json', default=None,
                        help='输出详细结果到 JSON 文件')
    parser.add_argument('--output-csv', default=None,
                        help='输出详细结果到 CSV 文件')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='显示详细调试信息')
    args = parser.parse_args()

    if not os.path.exists(args.apk_base):
        print(f"ERROR: 目录不存在: {args.apk_base}")
        sys.exit(1)

    # 加载需要跳过的 case（默认跳过）
    skip_cases = set()
    if not args.no_skip_delete_cases:
        skip_cases = load_skip_cases(args.delete_csv)

    print(f"Comparing repair results:")
    print(f"  Ground Truth: repair_output_*")
    print(f"  New Method: repair_output_*{args.suffix}")
    if args.verbose:
        print(f"  Verbose mode: ON")
    print()

    # 计算指标
    stats = calculate_metrics(args.apk_base, args.suffix, skip_cases, verbose=args.verbose)

    # 打印摘要
    print_summary(stats)

    # 输出 JSON
    if args.output_json:
        with open(args.output_json, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        print(f"\n详细结果已保存到: {args.output_json}")

    # 输出 CSV
    if args.output_csv:
        write_csv(stats, args.output_csv)
        print(f"CSV 结果已保存到: {args.output_csv}")


if __name__ == '__main__':
    main()
