"""
解析测试用例目录，提取原始应用和新版应用的数据对
"""

import os
import re
import glob
import json
from lxml import etree as ET
from typing import Dict, List, Tuple, Optional
import concurrent.futures
import csv
from datetime import datetime
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback

# 导入匹配模块
from .Matcher import Matcher
from .utils import draw_element_on_image, read_image, compute_ssim
from .Logger import get_logger


class Parser:
    """测试用例解析器"""
    
    def __init__(self, dataset_dir: str, base_app_filter: str = None, run_count_filter: str = None):
        """
        初始化解析器
        
        Args:
            dataset_dir: 测试用例目录，如 "test_case1"
            base_app_filter: 基础应用过滤器，例如 "v6_4_1"，用于只处理特定基础版本的测试用例
            run_count_filter: 运行计数过滤器，例如 "3"，用于只处理特定运行计数的测试用例
        """
        self.dataset_dir = dataset_dir
        self.base_app_filter = base_app_filter
        self.run_count_filter = run_count_filter
        self.test_cases_pairs = self.generate_test_cases_pairs()
        print("before deduplicate test_cases_pairs", len(self.test_cases_pairs))
        self.deduplicate_failed_events()
        print("after deduplicate test_cases_pairs", len(self.test_cases_pairs))
        
    
    def generate_test_cases_pairs(self) -> Dict[Tuple[str, str, str], Dict]:
        """
        1. 解析测试用例目录，提取文件夹对
        2. 针对每一对test case，找到里面出错的地方，获取里面的png xml events等信息
        """
        # 查找所有 replay 文件夹
        replay_folders = self.find_replay_folders()
        
        # 解析数据对
        pairs = {}
        for replay_folder in replay_folders:
            replay_name = os.path.basename(replay_folder)
            replay_info = self.parse_replay_dir_name(replay_name)
            
            if not replay_info:
                continue
            
            # 如果指定了run_count_filter，只处理匹配的
            if self.run_count_filter and str(replay_info['run_count']) != str(self.run_count_filter):
                continue

            # 如果指定了base_app_filter，只处理匹配的
            if self.base_app_filter and str(replay_info['base_version']) != str(self.base_app_filter):
                continue
                
            # 推导对应的 record 文件夹
            record_name = self.derive_record_folder(replay_info)
            if not record_name:
                continue
                        
            # 创建数据对 - 使用三元组作为键 (base_version, new_version, run_count)
            pair_id = (replay_info['base_version'], replay_info['new_version'], replay_info['run_count'])
            
            record_path = os.path.join(self.dataset_dir, record_name)
            replay_events_count =  self.count_events(os.path.join(replay_folder, "events"))
            if replay_events_count == 100: #说明没有失败的event
                continue
            pairs[pair_id] = {
                "record_path": record_path,
                "replay_path": replay_folder,
                "replay_events_count":replay_events_count
            }
        
        return pairs
    
    def find_replay_folders(self) -> List[str]:
        """
        在 dataset_dir 下查找所有 replay_output_*_for_* 文件夹。
        如果提供 base_app_filter（例如 "v6_4_1"），则仅返回 *_for_{base_app_filter} 的目录。
        
        Returns:
            replay 文件夹路径列表
        """
        pattern = os.path.join(self.dataset_dir, "replay_output_*_for_*")
        replay_folders = glob.glob(pattern)
        
        if self.base_app_filter:
            suffix = f"_for_{self.base_app_filter}"
            replay_folders = [p for p in replay_folders if os.path.basename(p).endswith(suffix)]
        
        return replay_folders
    
    def derive_record_folder(self, replay_info: Dict) -> Optional[str]:
        """
        根据 replay 信息推导对应的 record 文件夹名。
        例：对于 replay_info = {"new_version": "v6_6_2", "run_count": "3", "base_version": "v6_4_1"}
        返回 "record_output_v6_4_1_run3"
        
        Args:
            replay_info: replay 信息字典，包含 new_version, run_count, base_version
            
        Returns:
            对应的 record 文件夹名称，如果无法推导则返回 None
        """
        if not replay_info or 'base_version' not in replay_info or 'run_count' not in replay_info:
            return None
        
        base_app = replay_info['base_version']
        run_count = replay_info['run_count']
        
        # 构建 record 文件夹名
        record_name = f"record_output_{base_app}_run{run_count}"
        
        # 检查是否存在
        record_path = os.path.join(self.dataset_dir, record_name)
        if os.path.exists(record_path):
            return record_name
        
        return None
    
    def parse_replay_dir_name(self, dir_name: str) -> Optional[Dict]:
        """
        解析 replay 目录名称
        
        Args:
            dir_name: 目录名称，如 "replay_output_V3_0_9-F-DROID_run3_for_V3_0_2-F-DROID"
            
        Returns:
            解析结果，如 {"new_version": "V3_0_9-F-DROID", "run_count": "3", "base_version": "V3_0_2-F-DROID"}
        """
        match = re.match(r'^replay_output_(?P<new_version>.+?)_run(?P<run_count>\d+)_for_(?P<base_version>.+)$', dir_name)
        if match:
            return match.groupdict()
        return None
    
    def count_events(self, events_dir: str) -> int:
        """
        统计 events 目录下的 .json 数量
        
        Args:
            events_dir: 事件目录路径
            
        Returns:
            事件数量
        """
        if not os.path.isdir(events_dir):
            return 0
        
        json_paths = glob.glob(os.path.join(events_dir, "*.json"))
        return len(json_paths)
    
    def find_original_element(self, event_path, xml_tree) -> ET.Element:
        """
        根据event中的信息，在xml_tree中找到对应的元素
        
        Args:
            event_path: 事件文件路径
            xml_tree: XML树对象
            
        Returns:
            找到的元素对象或者none
        """
        import json
        
        # 1. 从事件文件中提取bounds和class信息
        try:
            with open(event_path, 'r', encoding='utf-8') as f:
                event = json.load(f)
            
            # 提取目标bounds和class
            verified_bounds = None
            verified_class = None
            verified_text = None
            verified_resource_id = None
            verified_content_description = None
            
            
            if 'event' in event and 'view' in event['event']:
                view = event['event']['view']
                if 'bounds' in view:
                    verified_bounds = view['bounds']
                if 'class' in view:
                    verified_class = view['class']
                if 'text' in view:
                    verified_text = view['text']
                if 'resource_id' in view:
                    verified_resource_id = view['resource_id']
                if 'content_description' in view:
                    verified_content_description = view['content_description']
            
                
            # 将bounds转换为字符串格式 [x1,y1][x2,y2]
            verified_bounds_str = f"[{verified_bounds[0][0]},{verified_bounds[0][1]}][{verified_bounds[1][0]},{verified_bounds[1][1]}]"
            
        except Exception as e:
            print(f"Error reading event file: {e}")
            return None
        
        # 2. 在XML树中查找具有相同属性的结点
        if xml_tree is None:
            print("XML tree is None")
            return None
            
        root = xml_tree.getroot()

        for node in root.iter():
            attrs = node.attrib

            def norm(v):
                # 把 None 或 "" 都归一到 None
                return v if v not in (None, "") else None

            current_bounds = norm(attrs.get('bounds'))
            current_class = norm(attrs.get('class'))
            current_text = norm(attrs.get('text'))
            current_resource_id = norm(attrs.get('resource-id'))
            current_content_desc = norm(attrs.get('content-desc'))

            match = True

            if verified_bounds_str is not None and current_bounds != verified_bounds_str:
                match = False
            if verified_class is not None and current_class != verified_class:
                match = False
            if verified_text is not None and current_text != verified_text:
                match = False
            if verified_resource_id is not None and current_resource_id != verified_resource_id:
                match = False
            if verified_content_description is not None and current_content_desc != verified_content_description:
                match = False

            if match:
                return node

        
        # 返回找到的元素对象
        return None
    
    
    def parse_xml_file(self, xml_path: str) -> Optional[ET.ElementTree]:
        """
        使用lxml解析XML文件
        
        Args:
            xml_path: XML文件路径
            
        Returns:
            解析后的XML树对象，如果解析失败则返回None

        ElementTree = 包裹整个 XML 文档的树
        Element = XML 里的一个节点
        每个 Element 可以有:
            - tag（节点名）
            - attrib（属性字典）
            - text（文本内容）
            - children（子节点）
            
        lxml的ElementTree提供了比标准库更丰富的功能:
            - getparent(): 获取父节点
            - xpath(): 支持更强大的XPath查询
            - getprevious()/getnext(): 获取前一个/后一个兄弟节点
        """
        if not os.path.exists(xml_path):
            print(f"XML文件不存在: {xml_path}")
            return None
            
        result_tree = None
        
        try:
            # 使用lxml的parser，保留注释
            parser = ET.XMLParser(remove_blank_text=True, remove_comments=False)
            result_tree = ET.parse(xml_path, parser)
        except Exception as e:
            print(f"解析XML文件失败 {xml_path}: {e}")
        
        return result_tree
    
    def process_single_pair(self, pair_data):
        """
        处理单个测试用例对
        
        Args:
            pair_data: (pair_id, pair_info)元组
            
        Returns:
            (pair_id, matching_result)元组
        """
        pair_id, pair_info = pair_data
        failed_event_number = pair_info['replay_events_count'] + 1
        record_path = pair_info['record_path']
        replay_path = pair_info['replay_path']
        
        # 为每个进程创建独立的日志目录和日志记录器
        log_dir = os.path.join(self.dataset_dir, f"logs/logs_pair_{pair_id}")
        os.makedirs(log_dir, exist_ok=True)
        # 使用唯一的日志记录器名称并强制创建新的处理器
        logger_name = f"UIMatch_pair_{pair_id}"
        logger = get_logger(name=logger_name, log_dir=log_dir, force_new_handlers=True)
        
        # find png + xml + event in record
        original_event = f"{record_path}/events/event_{failed_event_number}.json"
        original_png = f"{record_path}/states/screen_{failed_event_number-1}.png"
        original_xml = f"{record_path}/xmls/xml_{failed_event_number-1}.xml"
        original_tree = self.parse_xml_file(original_xml)
        original_element = self.find_original_element(original_event, original_tree)
        print(f"original_element: {original_element}")

        # find png + xml in replay
        replay_png = f"{replay_path}/states/screen_{failed_event_number-1}.png"
        replay_xml = f"{replay_path}/xmls/xml_{failed_event_number-1}.xml"
        replay_tree = self.parse_xml_file(replay_xml)

        # check if has success png in replay
        if os.path.exists(f"{replay_path}/states/screen_{failed_event_number-1}_success.png"):
            return pair_id, {
                "success": False,
                "matching_method": "Exists Success",
            }

        #调用算法来matching the original and replay
        matcher = Matcher(original_png, original_tree, original_element, replay_png, replay_tree, logger)
        matching_result = matcher.matching()
        logger.info(f"matching_result: {matching_result}")
        if matching_result["success"]:
            #在replay png中标注
            if matching_result['matched_element'] is not None:
                logger.info(f"matching_result: {matching_result['matched_element'].attrib}")
                replay_img = read_image(replay_png)
                replay_img = draw_element_on_image(replay_img, matching_result["matched_element"].attrib.get("bounds", ""))
                replay_img.save(replay_png.replace(".png", "_success.png"))
                # 将lxml.etree._Attrib对象转换为普通Python字典
                matching_result['matched_element'] = dict(matching_result['matched_element'].attrib)
                # save as a json file for matched element
                with open(f"{replay_path}/matched_element_{failed_event_number-1}.json", "w", encoding="utf-8") as f:
                    json.dump(matching_result['matched_element'], f, ensure_ascii=False, indent=4)

                # save as a json file for matched method
                with open(f"{replay_path}/matched_method_{failed_event_number-1}.json", "w", encoding="utf-8") as f:
                    json.dump(matching_result['matching_method'], f, ensure_ascii=False, indent=4)

            else:
                matching_result['success'] = False

        
        return pair_id, matching_result
    
    def read_event_attributes(self, event_path: str) -> Dict:
        """
        读取event文件
        """
        try:
            with open(event_path, 'r', encoding='utf-8') as f:
                event = json.load(f)
        except Exception as e:
            print(f"Error reading event file: {e}")
            return None
        
        bounds = ""
        class_name = ""
        text = ""
        resource_id = ""
        content_description = ""
        if 'event' in event and 'view' in event['event']:
                view = event['event']['view']
                if 'bounds' in view:
                    bounds = view['bounds']
                if 'class' in view:
                    class_name = view['class']
                if 'text' in view:
                    text = view['text']
                if 'resource_id' in view:
                    resource_id = view['resource_id']
                if 'content_description' in view:
                    content_description = view['content_description']
        
        result_str = f"{str(bounds)}|{class_name}|{text}|{resource_id}|{content_description}"
        return result_str
    
    def deduplicate_failed_events(self) -> List[Dict]:
        """
        去重failed events
        self.test_cases_pairs

        1. base app, run count, replay_events_count相同, 说明是同一个scenario发生的failed
        2. new app跟event里面的内容相同, 说明是同一个元素发生的failed
        """

        visited_pairs_1 = set()
        cleaned_test_cases_pairs_1 = {}

        for pair_id, pair_info in self.test_cases_pairs.items():
            # paire_id: base_version, run_count, replay_events_count
            pair_key = (pair_id[0], pair_id[2], pair_info['replay_events_count'])

            if pair_key in visited_pairs_1:
                continue
            visited_pairs_1.add(pair_key)
            cleaned_test_cases_pairs_1[pair_id] = pair_info

        visited_pairs_2 = set()
        cleaned_test_cases_pairs_2 = {}
        for pair_id, pair_info in cleaned_test_cases_pairs_1.items():
            failed_event_number = pair_info['replay_events_count'] + 1
            current_event_path = f"{pair_info['record_path']}/events/event_{failed_event_number}.json"

            if failed_event_number == 101:
                continue #说明没有失败的event
            current_event_attributes_str = self.read_event_attributes(current_event_path)
            if current_event_attributes_str is None:
                continue
            new_version = pair_id[1]
            pair_key = (current_event_attributes_str, new_version)
            if pair_key in visited_pairs_2:
                continue
            visited_pairs_2.add(pair_key)
            cleaned_test_cases_pairs_2[pair_id] = pair_info
        self.test_cases_pairs = cleaned_test_cases_pairs_2

        
    
    def read_and_matching_failed_events_sequential(self) -> Dict:
        """
        读取 failed 事件，使用顺序for循环处理（用于调试）
        
        Args:
            debug: 是否启用详细调试输出
            
        Returns:
            包含匹配结果的测试用例字典
        """
        import time
        
        total_count = len(self.test_cases_pairs)
        print(f"开始顺序处理 {total_count} 个测试用例对...")
        
        # 处理统计
        success_count = 0
        error_count = 0
        start_time = time.time()
        
        # 遍历处理每个测试用例
        for idx, (pair_id, pair_info) in enumerate(self.test_cases_pairs.items(), 1):
            try:
                # 显示当前处理的测试用例信息
                record_app, replay_app, run_count = pair_id
                print(f"\n[{idx}/{total_count}] 正在处理: {record_app} → {replay_app} (Run {run_count})")
                
                
                # 处理测试用例
                process_start = time.time()
                processed_pair_id, matching_result = self.process_single_pair((pair_id, pair_info))
                process_time = time.time() - process_start
                
                # 更新结果
                self.test_cases_pairs[pair_id]['matching_result'] = matching_result
                
                # 显示结果
                success = matching_result.get('success', False)
                method = matching_result.get('matching_method', 'unknown') if success else 'failed'
                
                if success:
                    success_count += 1
                    print(f"✅ 成功: 使用方法 '{method}' 匹配 (耗时: {process_time:.2f}秒)")
                else:
                    print(f"❌ 失败: {method} (耗时: {process_time:.2f}秒)")
                
                # 显示进度
                elapsed = time.time() - start_time
                avg_time = elapsed / idx
                remaining = avg_time * (total_count - idx)
                print(f"进度: {idx}/{total_count} ({idx/total_count*100:.1f}%) - 已用时: {elapsed:.1f}秒 - 预计剩余: {remaining:.1f}秒")
                
            except Exception as exc:
                error_count += 1
                print(f"❗ 处理测试用例 {pair_id} 时发生错误:")
                import traceback
                traceback.print_exc()
                
                # 记录错误但继续处理其他测试用例
                self.test_cases_pairs[pair_id]['matching_result'] = {
                    "success": False, 
                    "error": str(exc),
                    "matching_method": "error"
                }
        
        # 显示总结
        total_time = time.time() - start_time
        print(f"\n处理完成，共 {total_count} 个测试用例，耗时: {total_time:.1f}秒")
        print(f"成功: {success_count} ({success_count/total_count*100:.1f}%)")
        print(f"失败: {total_count - success_count - error_count} ({(total_count - success_count - error_count)/total_count*100:.1f}%)")
        print(f"错误: {error_count} ({error_count/total_count*100:.1f}%)")
        
        return self.test_cases_pairs
    
    
    def read_and_matching_failed_events_parallel(self, max_workers=None) -> Dict:
        """
        读取 failed 事件，使用多线程并行处理
        """

        if max_workers is None:
            max_workers = os.cpu_count() or 4

        total = len(self.test_cases_pairs)
        print(f"开始多线程处理 {total} 个测试用例对，使用 {max_workers} 个线程...")

        results_lock = threading.Lock()
        results = {}

        progress_queue = queue.Queue()
        SENTINEL = object()  # 退出信号

        def progress_monitor():
            completed = 0
            while True:
                try:
                    msg = progress_queue.get(timeout=1)
                except queue.Empty:
                    continue
                try:
                    if msg is SENTINEL:
                        # 标记并退出
                        return
                    print(msg)
                    if ("处理完成" in msg) or ("发生错误" in msg):
                        completed += 1
                        print(f"进度: {completed}/{total} ({completed/total*100:.1f}%)")
                finally:
                    # 确保每条消息都 task_done
                    progress_queue.task_done()

        monitor_thread = threading.Thread(target=progress_monitor)
        monitor_thread.start()

        def process_pair(pair_id, pair_info):
            try:
                progress_queue.put(f"正在处理 pair_id: {pair_id}")
                processed_pair_id, matching_result = self.process_single_pair((pair_id, pair_info))
                with results_lock:
                    results[pair_id] = matching_result
                success = matching_result.get('success', False)
                method = matching_result.get('matching_method', 'unknown') if success else 'failed'
                progress_queue.put(f"处理完成: pair_id={pair_id}, success={success}, method={method}")
                return pair_id, matching_result
            except Exception as exc:
                progress_queue.put(f"发生错误: pair_id={pair_id}, err={exc}")
                progress_queue.put(traceback.format_exc())
                with results_lock:
                    results[pair_id] = {"success": False, "error": str(exc)}
                return pair_id, results[pair_id]

        # 执行与等待
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_pair, pid, info): pid for pid, info in self.test_cases_pairs.items()}
            for _ in as_completed(futures):
                pass  # 只是确保所有任务都完成

        # 更新原始字典中的匹配结果
        for pair_id, matching_result in results.items():
            self.test_cases_pairs[pair_id]['matching_result'] = matching_result

        # 通知进度线程退出，并确保所有消息都被消费
        progress_queue.put(SENTINEL)
        progress_queue.join()
        monitor_thread.join()

        print(f"多线程处理完成，共处理 {len(results)} 个测试用例对")
        return self.test_cases_pairs


    
    def generate_html_content(self, original_png_path, original_element, matched_element_png_path, matched_element) -> str:
        """
        生成HTML内容
        
        Args:
            original_png_path: 原始PNG文件在tmp_images中的相对路径
            original_element: 原始元素
            matched_element_png_path: 匹配元素PNG文件在tmp_images中的相对路径
            matched_element: 匹配元素
        """
        # 安全地获取属性，避免KeyError
        original_resource_id = original_element.attrib.get('resource-id', 'N/A')
        matched_resource_id = matched_element.get('resource-id', 'N/A')

        original_text = original_element.attrib.get('text', 'N/A')
        matched_text = matched_element.get('text', 'N/A')

        original_content_description = original_element.attrib.get('content-desc', 'N/A')
        matched_content_description = matched_element.get('content-desc', 'N/A')

        original_class = original_element.attrib.get('class', 'N/A')
        matched_class = matched_element.get('class', 'N/A')

        # 添加CSS样式
        css_style = """
        <style>
            .container {
                display: flex;
                justify-content: space-between;
                width: 100%;
                margin-bottom: 30px;
            }
            .column {
                width: 48%;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 10px;
            }
            .attribute {
                background-color: #f5f5f5;
                padding: 10px;
                margin-bottom: 10px;
                border-radius: 5px;
            }
            .attribute p {
                margin: 5px 0;
                font-family: Arial, sans-serif;
            }
            .image {
                text-align: center;
            }
            .image img {
                object-fit: contain;
                height: 580px;
                width: 300px;
                border: 1px solid #ddd;
            }
            h2 {
                color: #333;
                font-family: Arial, sans-serif;
                margin-bottom: 10px;
            }
            .success {
                color: green;
                font-weight: bold;
            }
            .failure {
                color: red;
                font-weight: bold;
            }
        </style>
        """
        
        # 生成HTML内容
        html = css_style
        html += f"<h2>Matching Result: <span class='success'>Success</span></h2>"
        html += f"<div class='container'>"
        html += f"<div class='column'>"
        html += f"<h3>Original Element</h3>"
        html += f"<div class='attribute'>"
        html += f"<p><strong>Resource ID:</strong> {original_resource_id}</p>"
        html += f"<p><strong>Text:</strong> {original_text}</p>"
        html += f"<p><strong>Content Desc:</strong> {original_content_description}</p>"
        html += f"<p><strong>Class:</strong> {original_class}</p>"
        html += f"</div>"
        html += f"<div class='image'>"
        html += f"<img src='{original_png_path}' alt='Original Element'>"
        html += f"</div>"
        html += f"</div>"
        html += f"<div class='column'>"
        html += f"<h3>Matched Element</h3>"
        html += f"<div class='attribute'>"
        html += f"<p><strong>Resource ID:</strong> {matched_resource_id}</p>"
        html += f"<p><strong>Text:</strong> {matched_text}</p>"
        html += f"<p><strong>Content Desc:</strong> {matched_content_description}</p>"
        html += f"<p><strong>Class:</strong> {matched_class}</p>"
        html += f"</div>"
        html += f"<div class='image'>"
        html += f"<img src='{matched_element_png_path}' alt='Matched Element'>"
        html += f"</div>"
        html += f"</div>"
        html += f"</div>"
        return html
    
    
    
    
    def generate_html_report(self) -> None:
        """
        生成HTML报告 - 将所有测试用例放在一个HTML文件中
        
        1. 遍历test_cases_pairs，将所有测试用例的结果添加到同一个HTML文件中
        2. 每个测试用例包括：原始元素、新版元素、匹配结果、匹配方法
        3. 将PNG文件复制到tmp_images目录，并在HTML中引用相对路径
        """
        import shutil
        from datetime import datetime
        
        # 创建报告目录
        html_report_dir = os.path.join(self.dataset_dir, "html_report")
        tmp_image_dir = os.path.join(html_report_dir, "tmp_images")
        os.makedirs(tmp_image_dir, exist_ok=True)
        os.makedirs(html_report_dir, exist_ok=True)
        
        # 准备HTML头部
        report_html_path = os.path.join(html_report_dir, "matching_report.html")
        
        # HTML头部和样式
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>UI Matching Report</title>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 20px;
                    padding-bottom: 50px;
                }}
                h1, h2, h3 {{
                    color: #333;
                    font-family: Arial, sans-serif;
                    margin-bottom: 10px;
                }}
                .summary {{
                    background-color: #f8f8f8;
                    border: 1px solid #ddd;
                    padding: 15px;
                    margin-bottom: 30px;
                    border-radius: 5px;
                }}
                .summary table {{
                    border-collapse: collapse;
                    width: 100%;
                    font-size: 14px;
                }}
                .summary th, .summary td {{
                    border: 1px solid #ddd;
                    padding: 6px;
                    text-align: center;
                }}
                .summary th {{
                    background-color: #f2f2f2;
                }}
                /* 为了使表格更紧凑，设置一些列的宽度 */
                .summary table th:nth-child(1), .summary table th:nth-child(2) {{
                    width: 10%;
                }}
                .summary table th:nth-child(3), .summary table th:nth-child(4), .summary table th:nth-child(5) {{
                    width: 6%;
                }}
                /* 指标列使用更紧凑的宽度 */
                .summary table th:nth-child(n+6) {{
                    width: 5%;
                }}
                .case-container {{
                    border: 1px solid #ddd;
                    margin-bottom: 40px;
                    padding: 15px;
                    border-radius: 5px;
                    background-color: #fff;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .case-header {{
                    background-color: #f5f5f5;
                    padding: 10px;
                    margin-bottom: 15px;
                    border-radius: 5px;
                }}
                .container {{
                    display: flex;
                    justify-content: space-between;
                    width: 100%;
                    margin-bottom: 30px;
                }}
                .column {{
                    width: 48%;
                    border: 1px solid #ccc;
                    border-radius: 5px;
                    padding: 10px;
                }}
                .attribute {{
                    background-color: #f5f5f5;
                    padding: 10px;
                    margin-bottom: 10px;
                    border-radius: 5px;
                }}
                .attribute p {{
                    margin: 5px 0;
                    font-family: Arial, sans-serif;
                }}
                .image {{
                    text-align: center;
                }}
                .image img {{
                    object-fit: contain;
                    height: 580px;
                    width: 300px;
                    border: 1px solid #ddd;
                }}
                .success {{
                    color: green;
                    font-weight: bold;
                }}
                .failure {{
                    color: red;
                    font-weight: bold;
                }}
                .navigation {{
                    position: fixed;
                    top: 10px;
                    right: 10px;
                    background-color: #fff;
                    border: 1px solid #ddd;
                    padding: 10px;
                    border-radius: 5px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    max-height: 300px;
                    overflow-y: auto;
                    z-index: 1000;
                }}
                .navigation h3 {{
                    margin-top: 0;
                }}
                .navigation ul {{
                    list-style-type: none;
                    padding-left: 0;
                    margin: 0;
                }}
                .navigation li {{
                    margin-bottom: 5px;
                }}
                .navigation a {{
                    text-decoration: none;
                    color: #0066cc;
                }}
                .navigation a:hover {{
                    text-decoration: underline;
                }}
                #toc-toggle {{
                    display: block;
                    margin-bottom: 10px;
                    cursor: pointer;
                }}
                .hidden {{
                    display: none;
                }}
            </style>
            <script>
                function toggleTOC() {{
                    var toc = document.getElementById('toc-list');
                    var toggle = document.getElementById('toc-toggle');
                    if (toc.classList.contains('hidden')) {{
                        toc.classList.remove('hidden');
                        toggle.textContent = '隐藏目录';
                    }} else {{
                        toc.classList.add('hidden');
                        toggle.textContent = '显示目录';
                    }}
                }}
                
                // 页面加载后添加锚点导航
                document.addEventListener('DOMContentLoaded', function() {{
                    var cases = document.querySelectorAll('.case-container');
                    var tocList = document.getElementById('toc-list');
                    
                    cases.forEach(function(caseElement, index) {{
                        var caseId = 'case-' + (index + 1);
                        caseElement.id = caseId;
                        
                        var caseHeader = caseElement.querySelector('.case-header');
                        var recordApp = caseHeader.getAttribute('data-record-app');
                        var replayApp = caseHeader.getAttribute('data-replay-app');
                        
                        var listItem = document.createElement('li');
                        var link = document.createElement('a');
                        link.href = '#' + caseId;
                        link.textContent = recordApp + ' → ' + replayApp;
                        listItem.appendChild(link);
                        tocList.appendChild(listItem);
                    }});
                }});
            </script>
        </head>
        <body>
            <h1>UI Matching Report</h1>
            <p>Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
            
            <!-- 导航目录 -->
            <div class="navigation">
                <span id="toc-toggle" onclick="toggleTOC()">隐藏目录</span>
                <ul id="toc-list">
                    <!-- JavaScript will populate this list -->
                </ul>
            </div>
            
            <!-- 摘要部分 -->
            <div class="summary">
                <h2>Summary</h2>
                <table>
                    <tr>
                        <th>Record App</th>
                        <th>Replay App</th>
                        <th>Run Count</th>
                        <th>Result</th>
                        <th>Method</th>
                        <th>Resource ID</th>
                        <th>Text</th>
                        <th>Content Desc</th>
                        <th>Class</th>
                        <th>Visual</th>
                        <th>Bounds Strict</th>
                        <th>Bounds Loose</th>
                    </tr>
        """
        
        # 处理每个测试用例对
        success_count = 0
        total_count = 0
        case_contents = ""
        
        for pair_id, pair_info in self.test_cases_pairs.items():
            try:
                total_count += 1
                record_app, replay_app, run_count = pair_id
                failed_event_number = pair_info['replay_events_count'] + 1
                record_path = pair_info['record_path']
                replay_path = pair_info['replay_path']

                # 1. 获取原始元素信息
                original_event = f"{record_path}/events/event_{failed_event_number}.json"
                original_png = f"{record_path}/states/screen_{failed_event_number-1}_marked_original_element.png"
                original_xml = f"{record_path}/xmls/xml_{failed_event_number-1}.xml"
                
                # 检查文件是否存在
                if not os.path.exists(original_png) or not os.path.exists(original_event) or not os.path.exists(original_xml):
                    print(f"跳过 {pair_id}: 原始文件不存在")
                    continue
                
                # 解析原始元素
                original_tree = self.parse_xml_file(original_xml)
                original_element = self.find_original_element(original_event, original_tree)
                if original_element is None:
                    print(f"跳过 {pair_id}: 无法找到原始元素")
                    continue

                # 2. 获取匹配元素信息
                matched_element_png = f"{replay_path}/states/screen_{failed_event_number-1}_success.png"
                matching_result = pair_info.get('matching_result', {})
                matched_element = matching_result.get('matched_element', {})
                
                # 即使匹配失败，也显示在报告中
                if not os.path.exists(matched_element_png) or not matched_element:
                    # 匹配失败，设置默认值
                    success = False
                    method = "failed"
                    matched_element = {}  # 使用空字典表示没有匹配元素
                    # 使用一个默认的"匹配失败"图像
                    matched_element_png = matched_element_png = f"{replay_path}/states/screen_{failed_event_number-1}.png"
                else:
                    success = True
                    method = matching_result.get('matching_method', 'unknown')
                
                if success:
                    success_count += 1
                
                # 3. 复制图片到tmp_images目录
                # 生成唯一的文件名
                original_png_filename = f"original_{record_app}_{replay_app}_{run_count}_{failed_event_number-1}.png"
                matched_png_filename = f"matched_{record_app}_{replay_app}_{run_count}_{failed_event_number-1}.png"
                
                original_png_dest = os.path.join(tmp_image_dir, original_png_filename)
                matched_png_dest = os.path.join(tmp_image_dir, matched_png_filename)
                
                # 复制图片文件
                shutil.copy2(original_png, original_png_dest)
                
                # 如果匹配成功，复制匹配图片；如果失败，创建一个"失败"图片
                if os.path.exists(matched_element_png):
                    shutil.copy2(matched_element_png, matched_png_dest)
                else:
                    # 创建一个简单的"匹配失败"图片
                    try:
                        from PIL import Image, ImageDraw, ImageFont
                        # 创建一个与原始图像相同大小的空白图像
                        try:
                            original_img = Image.open(original_png)
                            width, height = original_img.size
                        except:
                            width, height = 300, 580  # 默认尺寸
                        
                        # 创建一个红色背景的图像
                        failed_img = Image.new('RGB', (width, height), (255, 240, 240))
                        draw = ImageDraw.Draw(failed_img)
                        
                        # 添加文字
                        text = "匹配失败"
                        # 尝试使用系统字体，如果失败则使用默认字体
                        try:
                            font = ImageFont.truetype("Arial", 40)
                        except:
                            font = ImageFont.load_default()
                        
                        # 计算文字位置使其居中
                        text_width, text_height = draw.textsize(text, font=font) if hasattr(draw, 'textsize') else (150, 40)
                        position = ((width - text_width) // 2, (height - text_height) // 2)
                        
                        # 绘制文字
                        draw.text(position, text, fill=(255, 0, 0), font=font)
                        
                        # 保存图像
                        failed_img.save(matched_png_dest)
                    except Exception as e:
                        print(f"创建失败图像时出错: {e}")
                        # 如果创建失败图像失败，复制原始图像作为后备方案
                        shutil.copy2(original_png, matched_png_dest)
                
                # 图片的相对路径（相对于HTML文件）
                original_png_rel_path = f"tmp_images/{original_png_filename}"
                matched_png_rel_path = f"tmp_images/{matched_png_filename}"
                
                # 4. 添加到摘要表格
                result_class = "success" if success else "failure"
                result_text = "Success" if success else "Failure"
                
                # 计算匹配指标
                metrics = {}
                if success:
                    # 只有在匹配成功时才计算指标
                    metrics = self.calculate_metrics(original_png, original_element, matched_element_png, matched_element)
                else:
                    # 匹配失败时，所有指标都设为N/A
                    metrics = {
                        "Resouce ID": "N/A",
                        "Text": "N/A",
                        "Content Desc": "N/A",
                        "Class": "N/A",
                        "Visual": "N/A",
                        "Bounds Strict": "N/A",
                        "Bounds Loose": "N/A",
                    }
                
                # 为每个指标设置CSS类
                resource_id_class = "success" if metrics["Resouce ID"] is True else ("failure" if metrics["Resouce ID"] is False else "")
                text_class = "success" if metrics["Text"] is True else ("failure" if metrics["Text"] is False else "")
                content_desc_class = "success" if metrics["Content Desc"] is True else ("failure" if metrics["Content Desc"] is False else "")
                class_class = "success" if metrics["Class"] is True else ("failure" if metrics["Class"] is False else "")
                visual_class = "success" if metrics["Visual"] is True else ("failure" if metrics["Visual"] is False else "")
                bounds_strict_class = "success" if metrics["Bounds Strict"] is True else ("failure" if metrics["Bounds Strict"] is False else "")
                bounds_loose_class = "success" if metrics["Bounds Loose"] is True else ("failure" if metrics["Bounds Loose"] is False else "")
                
                html_content += f"""
                <tr>
                    <td>{record_app}</td>
                    <td>{replay_app}</td>
                    <td>{run_count}</td>
                    <td class="{result_class}">{result_text}</td>
                    <td>{method}</td>
                    <td class="{resource_id_class}">{metrics["Resouce ID"]}</td>
                    <td class="{text_class}">{metrics["Text"]}</td>
                    <td class="{content_desc_class}">{metrics["Content Desc"]}</td>
                    <td class="{class_class}">{metrics["Class"]}</td>
                    <td class="{visual_class}">{metrics["Visual"]}</td>
                    <td class="{bounds_strict_class}">{metrics["Bounds Strict"]}</td>
                    <td class="{bounds_loose_class}">{metrics["Bounds Loose"]}</td>
                </tr>
                """
                
                # 5. 生成每个测试用例的详细内容
                # 安全地获取属性，避免KeyError
                original_resource_id = original_element.attrib.get('resource-id', 'N/A')
                matched_resource_id = matched_element.get('resource-id', 'N/A')

                original_text = original_element.attrib.get('text', 'N/A')
                matched_text = matched_element.get('text', 'N/A')

                original_content_description = original_element.attrib.get('content-desc', 'N/A')
                matched_content_description = matched_element.get('content-desc', 'N/A')

                original_class = original_element.attrib.get('class', 'N/A')
                matched_class = matched_element.get('class', 'N/A')
                
                case_contents += f"""
                <div class="case-container">
                    <div class="case-header" data-record-app="{record_app}" data-replay-app="{replay_app}">
                        <h2>Test Case: {record_app} → {replay_app} (Run {run_count})</h2>
                        <p><strong>Event Number:</strong> {failed_event_number}</p>
                        <p><strong>Result:</strong> <span class="{result_class}">{result_text}</span></p>
                        <p><strong>Method:</strong> {method}</p>
                    </div>
                    
                    <div class="container">
                        <div class="column">
                            <h3>Original Element</h3>
                            <div class="attribute">
                                <p><strong>Resource ID:</strong> {original_resource_id}</p>
                                <p><strong>Text:</strong> {original_text}</p>
                                <p><strong>Content Desc:</strong> {original_content_description}</p>
                                <p><strong>Class:</strong> {original_class}</p>
                            </div>
                            <div class="image">
                                <img src="{original_png_rel_path}" alt="Original Element">
                            </div>
                        </div>
                        <div class="column">
                            <h3>Matched Element</h3>
                            <div class="attribute">
                                <p><strong>Resource ID:</strong> {matched_resource_id}</p>
                                <p><strong>Text:</strong> {matched_text}</p>
                                <p><strong>Content Desc:</strong> {matched_content_description}</p>
                                <p><strong>Class:</strong> {matched_class}</p>
                            </div>
                            <div class="image">
                                <img src="{matched_png_rel_path}" alt="Matched Element">
                            </div>
                        </div>
                    </div>
                </div>
                """
                
            except Exception as e:
                print(f"处理 {pair_id} 时出错: {e}")
                import traceback
                traceback.print_exc()
        
        # 完成HTML内容
        success_rate = 0 if total_count == 0 else (success_count / total_count * 100)
        
        html_content += f"""
                </table>
                <p><strong>Summary:</strong> {success_count}/{total_count} successful matches ({success_rate:.1f}% success rate)</p>
            </div>
            
            <!-- 详细测试用例 -->
            <h2>Detailed Test Cases</h2>
            {case_contents}
        </body>
        </html>
        """
        
        # 写入HTML文件
        with open(report_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        print(f"HTML报告已生成到 {report_html_path}")
        print(f"成功匹配: {success_count}/{total_count} ({success_rate:.1f}%)")


            
        

    def calculate_metrics(self, original_png_path, original_element, matched_png_path, matched_element):
        """
        计算匹配元素与原始元素之间的各种指标
        
        参数:
            original_png_path: 原始元素的截图路径
            original_element: 原始元素的XML节点
            matched_png_path: 匹配元素的截图路径
            matched_element: 匹配元素的属性字典
            
        返回:
            包含7个指标的字典:
            - Resource ID: 资源ID是否匹配
            - Text: 文本是否匹配
            - Content Desc: 内容描述是否匹配
            - Class: 类名是否匹配
            - Visual: 视觉上是否相似
            - Bounds Strict: 边界是否完全一致
            - Bounds Loose: 边界是否有交集
        """
        print(f"original_png_path: {original_png_path}")
        print(f"matched_png_path: {matched_png_path}")
        original_png_path = original_png_path.replace("_marked_original_element", "")
        matched_png_path = matched_png_path.replace("_success", "")


        if not os.path.exists(original_png_path) or not os.path.exists(matched_png_path):
            return {
                "Resouce ID": 'NA',
                "Text": 'NA',
                "Content Desc": 'NA',
                "Class": 'NA',
                "Visual": 'NA',
                "Bounds Strict": 'NA',
                "Bounds Loose": 'NA',
            }

        # 1. 比较基本属性，计算前4个metrics
        original_resource_id = original_element.attrib.get('resource-id', '')
        matched_resource_id = matched_element.get('resource-id', '')
        resource_id_match = original_resource_id == matched_resource_id
        
        # 如果两者都为空，则为NA
        if original_resource_id == '' and matched_resource_id == '':
            resource_id_match = 'NA'
            
        original_text = original_element.attrib.get('text', '')
        matched_text = matched_element.get('text', '')
        text_match = original_text == matched_text
        
        # 如果两者都为空，则视为NA
        if original_text == '' and matched_text == '':
            text_match = 'NA'
            
        original_content_desc = original_element.attrib.get('content-desc', '')
        matched_content_desc = matched_element.get('content-desc', '')
        content_desc_match = original_content_desc == matched_content_desc
        
        # 如果两者都为空，则视为NA
        if original_content_desc == '' and matched_content_desc == '':
            content_desc_match = 'NA'
            
        original_class = original_element.attrib.get('class', '')
        matched_class = matched_element.get('class', '')
        class_match = original_class == matched_class

        # 如果两者都为空，则视为NA
        if original_class == '' and matched_class == '':
            class_match = 'NA'
        
        # 2. 计算边界相关指标
        bounds_strict_match = False
        bounds_loose_match = False

        original_bounds_str = original_element.attrib.get('bounds', '')
        matched_bounds_str = matched_element.get('bounds', '')
        
        # 创建Matcher实例来调用实例方法
        matcher = Matcher(None, None, None, None, None, None)  # 传递必要的参数
        
        original_bounds = matcher._parse_bounds(original_bounds_str)
        matched_bounds = matcher._parse_bounds(matched_bounds_str)

        # 2.1 计算边界重叠, bounds strict
        if original_bounds == matched_bounds:
            bounds_strict_match = True
        
        # 2.2 计算边界重叠, bounds loose
        overlap = matcher._calculate_overlap(original_bounds, matched_bounds)
        if overlap > 0:
            bounds_loose_match = True

        # 3. 计算视觉相似度
        visual_match = False
        print(f"original_bounds: {original_bounds}")
        print(f"matched_bounds: {matched_bounds}")
        try:
            # 3.1 读取图像
            original_img = read_image(original_png_path)
            replay_img = read_image(matched_png_path)
            print(f"original_img: {original_img}")
            print(f"replay_img: {replay_img}")
                
            # 3.2 裁剪元素图像
            original_x1, original_y1, original_x2, original_y2 = original_bounds
            candidate_x1, candidate_y1, candidate_x2, candidate_y2 = matched_bounds
            
            # 使用PIL的crop方法裁剪图像
            try:
                original_crop = original_img.crop((original_x1, original_y1, original_x2, original_y2))
                candidate_crop = replay_img.crop((candidate_x1, candidate_y1, candidate_x2, candidate_y2))
                
                # 检查裁剪后的图像是否为空
                if original_crop.width <= 1 or original_crop.height <= 1 or candidate_crop.width <= 1 or candidate_crop.height <= 1:
                    visual_match = 'NA'
            except Exception as e:
                print(f"裁剪图像错误: {e}")
        
            similarity = compute_ssim(original_crop, candidate_crop)
            print(f"similarity: {similarity}")
            if similarity > 0.9:
                visual_match = True
            
        except Exception as e:
            print(f"计算视觉相似度时出错: {e}")
                    
        return {
            "Resouce ID": resource_id_match,
            "Text": text_match,
            "Content Desc": content_desc_match,
            "Class": class_match,
            "Visual": visual_match,
            "Bounds Strict": bounds_strict_match,
            "Bounds Loose": bounds_loose_match,
        }


def main():
    """测试函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="解析测试用例目录")
    parser.add_argument("-dataset_dir", help="测试用例目录路径", default="../test_case1")
    parser.add_argument("-base-app", help="基础应用过滤器，例如 v6_4_1", default=None) #可以只看某一个base app
    parser.add_argument("-run-count", help="运行计数过滤器，例如 3", default=None)
    parser.add_argument("-max-workers", type=int, help="最大工作进程数，默认为None，将使用CPU核心数", default=30)
    parser.add_argument("-log-dir", help="日志目录路径，默认为'logs'", default="logs")
    parser.add_argument("-only-report-failed", help="只报告失败的测试用例对", action="store_true")
    parser.add_argument("-debug", help="启用详细调试输出", action="store_true", default=False)
    args = parser.parse_args()
    
    # 创建主进程的日志记录器
    main_logger = get_logger(name="UIMatch_main", log_dir=args.log_dir, force_new_handlers=True)
    main_logger.info(f"开始处理测试用例，参数：dataset_dir={args.dataset_dir}, base_app={args.base_app}, run_count={args.run_count}, max_workers={args.max_workers}")
    
    test_parser = Parser(args.dataset_dir, args.base_app, args.run_count)
    # 将日志记录器传递给Parser实例
    test_parser.logger = main_logger

    if args.only_report_failed == False:
        # 匹配failed events
        if args.debug == False:
            test_parser.read_and_matching_failed_events_parallel(max_workers=args.max_workers)
        else:
            test_parser.read_and_matching_failed_events_sequential()
    else:
        # 只生成报告时，从已有的结果文件中加载匹配信息
        for pair_id, pair_info in test_parser.test_cases_pairs.items():
            record_app, replay_app, run_count = pair_id
            replay_path = pair_info['replay_path']
            failed_event_number = pair_info.get('replay_events_count', 0) + 1
            
            # 尝试加载匹配结果文件
            result_json_path = f"{replay_path}/matched_element_{failed_event_number-1}.json"
            if os.path.exists(result_json_path):
                try:
                    with open(result_json_path, 'r', encoding='utf-8') as f:
                        matched_element = json.load(f)
                        matching_result = pair_info.get('matching_result', {})
                        matching_result['success'] = True
                        
                        # 尝试加载匹配方法
                        method_json_path = f"{replay_path}/matched_method_{failed_event_number-1}.json"
                        if os.path.exists(method_json_path):
                            try:
                                with open(method_json_path, 'r', encoding='utf-8') as mf:
                                    matching_method = json.load(mf)
                                    matching_result['matching_method'] = matching_method
                            except Exception as me:
                                print(f"加载匹配方法失败 {pair_id}: {me}")
                                matching_result['matching_method'] = "Unknown"
                        else:
                            matching_result['matching_method'] = "Unknown"
                            
                        matching_result['matched_element'] = matched_element
                        pair_info['matching_result'] = matching_result
                        print(f"已加载匹配结果: {pair_id}")
                except Exception as e:
                    print(f"加载匹配结果失败 {pair_id}: {e}")
            else:
                print(f"匹配结果文件不存在: {result_json_path}")   

    # 生成HTML报告
    test_parser.generate_html_report()
    
    

if __name__ == "__main__":
    main()