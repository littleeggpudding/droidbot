#!/usr/bin/env python3
"""
DroidBot Repair 批量运行器

支持一种运行模式:
- repair: 修复失败的测试用例（从 html_report 解析失败用例）

repair 模式参数说明:
- -replay_output: 原始录制目录，如 record_output_{record_app}_run{N}
- -failed_replay_output: 失败的回放目录，如 replay_output_{replay_app}_run{N}_for_{record_app}
- -o: repair 输出目录，如 repair_output_{replay_app}_run{N}_for_{record_app}

目录结构:
{apk-base}/
├── html_report/
│   └── matching_report.html  <- 从这里解析失败用例
├── record_output_{app}_run{N}/
├── replay_output_{app}_run{N}_for_{base}/
├── repair_output_{app}_run{N}_for_{base}/  <- 输出到这里
└── select_apks/
    └── {package_name}/
        └── v{version}.apk

使用示例:
python3 start_repair_bash.py \
    --apk-base /data/shiwensong/droidbot/com.byagowi.persiancalendar \
    --max-parallel 4
"""

import os
import sys
import re
import csv
import time
import logging
import argparse
import subprocess
import signal
import glob
import shutil
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Set, Tuple
from queue import Queue

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


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
        logger.warning(f"CSV 文件不存在: {csv_path}")
        return skip_cases

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            record_app = row.get('Record App', '').strip()
            replay_app = row.get('Replay App', '').strip()
            run_count = row.get('Run Count', '').strip()
            if record_app and replay_app and run_count:
                skip_cases.add((record_app, replay_app, run_count))

    logger.info(f"已加载 {len(skip_cases)} 个需要跳过的 case")
    return skip_cases


def should_skip_case(record_app: str, replay_app: str, run_count: str,
                     skip_cases: Set[Tuple[str, str, str]]) -> bool:
    """检查是否应该跳过这个 case"""
    return (record_app, replay_app, run_count) in skip_cases


class DroidBotRepairRunner:
    """DroidBot Repair 批量运行器"""

    def __init__(self, args):
        self.apk_base = args.apk_base  # 数据目录，如 /data/.../com.xxx
        self.android_home = args.android_home
        self.avd_name = args.avd_name
        self.start_py = args.start_py
        self.count = args.count
        self.max_parallel = args.max_parallel
        self.per_task_timeout = args.per_task_timeout
        self.test_mode = args.test_mode

        # 加载需要跳过的 case
        self.skip_delete_cases = args.skip_delete_cases
        self.skip_cases = set()
        if self.skip_delete_cases:
            self.skip_cases = load_skip_cases(args.delete_csv)

        # repair 输出目录后缀
        self.repair_output_dir_suffix = args.repair_output_dir_suffix

        # HTML 报告路径自动从 apk_base 推导
        self.html_report = os.path.join(self.apk_base, 'html_report', 'matching_report.html')

        # select_apks 目录（可通过参数指定，否则从 apk_base 推导）
        # 默认路径: ../droidbot/select_apks/{package_name}
        if args.select_apks:
            self.select_apks_dir = args.select_apks
        else:
            package_name = os.path.basename(os.path.abspath(self.apk_base))
            parent_dir = os.path.dirname(os.path.abspath(self.apk_base))
            self.select_apks_dir = os.path.join(parent_dir, 'droidbot', 'select_apks', package_name)

        self.log_dir = args.log_dir or self._default_log_dir()

        # 端口配置
        self.base_port = args.base_port
        self.port_step = 2

        self._setup_environment()
        os.makedirs(self.log_dir, exist_ok=True)

    def _default_log_dir(self) -> str:
        return os.path.join(self.apk_base, 'logs_repair')

    def _setup_environment(self):
        """设置 Android SDK 环境变量"""
        os.environ['ANDROID_HOME'] = self.android_home
        os.environ['ANDROID_SDK_ROOT'] = self.android_home
        paths = [
            f"{self.android_home}/cmdline-tools/latest/bin",
            f"{self.android_home}/platform-tools",
            f"{self.android_home}/emulator"
        ]
        os.environ['PATH'] = ':'.join(paths) + ':' + os.environ.get('PATH', '')

    def start_emulators_batch(self, num_emulators: int) -> bool:
        """批量启动模拟器"""
        try:
            logger.info(f"Starting {num_emulators} emulators...")
            result = subprocess.run(
                ['./start_emulator.sh', str(num_emulators)],
                check=True,
                capture_output=True,
                text=True,
                timeout=600
            )
            logger.info(f"✓ Started {num_emulators} emulators")
            return True
        except subprocess.TimeoutExpired:
            logger.error("Timeout starting emulators")
            return False
        except Exception as e:
            logger.error(f"Failed to start emulators: {e}")
            return False

    def kill_emulator(self, serial: str, force: bool = True):
        """杀死模拟器"""
        port = serial.split('-')[1]
        logger.info(f"Killing emulator {serial}...")

        try:
            subprocess.run(
                ['adb', '-s', serial, 'emu', 'kill'],
                capture_output=True,
                timeout=3
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"adb kill timeout for {serial}, using force kill")
        except Exception as e:
            logger.debug(f"adb kill error: {e}")

        if force:
            try:
                subprocess.run(
                    ['pkill', '-9', '-f', f'emulator.*-port {port}'],
                    capture_output=True,
                    timeout=2
                )
            except:
                pass

            pid_file = f'emulator_{port}.pid'
            if os.path.exists(pid_file):
                try:
                    with open(pid_file, 'r') as f:
                        pid = f.read().strip()
                    os.kill(int(pid), signal.SIGKILL)
                except:
                    pass
                try:
                    os.unlink(pid_file)
                except:
                    pass

        logger.info(f"✓ Killed {serial}")

    def cleanup_all_emulators(self):
        """清理所有模拟器"""
        logger.info("Cleaning up all emulators...")
        try:
            subprocess.run(
                ['pkill', '-9', '-f', f'emulator.*-avd {self.avd_name}'],
                capture_output=True,
                timeout=5
            )
        except:
            pass
        time.sleep(2)
        logger.info("✓ Cleanup completed")

    def parse_html_report(self, html_report_path: str) -> List[Dict]:
        """
        解析 HTML 报告，提取失败的测试用例

        HTML 表格列:
        - Record App: 基础版本（录制时的 APK 版本）
        - Replay App: 新版本（回放时的 APK 版本）
        - Run Count: 运行次数
        - Result: 匹配结果 (Success/Failure)
        - Method: 匹配方法

        Returns:
            失败测试用例列表
        """
        if not HAS_BS4:
            logger.error("需要安装 beautifulsoup4: pip install beautifulsoup4")
            return []

        if not os.path.exists(html_report_path):
            logger.error(f"HTML 报告文件不存在: {html_report_path}")
            return []

        with open(html_report_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, 'html.parser')

        # 找到 summary 表格
        summary_div = soup.find('div', class_='summary')
        if not summary_div:
            logger.error("未找到 summary 表格")
            return []

        table = summary_div.find('table')
        if not table:
            logger.error("未找到表格")
            return []

        # 获取所有行（跳过表头）
        rows = table.find_all('tr')[1:]

        failed_cases = []
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 5:
                continue

            record_app = cells[0].get_text(strip=True)
            replay_app = cells[1].get_text(strip=True)
            run_count = cells[2].get_text(strip=True)
            result = cells[3].get_text(strip=True)
            method = cells[4].get_text(strip=True)

            # 只收集失败的用例
            if result.lower() == 'failure' or result.lower() == 'success':
                failed_cases.append({
                    'record_app': record_app,
                    'replay_app': replay_app,
                    'run_count': run_count,
                    'result': result,
                    'method': method
                })

        logger.info(f"从 HTML 报告中解析到 {len(failed_cases)} 个失败的测试用例")
        return failed_cases

    def sanitize_suffix(self, name: str) -> str:
        """
        生成安全的目录名（与 start_bash.py 保持一致）

        处理逻辑：
        1. 只保留字母数字和 ._-，其他字符替换为 _
        2. 把 . 替换成 _
        3. 去掉末尾的 _
        """
        s = os.path.splitext(name)[0]  # 去掉扩展名
        s = ''.join(c if c.isalnum() or c in '._-' else '_' for c in s)
        s = s.replace('.', '_').rstrip('_')
        return s if s else 'apk'

    def suffix_to_apk_path(self, suffix: str) -> Optional[str]:
        """
        将表格中的 app 版本名称转换为 APK 路径

        HTML table 里的 suffix 已经是经过 sanitize_suffix 处理的（从目录名提取）
        所以只需要对 APK 文件名做同样的 sanitize_suffix 处理后直接比较

        例如：
        - suffix (from HTML): "Notes__Privacy_Friendly__v1_3_0"
        - APK: "Notes_(Privacy_Friendly)_v1.3.0.apk"
        - sanitize后: "Notes__Privacy_Friendly__v1_3_0"
        - 两者相同，匹配成功

        Args:
            suffix: 版本名称（已经是 sanitized 的形式）

        Returns:
            APK 文件路径，如果未找到则返回 None
        """
        # 获取所有 APK 文件
        search_pattern = os.path.join(self.select_apks_dir, "**/*.apk")
        all_apks = glob.glob(search_pattern, recursive=True)

        # 遍历查找匹配的 APK
        for apk_path in all_apks:
            apk_name = os.path.basename(apk_path)
            # 用 sanitize_suffix 处理 APK 文件名
            sanitized_apk = self.sanitize_suffix(apk_name)

            if suffix == sanitized_apk:
                logger.debug(f"找到 APK: {suffix} -> {apk_path}")
                return apk_path

        logger.warning(f"未找到 APK: {suffix}")
        return None

    def generate_tasks(self) -> List[Dict]:
        """
        从 HTML 报告生成 repair 任务

        目录映射关系 (所有目录都在 apk_base 下):
        - record_output: record_output_{record_app}_run{N}
        - failed_replay_output: replay_output_{replay_app}_run{N}_for_{record_app}
        - repair_output: repair_output_{replay_app}_run{N}_for_{record_app}
        """
        failed_cases = self.parse_html_report(self.html_report)
        if not failed_cases:
            return []

        tasks = []
        skipped_count = 0
        for case in failed_cases:
            record_app = case['record_app']
            replay_app = case['replay_app']
            run_count = case['run_count']

            # 检查是否需要跳过
            if should_skip_case(record_app, replay_app, run_count, self.skip_cases):
                logger.info(f"跳过: 在 Need_to_delete.csv 中 - {record_app} <- {replay_app} run{run_count}")
                skipped_count += 1
                continue

            # 构建目录名 (相对于 apk_base)
            record_output_dir = os.path.join(self.apk_base, f"record_output_{record_app}_run{run_count}")
            failed_replay_output_dir = os.path.join(self.apk_base, f"replay_output_{replay_app}_run{run_count}_for_{record_app}")
            repair_output_dir = os.path.join(self.apk_base, f"repair_output_{replay_app}_run{run_count}_for_{record_app}{self.repair_output_dir_suffix}")

            # 检查目录是否存在
            if not os.path.exists(record_output_dir):
                logger.info(f"跳过: record 目录不存在: {record_output_dir}")
                continue

            if not os.path.exists(failed_replay_output_dir):
                logger.info(f"跳过: failed replay 目录不存在: {failed_replay_output_dir}")
                continue

            # 检查是否已经 repair 过
            if os.path.exists(repair_output_dir):
                logger.info(f"跳过: 已存在 repair 目录: {repair_output_dir}")
                continue

            # 查找 APK 路径（使用 replay_app，即新版本）
            apk_path = self.suffix_to_apk_path(replay_app)
            if not apk_path:
                logger.info(f"跳过: 未找到 APK: {replay_app} (在 {self.select_apks_dir} 中)")
                continue

            tasks.append({
                'apk_path': apk_path,
                'suffix': replay_app,
                'run_idx': int(run_count),
                'out_dir': repair_output_dir,
                'record_dir': record_output_dir,
                'failed_replay_dir': failed_replay_output_dir,
                'base_suffix': record_app
            })

        logger.info(f"生成 {len(tasks)} 个 repair 任务")
        if skipped_count > 0:
            logger.info(f"跳过了 {skipped_count} 个 case (在 Need_to_delete.csv 中)")
        return tasks

    def run_single_task(self, task: Dict, serial: str) -> bool:
        """运行单个 repair 任务"""
        apk_path = task['apk_path']
        out_dir = task['out_dir']
        run_idx = task['run_idx']
        record_dir = task['record_dir']
        failed_replay_dir = task['failed_replay_dir']

        port = serial.split('-')[1]
        log_file = os.path.join(self.log_dir, f"{os.path.basename(out_dir)}_{port}.log")

        logger.info(f"[{serial}] Running repair: {task['suffix']} (run {run_idx})")

        # 构建命令
        cmd = [
            'python3', self.start_py,
            '-a', apk_path,
            '-o', out_dir,
            '-replay_output', record_dir,
            '-failed_replay_output', failed_replay_dir,
            '-is_emulator',
            '-policy', 'matching',
            '-count', str(self.count),
            '-d', serial
        ]

        logger.debug(f"[{serial}] CMD: {' '.join(cmd)}")

        success = False
        try:
            if self.test_mode:
                logger.info(f"[{serial}] TEST MODE → {out_dir}")
                time.sleep(1)
                success = True
            else:
                with open(log_file, 'w') as f:
                    result = subprocess.run(
                        cmd,
                        stdout=f,
                        stderr=subprocess.STDOUT,
                        timeout=self.per_task_timeout
                    )
                    success = (result.returncode == 0)

        except subprocess.TimeoutExpired:
            logger.error(f"[{serial}] ✗ TIMEOUT after {self.per_task_timeout}s")
            shutil.rmtree(out_dir, ignore_errors=True)
            success = False

        except Exception as e:
            logger.error(f"[{serial}] ✗ Error: {e}")
            success = False

        finally:
            try:
                self.kill_emulator(serial, force=True)
            except Exception as e:
                logger.error(f"Error killing {serial}: {e}")

        if success:
            logger.info(f"[{serial}] ✓ Success → {out_dir}")
        else:
            logger.error(f"[{serial}] ✗ Failed (see {log_file})")

        return success

    def run_batch(self, tasks: List[Dict]) -> int:
        """运行一批任务"""
        batch_size = len(tasks)
        logger.info("=" * 60)
        logger.info(f"Batch: {batch_size} tasks")
        logger.info("=" * 60)

        if not self.start_emulators_batch(batch_size):
            logger.error("Failed to start emulators")
            return 0

        serial_queue = Queue()
        for i in range(batch_size):
            port = self.base_port + i * self.port_step
            serial = f"emulator-{port}"
            serial_queue.put(serial)

        logger.info(f"Emulators ready: {batch_size}")

        def worker(task_and_serial):
            task, serial = task_and_serial
            return self.run_single_task(task, serial)

        task_assignments = []
        for task in tasks:
            serial = serial_queue.get()
            task_assignments.append((task, serial))

        success_count = 0
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            results = executor.map(worker, task_assignments)
            for success in results:
                if success:
                    success_count += 1

        logger.info(f"Batch completed: {success_count}/{batch_size} successful")

        time.sleep(2)
        for _, serial in task_assignments:
            try:
                self.kill_emulator(serial, force=True)
            except:
                pass

        return success_count

    def run(self):
        """主运行逻辑"""
        logger.info("=" * 60)
        logger.info("REPAIR Mode")
        logger.info(f"Data Dir: {self.apk_base}")
        logger.info(f"HTML Report: {self.html_report}")
        logger.info(f"APK Dir: {self.select_apks_dir}")
        logger.info(f"Max Parallel: {self.max_parallel}")
        logger.info("=" * 60)

        # 检查 HTML 报告是否存在
        if not os.path.exists(self.html_report):
            logger.error(f"HTML 报告不存在: {self.html_report}")
            return

        # 检查 select_apks 目录是否存在
        if not os.path.exists(self.select_apks_dir):
            logger.error(f"APK 目录不存在: {self.select_apks_dir}")
            return

        # 清理环境
        self.cleanup_all_emulators()

        # 生成任务
        all_tasks = self.generate_tasks()

        if not all_tasks:
            logger.warning("No tasks to run")
            return

        logger.info(f"Total tasks: {len(all_tasks)}")

        # 分批执行
        total_success = 0
        for i in range(0, len(all_tasks), self.max_parallel):
            batch = all_tasks[i:i + self.max_parallel]
            batch_num = i // self.max_parallel + 1
            total_batches = (len(all_tasks) + self.max_parallel - 1) // self.max_parallel

            logger.info(f"\n{'=' * 60}")
            logger.info(f"Batch {batch_num}/{total_batches}")
            logger.info(f"{'=' * 60}")

            success = self.run_batch(batch)
            total_success += success

            if i + self.max_parallel < len(all_tasks):
                logger.info("Waiting 5s before next batch...")
                time.sleep(5)

        # 统计
        logger.info(f"\n{'=' * 60}")
        logger.info("REPAIR Completed")
        logger.info(f"Success: {total_success}/{len(all_tasks)}")
        logger.info(f"{'=' * 60}")


def signal_handler(signum, frame):
    """Ctrl+C 处理"""
    logger.warning("Interrupted! Cleaning up...")
    subprocess.run(['pkill', '-9', 'emulator'], capture_output=True)
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(
        description='DroidBot Repair 批量运行器 - 从 HTML 报告解析失败用例并修复'
    )

    parser.add_argument('--apk-base', required=True,
                        help='数据目录，如 /data/shiwensong/droidbot/com.xxx，会自动读取 html_report/matching_report.html')
    parser.add_argument('--android-home', default=os.path.expanduser("~/android-sdk"),
                        help='Android SDK 路径')
    parser.add_argument('--avd-name', '--avd', default='Android10.0',
                        help='AVD 名称')
    parser.add_argument('--start-py', default='start.py',
                        help='start.py 路径')
    parser.add_argument('--count', type=int, default=100,
                        help='每个任务的事件数量')
    parser.add_argument('--max-parallel', type=int, default=8,
                        help='最大并行任务数')
    parser.add_argument('--per-task-timeout', type=int, default=1800,
                        help='每个任务的超时时间（秒），默认30分钟')
    parser.add_argument('--log-dir', default=None,
                        help='日志目录（默认在 apk-base/logs_repair）')
    parser.add_argument('--test-mode', action='store_true',
                        help='测试模式，不实际运行')
    parser.add_argument('--base-port', type=int, default=5554,
                        help='模拟器起始端口（默认 5554）')
    parser.add_argument('--select-apks', default=None,
                        help='APK 目录路径（默认从 apk-base/select_apks 推导）')
    parser.add_argument('--skip-delete-cases', action='store_true',
                        help='跳过 Need_to_delete.csv 中列出的 case')
    parser.add_argument('--delete-csv', default='Need_to_delete.csv',
                        help='需要删除的 case 列表文件路径（默认: Need_to_delete.csv）')
    parser.add_argument('--repair-output-dir-suffix', default='',
                        help='repair 输出目录后缀，直接拼接在目录名后面（默认: 空）')

    return parser.parse_args()


def main():
    args = parse_args()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        runner = DroidBotRepairRunner(args)
        runner.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
