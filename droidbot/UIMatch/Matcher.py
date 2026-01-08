"""
匹配算法模块，用于比较原始UI和新版UI中的元素
"""

import os
import numpy as np
from lxml import etree as ET
from typing import Dict, List, Tuple, Optional, Any
from PIL import Image
from .utils import compute_ssim, read_image, get_element_xpath, compute_xpath_similarity, compute_bounds_similarity, encode_image_to_base64, draw_element_on_image, draw_original_element_on_image, draw_replay_element_on_image
from .utils import get_encoded_image, openai_chat, get_find_result, get_component_no
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib


class Matcher:
    def __init__(self, original_png, original_tree, original_element, replay_png, replay_tree, logger, cross_page=False):
        """
        初始化匹配器
        
        Args:
            original_png: 原始UI的截图路径
            original_xml_tree: 原始UI的XML树对象
            original_element: 原始UI中目标元素对象
            replay_png: 新版UI的截图路径
            replay_xml_tree: 新版UI的XML树对象
        """
        self.original_png = original_png
        self.original_tree = original_tree
        self.original_element = original_element
        self.replay_png = replay_png
        self.replay_tree = replay_tree
        root = self.replay_tree.getroot()
        _HindenWidgetFilter(root)


        # 用于相似度匹配的候选元素和得分
        self.candidates = []
        self.scores = []

        self.cross_page = cross_page

        # 用于相似度匹配的权重
        if cross_page == False:
            self.alpha = 0.4 # 视觉相似度权重
            self.beta = 0.3 # 属性相似度权重
            self.gamma = 0.2 # 空间相似度权重
        else:
            self.alpha = 0.5 # 视觉相似度权重
            self.beta = 0.5 # 属性相似度权重
            self.gamma = 0 # 空间相似度权重

        # 用于大模型匹配的
        self.top_n = 80
        self.model_name = "gpt-4.1-mini"
        self.model_type = "gpt"
        self.api_key = os.getenv("API_KEY")

        self.logger = logger
        self.app_name = None
    
    def matching(self, app_name=None) -> Dict[str, Any]:
        """
        执行匹配，按优先级尝试三种匹配策略
        
        Returns:
            匹配结果，包含匹配状态、bounds等信息
        """
        self.app_name = app_name

        # 0. 标注原始元素，方便调试
        original_bounds = self._parse_bounds(self.original_element.attrib.get("bounds", ""))
        original_img = read_image(self.original_png)
        marked_original_img = draw_original_element_on_image(original_img, original_bounds)
        original_output_filename = self.original_png.replace(".png", "_marked_original_element.png")
        marked_original_img.save(original_output_filename)


        # 1. 首先尝试精确匹配
        exact_result = self.exact_matching()
        if exact_result["success"]:
            return exact_result
        
        # 2. 如果精确匹配失败，尝试相似度匹配
        similarity_result = self.similarity_matching()
        if similarity_result["success"]:
            return similarity_result
        
        # 3. 如果相似度匹配也失败，尝试大模型匹配
        llm_result = self.llm_matching()
        return llm_result

    def exact_matching(self) -> Dict[str, Any]:
        """
        精确匹配策略，通过精确的属性和特征匹配元素
        依次尝试 content-desc, resource-id, text 三个属性
        唯一匹配则返回成功，匹配到多个或没匹配到则尝试下一个属性

        Returns:
            匹配结果，包含success和matched_element
        """
        root = self.replay_tree.getroot()

        def norm(v):
            # 把 None 或 "" 都归一到 None
            return v if v not in (None, "") else None

        def find_by_attr(attr_name, value, case_insensitive=False):
            """根据属性查找元素，返回 (匹配的元素, 匹配次数)"""
            if value is None:
                return None, 0
            matched = None
            count = 0
            for element in root.iter():
                cur_value = norm(element.attrib.get(attr_name))
                if cur_value is not None:
                    if case_insensitive:
                        is_match = cur_value.lower() == value.lower()
                    else:
                        is_match = cur_value == value
                    if is_match:
                        matched = element
                        count += 1
            return matched, count

        # 1. 通过 content-desc 精确匹配
        content_desc = norm(self.original_element.attrib.get("content-desc"))
        matched_element, matched_times = find_by_attr("content-desc", content_desc, case_insensitive=True)
        if matched_element is not None and matched_times == 1:
            return {
                "success": True,
                "matched_element": matched_element,
                "matching_method": "exact_content_desc"
            }

        # 2. 通过 resource-id 精确匹配
        resource_id = norm(self.original_element.attrib.get("resource-id"))
        matched_element, matched_times = find_by_attr("resource-id", resource_id, case_insensitive=False)
        if matched_element is not None and matched_times == 1:
            return {
                "success": True,
                "matched_element": matched_element,
                "matching_method": "exact_resource_id"
            }

        # 3. 通过 text 精确匹配
        text = norm(self.original_element.attrib.get("text"))
        matched_element, matched_times = find_by_attr("text", text, case_insensitive=True)
        if matched_element is not None and matched_times == 1:
            return {
                "success": True,
                "matched_element": matched_element,
                "matching_method": "exact_text"
            }

        # 都没有唯一匹配
        return {
            "success": False
        }
    
    
    def similarity_matching(self) -> Dict[str, Any]:
        """
        相似度匹配策略，通过多维度相似度比较找到最佳匹配

        1. 视觉相似度
        2. 结构相似度
        3. 空间相似度

        """
        self.candidates = self._candidate_elements()
        if len(self.candidates) == 0:
            return {
                "success": False
            }
        self.scores = []
        self.all_matched_elements = []
        for candidate in self.candidates:
            score1 = self._compute_visual_similarity(candidate)
            if score1 > 0.95:
                self.all_matched_elements.append(candidate)
            
            score2 = self._compute_structure_similarity(candidate)
            
            score3 = self._compute_space_similarity(candidate)
            
            score4 = self._compute_attribute_similarity(candidate)
            # 视觉 > 文本 > 空间 > 结构
            total_score = self.alpha * score1 + self.beta * score4 + self.gamma * score3 + (1 - self.alpha - self.beta - self.gamma) * score2
            self.scores.append(total_score)

        if len(self.all_matched_elements) == 1:
            return {
                "success": True,
                "matched_element": self.all_matched_elements[0],
                "matching_method": "visual_similarity"
            }
        
        return {
            "success": False
        }

    def _compute_attribute_similarity(self, candidate_element) -> float:
        """计算属性相似度: text"""
        original_text = self.original_element.attrib.get("text")
        candidate_text = candidate_element.attrib.get("text")
        original_content_desc = self.original_element.attrib.get("content-desc")
        candidate_content_desc = candidate_element.attrib.get("content-desc")
        original_resource_id = self.original_element.attrib.get("resource-id")
        candidate_resource_id = candidate_element.attrib.get("resource-id")
        original_str = f"{original_text}|{original_content_desc}|{original_resource_id}"
        candidate_str = f"{candidate_text}|{candidate_content_desc}|{candidate_resource_id}"
        seq_matcher = difflib.SequenceMatcher(None, original_str.lower().split("|"), candidate_str.lower().split("|"))
        return round(seq_matcher.ratio(), 4)


    def _candidate_elements(self) -> List[ET.Element]:
        """
        查找可能的候选元素，并根据一系列规则进行过滤
        
        过滤规则:
        1. visible=true的保留，invisible的元素去除
        2. 父子边界重叠0.95的，只保留一个叶子结点
        3. 尺寸极小的元素（面积是2-3像素的），去除
        4. 面积是original element的5倍以上的元素，去除
        5. 过滤掉系统UI元素（状态栏和导航栏）
        
        Returns:
            过滤后的候选元素列表
        """
        # 获取原始元素的尺寸信息
        original_bounds = self._parse_bounds(self.original_element.attrib.get("bounds", ""))
        if not original_bounds:
            print("无法解析原始元素的bounds")
            return []
                    
        # 初始候选列表 - 获取所有结点元素
        root = self.replay_tree.getroot()

        initial_candidates = list(root.iter()) # 获取所有元素
        print("initial_candidates", len(initial_candidates))
        
        # 应用过滤规则
        filtered_candidates = []

        
        for element in initial_candidates:
            if element.attrib.get("covered", "false") == "true" and self.app_name is not None and self.app_name != "com.appmindlab.nano": # 已经被其他元素覆盖了
                continue

            # 规则1: 只保留可见元素
            if element.attrib.get("visible-to-user", "true").lower() == "false":
                continue
            
            # 规则5: 过滤掉系统UI元素（状态栏和导航栏）
            package = element.attrib.get("package", "")
            if package == "com.android.systemui":
                continue
                
            # 规则2: 解析元素的bounds
            bounds = self._parse_bounds(element.attrib.get("bounds", ""))
            if not bounds:
                continue
                
            # 规则3: 过滤掉极小元素
            area = self._calculate_area(bounds)
            if area < 10:  # 面积小于10像素的元素过滤掉
                continue
                
            # 规则4: 过滤掉过大元素
            # if area > original_area * 5:
            #     continue

            # 规则6: 过滤掉宽<5 或者高<5 的元素
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            if width < 10 or height < 10:
                continue
                
            # 规则5: 对于父子边界重叠度高的，只保留叶子节点
            is_leaf_or_unique = True
            
            # 检查该元素是否有子元素，且边界重叠度高
            for child in element:
                child_bounds = self._parse_bounds(child.attrib.get("bounds", ""))
                if child_bounds:
                    overlap_ratio = self._calculate_overlap(bounds, child_bounds) / area if area > 0 else 0
                    if overlap_ratio > 0.95:  # 边界重叠度超过95%
                        is_leaf_or_unique = False
                        break
            
            if is_leaf_or_unique:
                filtered_candidates.append(element)
        
        leaf_candidates = []
        for candidate in filtered_candidates:
            if len(candidate) > 0: # leaf node
                continue
            leaf_candidates.append(candidate)

        print("filtered_candidates", len(filtered_candidates))
        print("leaf_candidates", len(leaf_candidates))
        
        if len(leaf_candidates) == 0:
            return filtered_candidates
        else:
            return leaf_candidates
        
    def _parse_bounds(self, bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
        """
        解析Android UI元素的bounds字符串，格式为[x1,y1][x2,y2]
        
        Args:
            bounds_str: bounds属性字符串
            
        Returns:
            (left, top, right, bottom)元组，解析失败则返回None
        """
        try:
            # 提取坐标值
            import re
            match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                return (x1, y1, x2, y2)
        except Exception as e:
            print(f"解析bounds失败: {bounds_str}, 错误: {e}")
        return None
        
    def _calculate_area(self, bounds: Tuple[int, int, int, int]) -> int:
        """
        计算元素的面积
        
        Args:
            bounds: (left, top, right, bottom)元组
            
        Returns:
            元素的面积（像素数）
        """
        left, top, right, bottom = bounds
        width = max(0, right - left)
        height = max(0, bottom - top)
        return width * height
        
    def _calculate_overlap(self, bounds1: Tuple[int, int, int, int], 
                          bounds2: Tuple[int, int, int, int]) -> int:
        """
        计算两个元素边界的重叠面积
        
        Args:
            bounds1: 第一个元素的(left, top, right, bottom)
            bounds2: 第二个元素的(left, top, right, bottom)
            
        Returns:
            重叠区域的面积
        """
        left1, top1, right1, bottom1 = bounds1
        left2, top2, right2, bottom2 = bounds2
        
        # 计算重叠区域
        overlap_left = max(left1, left2)
        overlap_top = max(top1, top2)
        overlap_right = min(right1, right2)
        overlap_bottom = min(bottom1, bottom2)
        
        # 检查是否有重叠
        if overlap_right > overlap_left and overlap_bottom > overlap_top:
            return (overlap_right - overlap_left) * (overlap_bottom - overlap_top)
        return 0
    
    def _compute_visual_similarity(self, candidate_element) -> float:
        """
        计算原始元素和候选元素在图像上的视觉相似度
        使用SSIM(结构相似性指数)计算图像相似度
        
        Args:
            candidate_element: 候选元素
            
        Returns:
            视觉相似度得分 (0.0-1.0)
        """
        try:
            # 1. 获取原始元素和候选元素的bounds
            original_bounds = self._parse_bounds(self.original_element.attrib.get("bounds", ""))
            candidate_bounds = self._parse_bounds(candidate_element.attrib.get("bounds", ""))
                
            # 2. 读取图像
            original_img = read_image(self.original_png)
            replay_img = read_image(self.replay_png)
                
            # 3. 裁剪元素图像
            original_x1, original_y1, original_x2, original_y2 = original_bounds
            candidate_x1, candidate_y1, candidate_x2, candidate_y2 = candidate_bounds
            
            # 使用PIL的crop方法裁剪图像
            try:
                original_crop = original_img.crop((original_x1, original_y1, original_x2, original_y2))
                candidate_crop = replay_img.crop((candidate_x1, candidate_y1, candidate_x2, candidate_y2))
                
                # 检查裁剪后的图像是否为空
                if original_crop.width <= 1 or original_crop.height <= 1 or candidate_crop.width <= 1 or candidate_crop.height <= 1:
                    return 0.0
            except Exception as e:
                print(f"裁剪图像错误: {e}")
                return 0.0
        
            similarity = compute_ssim(original_crop, candidate_crop)
            
            return similarity
            
        except Exception as e:
            print(f"计算视觉相似度时出错: {e}")
            return 0.0

    def _compute_structure_similarity(self, candidate_element) -> float:
        """计算结构相似度，两个xpath的相似度"""
        # 1.获取原始元素和候选元素的xpath
        original_xpath = get_element_xpath(self.original_tree, self.original_element)
        candidate_xpath = get_element_xpath(self.replay_tree, candidate_element)
        
        # 2.计算两个xpath的相似度
        similarity = compute_xpath_similarity(original_xpath, candidate_xpath)
        return similarity


    def _compute_space_similarity(self, candidate_element) -> float:
        """计算空间相似度"""
        original_bounds = self._parse_bounds(self.original_element.attrib.get("bounds", ""))
        candidate_bounds = self._parse_bounds(candidate_element.attrib.get("bounds", ""))
        
        # 2.计算两个bounds的相似度
        similarity = compute_bounds_similarity(original_bounds, candidate_bounds)
        return similarity

  
  
    def llm_matching(self) -> Dict[str, Any]:
        """
        大模型匹配策略，使用大型语言模型进行UI元素匹配
        
        Returns:
            匹配结果，包含success和matched_element
        """
        if len(self.candidates) == 0:
            return {
                "success": False
            }

        # 1. 标记候选元素
        marked_replay_img = self._mark_candidates_on_image()
        output_filename = self.replay_png.replace(".png", "_marked_candidates.png") #存储在原始的下面了
        marked_replay_img.save(output_filename)
        
        # 2. 标注原始元素
        original_bounds = self._parse_bounds(self.original_element.attrib.get("bounds", ""))
        original_img = read_image(self.original_png)
        marked_original_img = draw_original_element_on_image(original_img, original_bounds)
        original_output_filename = self.original_png.replace(".png", "_marked_original_element.png")
        marked_original_img.save(original_output_filename)

        # 3. 原始element的图片
        original_element_img = original_img.crop(original_bounds)
        # save方便调试
        original_element_img_filename = self.original_png.replace(".png", "_original_element.png")
        original_element_img.save(original_element_img_filename)
        
        # 4. 判断页面是否相关
        # if self.cross_page == False:
        #     found_page_related = self._check_page_found(marked_original_img, original_element_img, marked_replay_img)
        #     self.logger.info(f"found_page_related: {found_page_related}")
        #     if found_page_related == "NO":
        #         return {
        #             "success": False
        #         }

        # 4. 如果页面相关，查找元素
        self.logger.info(f"original_png: {self.original_png}")
        try_times = 3
        element_id = None
        candidate_elements = []

        # 并发执行 LLM 调用
        with ThreadPoolExecutor(max_workers=try_times) as executor:
            futures = [
                executor.submit(self._find_element, marked_original_img, original_element_img, marked_replay_img)
                for _ in range(try_times)
            ]
            for future in as_completed(futures):
                candidate_element_id = future.result()
                if candidate_element_id is not None:
                    candidate_elements.append(candidate_element_id)

        # for _ in range(try_times):
        #     candidate_element_id = self._find_element(marked_original_img, original_element_img, marked_replay_img)
        #     if candidate_element_id is not None:
        #         candidate_elements.append(candidate_element_id)

        # voting for the best element
        if len(candidate_elements) == try_times:
            element_id = self._voting_for_best_element(candidate_elements)

        
        if element_id is not None and element_id>=0 and element_id<len(self.candidates):
            found_element = self.candidates[int(element_id)]
            corresponding_score = self.scores[int(element_id)]
            # if corresponding_score < 0.4:
            #     return {
            #         "success": False
            #     }
            #     return self._rollback_matching()
            # else:
            # print(f"found_element: {self.scores[int(element_id)]}")

            
            return {
                "success": True,
                "matched_element": found_element,
                "matching_method": "llm"
            }

        return {
            "success": False
        }

    def _voting_for_best_element(self, ids) -> int:
        
        return Counter(ids).most_common(1)[0][0]

        

    def _rollback_matching(self) -> Dict[str, Any]:
        """
        回滚匹配，返回score最高的一个
        """
        # 返回score最高的一个
        best_score = max(self.scores)
        if best_score < 0.7:
            return {
                "success": False
            }
        best_index = self.scores.index(best_score)
        best_candidate = self.candidates[best_index]
        return {
            "success": True,
            "matched_element": best_candidate,
            "matching_method": "hybrid_similarity",
            "score": best_score
        }
    
    def _find_element(self, marked_original_img, original_element_img, marked_replay_img) -> Dict[str, Any]:
        """
        查找元素
        """
        # 1. encode image to base64
        marked_original_img_base64 = get_encoded_image(marked_original_img)
        marked_replay_img_base64 = get_encoded_image(marked_replay_img)
        original_element_img_base64 = get_encoded_image(original_element_img)

        # 2. construct prompt
        system_prompt, user_prompt = self._construct_find_element_llm_prompt(marked_original_img_base64, original_element_img_base64, marked_replay_img_base64)

        # 3. call llm
        if self.model_type == "gpt" or self.model_type == "deepseek":
            response, token_usage = openai_chat(system_prompt, user_prompt, self.api_key, self.model_name, self.model_type)
            self.logger.info(f"response: {response}")
            self.logger.info(f"token_usage: {token_usage}")
            
            # 解析LLM返回的组件ID
            element_id_str = get_component_no(response)
            self.logger.info(f"LLM返回的组件ID: {element_id_str}")
            
            # 处理可能的多个ID情况
            try:
                # 如果返回了多个ID（如"2, 3, 4"），取第一个
                if ',' in element_id_str:
                    element_ids = [id.strip() for id in element_id_str.split(',')]
                    self.logger.info(f"LLM返回了多个ID: {element_ids}，将使用第一个: {element_ids[0]}")
                    element_id = int(element_ids[0])
                else:
                    element_id = int(element_id_str)
                
                return element_id
            except (ValueError, IndexError) as e:
                self.logger.error(f"解析组件ID失败: {e}，原始返回: {element_id_str}")
                # 返回None表示解析失败
                return None
        else:
            self.logger.error(f"不支持的模型类型: {self.model_type}")
            return None

    def _check_page_found(self, marked_original_img, original_element_img, marked_replay_img) -> bool:
        """
        判断页面是否相关
        
        Args:
            original_img: 原始元素图像对象
            replay_img: 标记候选元素的图像对象
        """
        # 1. encode image to base64
        marked_original_img_base64 = get_encoded_image(marked_original_img)
        marked_replay_img_base64 = get_encoded_image(marked_replay_img)
        original_element_img_base64 = get_encoded_image(original_element_img)

        # 2. construct prompt
        system_prompt, user_prompt = self._construct_page_found_llm_prompt(marked_original_img_base64, original_element_img_base64, marked_replay_img_base64)
        
        # 3. call llm
        if self.model_type == "gpt" or self.model_type == "deepseek":
            response, token_usage = openai_chat(system_prompt, user_prompt, self.api_key, self.model_name, self.model_type)
            find_result = get_find_result(response)
            return find_result
        else:
            print("Unsupported model type")
            return False
        
    
    def _mark_candidates_on_image(self) -> Image.Image:
        """
        在新版UI截图上标记候选元素
        
        Returns:
            (marked_image_path, marked_components_dict): 标记后的图像路径和组件字典
        """
        if len(self.candidates) == 0: # 如果候选元素列表为空，则进行相似度匹配，为了初始化self.candidates和self.scores
            self.similarity_matching()

        # 创建一个临时图像路径
        replay_img = read_image(self.replay_png)
        
        # 创建(索引, 得分)对的列表
        indexed_scores = [(i, score) for i, score in enumerate(self.scores)]
        
        # 按得分降序排序
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        
        # 取前N个得分最高的候选元素的索引
        top_n = min(self.top_n, len(indexed_scores))  # 最多标记self.top_n个元素
        top_n_candidates_indexes = [idx for idx, _ in indexed_scores[:top_n]]

        for i in range(len(self.candidates)):
            if i in top_n_candidates_indexes:
                element = self.candidates[i]
                bounds_str = element.attrib.get("bounds", "")
                if not bounds_str:
                    continue
                replay_img = draw_replay_element_on_image(replay_img, bounds_str, id=i)

        return replay_img
            
    
    def _construct_page_found_llm_prompt(self, marked_original_img_base64, original_element_img_base64, marked_replay_img_base64) -> Tuple[str, Dict]:
        """
        构建LLM提示
        """
        analyze_ori_scenarios_prompt = f"""
I will provide you with the original application version's screenshot (marked with red boxes indicating an original UI component) and the original UI component Figure.


* Original Screenshot
```
please see the Figure 1.
```

* Original UI component Figure
```
please see the UI component figure.
```
"""
    
        analyze_update_effects_prompt = f"""
I will provide you with the updated application version's screenshot, Please analyze whether the marked components in the old version screenshot can be found in the new version screenshot.

* Updated Screenshot
```
please see the Figure 2.
```
"""
    
        system_prompt = """
You are an Android UI testing expert.

Your task is to determine whether the UPDATED screen represents the SAME **PAGE-LEVEL INTENT / FUNCTIONAL STAGE** as the ORIGINAL screen — not whether specific UI components or content appear identical.

This task focuses on **functional relevance**, not exact UI matching.

---

## What “Page Found” Means (IMPORTANT)

A page should be considered FOUND (YES) if:
- The UPDATED screen serves the SAME PURPOSE as the ORIGINAL screen
- The user has reached the SAME FUNCTIONAL STAGE in the workflow
- A tester would consider the navigation successful for continuing the same test case

---

## Strong YES Rules (Based on Testing Practice)

You should IMMEDIATELY return YES if **any** of the following holds:

1. **Identical or functionally equivalent core UI components are present**
   - Even if surrounding content differs
   - Even if displayed text or data is different

2. **The page is a LIST-type or FEED-type page**
   - Examples: news list, article list, item list, browsing pages
   - Ignore the specific list items or content
   - If the page clearly supports the same browsing/reading purpose, return YES

These cases indicate the tester has successfully reached the intended page,
regardless of content differences.

---

## Focus on PAGE INTENT, not CONTENT DETAILS

You MUST focus on the **INTENT and PURPOSE of the page**, for example:
- Reading a news article
- Browsing a list of news or items
- Viewing content details
- Accessing a feature page
- Performing a configuration or settings task

IGNORE:
- Differences in displayed content (e.g., different news text)
- Differences between individual list items
- Visual style changes
- UI restructuring
- Minor layout or navigation differences

---

## What Does NOT Count as Page Found (NO)

Return NO only if:
- The UPDATED screen represents a DIFFERENT functional stage
- The user is on an unrelated feature or page
- The navigation failed to reach the intended page purpose

---

## Your Task

1. Analyze the ORIGINAL screen and infer its **page-level intent**.
2. Analyze the UPDATED screen and infer its **page-level intent**.
3. Decide whether both screens represent the SAME intent / purpose.

EXAMPLE OUTPUT:

```result.md
### Analyze_Process  
Analyze the UI-related info between original and updated version, and explain whether the marked components in the old version screenshot can be found in the new version screenshot..

### Your Answer
YES or NO
```

"""

        user_prompt = {}

        user_prompt['ori_analyze'] = [marked_original_img_base64] + [original_element_img_base64] + [
            {"type": "text", "text": analyze_ori_scenarios_prompt}
        ]

        user_prompt['update_analyze'] = [marked_replay_img_base64] + [
            {"type": "text", "text": analyze_update_effects_prompt}
        ]

        return system_prompt, user_prompt
    
    def _extract_component_no(self, text: str) -> str:
        """
        从LLM响应中提取组件编号
        
        Args:
            text: LLM响应文本
            
        Returns:
            组件编号
        """
        import re
        
        # 优先匹配 "### Matched_UI_No" 后一行中的中括号内容
        match = re.search(r'### Matched_UI_No\s*\n\s*\[(.*?)\]', text)
        
        if match:
            result = match.group(1)
            return result
        else:
            # fallback：找最后一个 [] 内的内容
            matches = re.findall(r'\[(.*?)\]', text)
            if matches:
                result = matches[-1]  # 取最后一个
                return result
        
        return ""

#     def _construct_find_element_llm_prompt(self, marked_original_img_base64, original_element_img_base64, marked_replay_img_base64) -> Tuple[str, Dict]:
#         """
#         构建LLM提示
#         """

#         analyze_ori_scenarios_prompt = f"""
# I will provide you with the original application version's screenshot (marked with red boxes indicating an original UI component) and the original UI component Figure.


# * Original Screenshot
# ```
# please see the Figure 1.
# ```

# * Original UI component Figure
# ```
# please see the UI component figure.
# ```
# """
    
#         analyze_update_effects_prompt = f"""
# I will provide you with the updated application version's screenshot. Different UI components are marked with green boxes and assigned a numerical sequence number. You need to analyze the screenshots of the Updated version and identify an UI component that is most similar to the original UI component of the Original version, then provide the component sequence numbers.

# * Updated Screenshot
# ```
# please see the Figure 2.
# ```
# """
    
#         system_prompt = """
# You are an Android developer who is skilled at analyzing component location relationships by combining GUI.

# There is a special task scenario that you need to solve. In the software version iteration, an UI component of the updated version may change compared to the original version. You need to browse the original version of the UI component information, and then analyze the updated version of the UI component information to find the best matched UI number in the Updated Screenshot.

# First, you will obtain the original version of the UI component information, including screenshots of the original component (marked with red boxes indicating the original UI component).
# Second, you will obtain the updated version of the UI component information, including screenshots of the updated component (marked with green boxes indicating all updated UI components). You will need to analyze screenshots of two versions, to determine a best matched UI component's Number in Updated Screenshot.
# Finally, you need return the best matched UI component's Number in the Updated Screenshot.

# EXAMPLE OUTPUT:

# ```result.md
# ### Analyze_Process  
# Analyze the UI-related info between original and updated version of the UI component, and explain how to find the matched UI component's Number in Updated Screenshot.

# ### Matched_UI_No
# [18]
# ```

# """

#         user_prompt = {}

#         user_prompt['ori_analyze'] = [marked_original_img_base64] + [original_element_img_base64] + [
#             {"type": "text", "text": analyze_ori_scenarios_prompt}
#         ]

#         user_prompt['update_analyze'] = [marked_replay_img_base64] + [
#             {"type": "text", "text": analyze_update_effects_prompt}
#         ]

#         return system_prompt, user_prompt


# Jan 7, 81% success rate
#     def _construct_find_element_llm_prompt(self, marked_original_img_base64, original_element_img_base64, marked_replay_img_base64) -> Tuple[str, Dict]:
#         """
#         构建LLM提示
#         """

#         analyze_ori_scenarios_prompt = f"""
# I will provide you with the original application version's screenshot (marked with red boxes indicating an original UI component) and the original UI component Figure.


# * Original Screenshot
# ```
# please see the Figure 1.
# ```

# * Original UI component Figure
# ```
# please see the UI component figure.
# ```
# """
    
#         analyze_update_effects_prompt = f"""
# I will provide you with the updated application version's screenshot. Different UI components are marked with green boxes and assigned a numerical sequence number. You need to analyze the screenshots of the Updated version and identify an UI component that is most similar to the original UI component of the Original version, then provide the component sequence numbers.

# * Updated Screenshot
# ```
# please see the Figure 2.
# ```
# """
    
#         system_prompt = """
# You are an Android UI analysis expert. Your task is to identify which UI component in the UPDATED screen corresponds to the SAME FUNCTION as the original UI element.

# ## Core Matching Principle
# You must select the UI component that represents the SAME *functional meaning* as the original element — not necessarily the one that looks the most similar.

# Appearance, structure, and position may change across versions, but FUNCTION remains the anchor signal. Use visual/layout cues only as *secondary evidence*.

# ## What “Functional Match” Means
# When selecting the matched component, prioritize:

# 1. **Semantic equivalence**  
#    - Focus on the purpose of the control (e.g., enabling dark mode, opening a menu, choosing a theme, activating an option).
#    - The semantic meaning should be the closest to the original intent.

# 2. **Functional category alignment**  
#    UI components often evolve but stay in the same functional family.  
#    Examples:  
#    - checkbox → switch  
#    - switch → dialog containing radio choices  
#    - menu item → reorganized navigation entry  
#    - toggle → multi-option selector  

# 3. **Semantic strength alignment**  
#    When the original widget expresses a *strong meaning* (“Force Dark Theme”), and the updated version has multiple options:  
#    - pick the option that best matches the *assertive/off/on meaning*,  
#      **not** the one that merely preserves current selection.  
#    (Do NOT match based on which option is currently highlighted or selected.)

# 4. **State-independent matching**  
#    Ignore which option is currently selected in the updated version.  
#    Selection state is NOT part of functional equivalence.

# 5. **Auxiliary visual cues**  
#    Only use appearance, relative placement, or grouping to help disambiguate **after**
#    semantic meaning is considered.

# ## Important Constraints
# - Do NOT choose an option merely because it is currently selected.
# - Do NOT rely on visual similarity alone.
# - Do NOT rely on exact wording; wording may evolve (“Force Dark Theme” → “Dark”).
# - Your answer must reflect functional purpose, not UI form.

# ## Output
# Provide the NUMBER of the updated UI component that best matches the original element.

# Output format:
# ```result.md
# ### Analyze_Process
# (Your reasoning here)

# ### Matched_UI_No
# [18]
# ```

# """

#         user_prompt = {}

#         user_prompt['ori_analyze'] = [marked_original_img_base64] + [original_element_img_base64] + [
#             {"type": "text", "text": analyze_ori_scenarios_prompt}
#         ]

#         user_prompt['update_analyze'] = [marked_replay_img_base64] + [
#             {"type": "text", "text": analyze_update_effects_prompt}
#         ]

#         return system_prompt, user_prompt


    def _construct_find_element_llm_prompt(self, marked_original_img_base64, original_element_img_base64, marked_replay_img_base64) -> Tuple[str, Dict]:
        """
        构建LLM提示
        """

        analyze_ori_scenarios_prompt = f"""
I will provide you with the original version's screenshot (marked with red boxes indicating an original UI widget).

* Original Screenshot
```
Please see the above Figure.
```
"""
        analyze_ori_element_prompt = f"""
I will provide you with the original UI widget Figure.

* Original UI widget Figure
```
Please see the above Figure.
```
"""
    
        analyze_update_effects_prompt = f"""
I will provide you with the updated version's screenshot. Different UI widgets are marked with green boxes and assigned a numerical sequence number.

* Updated Screenshot
```
Please see the above Figure.
```
"""
    
        system_prompt = """
You are an Android UI analysis expert with experience in UI evolution across app versions.
Your task is to identify which UI widget on the updated screenshot corresponds to the original UI widget from the old version.

## Matching Principle
- Select the UI widget that a user would most likely recognize as the same function, based on its purpose and role on the screen.
- You may use the surrounding UI context on the current screen (e.g., page title, section grouping, nearby controls) to infer the role and intent of each UI widget.
- Visual appearance, layout, or wording may change across versions. Use them only as supporting cues when intent is ambiguous.

## Output
Provide the NUMBER of the updated UI widget that best matches the original widget.

Output format:
```result.md
### Analyze_Process
(Your reasoning here)

### Matched_UI_No
[18]
```

"""

        user_prompt = {}

        user_prompt['ori_analyze'] = [marked_original_img_base64] + [{"type": "text", "text": analyze_ori_scenarios_prompt}] + [original_element_img_base64] + [{"type": "text", "text": analyze_ori_element_prompt}]

        user_prompt['update_analyze'] = [marked_replay_img_base64] + [
            {"type": "text", "text": analyze_update_effects_prompt}
        ]

        return system_prompt, user_prompt






import re
from typing import List, Dict
import uiautomator2
import xml.etree.ElementTree as ET
import rtree
from lxml import etree

class _HindenWidgetFilter:
    def __init__(self, root: etree._Element):
        # self.global_drawing_order = 0
        self._nodes = []

        self.idx = rtree.index.Index()
        try:
            self.set_covered_attr(root)
        except Exception as e:
            import traceback, uuid
            traceback.print_exc()

    def _iter_by_drawing_order(self, ele: etree._Element):
        """
        iter by drawing order (DFS)
        """
        if ele.tag == "node":
            yield ele

        children = list(ele)
        try:
            children.sort(key=lambda e: int(e.get("drawing-order", 0)))
        except (TypeError, ValueError):
            pass

        for child in children:
            yield from self._iter_by_drawing_order(child)

    def set_covered_attr(self, root: etree._Element):
        self._nodes: List[etree._Element] = list()
        for e in self._iter_by_drawing_order(root):
            # e.set("global-order", str(self.global_drawing_order))
            # self.global_drawing_order += 1
            e.set("covered", "false")

            # algorithm: filter by "clickable"
            clickable = (e.get("clickable", "false") == "true")
            _raw_bounds = e.get("bounds")
            if _raw_bounds is None:
                continue
            bounds = _get_bounds(_raw_bounds)
            if clickable:
                covered_widget_ids = list(self.idx.contains(bounds))
                if covered_widget_ids:
                    for covered_widget_id in covered_widget_ids:
                        node = self._nodes[covered_widget_id]
                        node.set("covered", "true")
                        self.idx.delete(
                            covered_widget_id,
                            _get_bounds(self._nodes[covered_widget_id].get("bounds"))
                        )

            cur_id = len(self._nodes)
            center = [
                (bounds[0] + bounds[2]) / 2,
                (bounds[1] + bounds[3]) / 2
            ]
            self.idx.insert(
                cur_id,
                (center[0], center[1], center[0], center[1])
            )
            self._nodes.append(e)

def _get_bounds(raw_bounds):
    pattern = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
    m = re.match(pattern, raw_bounds)
    try:
        bounds = [int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))]
    except Exception as e:
        print(f"raw_bounds: {raw_bounds}", flush=True)
        raise RuntimeError(e)

    return bounds

if __name__ == "__main__":
    llm_response = """
    ### Analyze_Process
The original UI component is a large, rounded rectangular blue button with a "+" (plus) sign. Its functional meaning is to increment or increase the counter displayed on the screen.

In the updated screenshot, the UI components are numbered 0 to 6. Components 2, 3, 4, 5, and 6 correspond to the top bar icons and title. Component 1 is a text prompt ("Try clicking on the number!"). Component 0 is the large number display showing "0" and is not interactive for incrementing.

There is no explicit "+" button visible in the updated screen. However, the text prompt (component 1) suggests that the user can increment the counter by clicking on the number itself (component 0). This indicates that the increment function that was originally a "+" button is now integrated into the number display UI element itself.

Thus, the component that functionally replaces the original "+" button is the number display area (component 0) which now also acts as the increment trigger.

### Matched_UI_No
[0]
    """
    element_id_str = get_component_no(llm_response)
    print(element_id_str)

    element_id = int(element_id_str)
    print(element_id)

    if element_id is not None and element_id>=0 and element_id<7:
        print("element_id is valid")
    else:
        print("element_id is invalid")
        
        