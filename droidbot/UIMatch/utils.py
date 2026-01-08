import xml.etree.ElementTree as ET
from typing import Tuple, Optional
import numpy as np
from skimage.metrics import structural_similarity as ssim
from PIL import Image, ImageDraw, ImageFont, ImageOps
import difflib
import math
import base64
from math import sqrt
from openai import OpenAI
import re
import os
from bs4 import BeautifulSoup


def trim_whitespace(image, threshold=235):
    """
    裁剪图像周围的留白
    
    Args:
        image: PIL图像对象
        threshold: 像素亮度阈值，高于此值被视为留白
        
    Returns:
        裁剪后的图像
    """
    # 转换为灰度图
    img_gray = image.convert('L')
    img_array = np.array(img_gray)
    
    # 找出非留白区域
    mask = img_array < threshold
    
    # 如果整个图像都是留白，返回原图
    if not np.any(mask):
        return image
    
    # 找出非留白区域的边界
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    y_min, y_max = np.where(rows)[0][[0, -1]]
    x_min, x_max = np.where(cols)[0][[0, -1]]
    
    # 确保裁剪区域至少有1像素的边距
    y_min = max(0, y_min - 1)
    y_max = min(img_array.shape[0] - 1, y_max + 1)
    x_min = max(0, x_min - 1)
    x_max = min(img_array.shape[1] - 1, x_max + 1)
    
    # 裁剪图像
    return image.crop((x_min, y_min, x_max + 1, y_max + 1))


def compute_ssim(image1, image2, trim=True):
    """
    计算两个图像的结构相似度
    
    Args:
        image1: 第一个PIL图像对象
        image2: 第二个PIL图像对象
        trim: 是否裁剪留白，默认为True
        
    Returns:
        结构相似度得分 (0-1)
    """
    # 裁剪留白
    # if trim:
    #     image1 = trim_whitespace(image1)
    #     image2 = trim_whitespace(image2)

    # 新增亮度均衡化
    image1 = ImageOps.equalize(image1.convert('L'))
    image2 = ImageOps.equalize(image2.convert('L'))
    
    # 转换为灰度图并调整大小
    image1 = image1.convert('L').resize((128, 128))
    image2 = image2.convert('L').resize((128, 128))
    
    # 转换为NumPy数组
    arr1 = np.array(image1)
    arr2 = np.array(image2)
    
    # 计算SSIM
    score, _ = ssim(arr1, arr2, full=True)
    return round(score, 4)

def read_image(image_path):
    image = Image.open(image_path)
    return image

def draw_element_on_image(image, bounds):
    """
    在图片上标注元素的bounds
    
    Args:
        image: PIL图像对象或图片路径
        bounds: 元素的bounds，格式为(x1, y1, x2, y2)或"[x1,y1][x2,y2]"
        id: 元素的编号，默认为None
    Returns:
        标注后的图片对象
    """
    image = image.copy()  # 防止修改原图
    # 创建绘图对象
    draw = ImageDraw.Draw(image)
    
    # 解析bounds
    if isinstance(bounds, str):
        # 如果是字符串格式"[x1,y1][x2,y2]"，解析为坐标
        import re
        match = re.findall(r"\[(\d+),(\d+)\]", bounds)
        if match and len(match) == 2:
            x1, y1 = int(match[0][0]), int(match[0][1])
            x2, y2 = int(match[1][0]), int(match[1][1])
            bounds = (x1, y1, x2, y2)
    
    # 提取坐标
    x1, y1, x2, y2 = bounds
    # 绘制矩形
    draw.rectangle([x1, y1, x2, y2], outline="red", width=3)
    
    return image

def compute_xpath_similarity(xpath1: str, xpath2: str) -> float:
    """
    计算两个 XPath 字符串的相似度，使用 difflib 的序列匹配
    返回 [0,1] 区间，相似度越高越接近1
    """
    seq_matcher = difflib.SequenceMatcher(None, xpath1.replace('//','/'), xpath2.replace('//','/'))
    return round(seq_matcher.ratio(), 4)

def get_element_xpath(tree: ET.ElementTree, element: ET.Element) -> str:
    """
    获取元素的xpath，使用class name + index的格式
    
    Args:
        tree: XML元素树
        element: 要获取XPath的元素
        
    Returns:
        元素的XPath字符串，格式如: /root/LinearLayout[0]/FrameLayout[1]/TextView[0]
    """
    if element is None:
        return ""
    
    # 获取根节点
    root = tree.getroot()
    
    # 构建从根到目标元素的路径
    path_elements = []
    current = element
    
    # 从当前元素向上遍历到根节点
    while current is not None and current != root:
        parent = current.getparent()
        if parent is None:
            break
        
        # 获取当前元素的class
        class_name = current.attrib.get('class', '')
        if '.' in class_name:
            # 如果是完整类名，只取最后一部分
            class_name = class_name.split('.')[-1]
        
        # 查找同类型的兄弟节点，计算索引
        siblings = [child for child in parent if child.attrib.get('class', '').endswith(class_name)]
        index = siblings.index(current)
        
        # 将当前节点添加到路径
        path_elements.append(f"{class_name}[{index}]")
        
        # 移动到父节点
        current = parent
    
    # 添加根节点
    path_elements.append("root")
    
    # 反转路径并组合成XPath字符串
    path_elements.reverse()
    xpath = "/" + "/".join(path_elements)
    
    return xpath


def compute_bounds_similarity(ori_bounds, target_bounds, img_diag_norm=3000.0):
    """
    计算两个 bounds 的相似度（位置+尺寸差异），返回 [0,1]
    """
    try:
        x1_1, y1_1, x2_1, y2_1 = ori_bounds
        x1_2, y1_2, x2_2, y2_2 = target_bounds
    except:
        return 0.0

    # 位置中心点距离
    cx1, cy1 = (x1_1 + x2_1) / 2, (y1_1 + y2_1) / 2
    cx2, cy2 = (x1_2 + x2_2) / 2, (y1_2 + y2_2) / 2
    pos_dist = math.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2)

    # 尺寸差距
    w1, h1 = x2_1 - x1_1, y2_1 - y1_1
    w2, h2 = x2_2 - x1_2, y2_2 - y1_2
    size_dist = math.sqrt((w1 - w2) ** 2 + (h1 - h2) ** 2)

    # 总差值
    total_dist = pos_dist + size_dist

    # 转换为相似度（越小越相似，归一化）
    similarity = 1 - min(total_dist / img_diag_norm, 1.0)
    return round(similarity, 4)


def encode_image_to_base64(image_path_or_obj):
    """
    将图像编码为base64字符串
    
    Args:
        image_path_or_obj: 图像路径或PIL Image对象
        
    Returns:
        base64编码的字符串
    """
    import io
    import base64
    
    if isinstance(image_path_or_obj, str):
        # 如果是路径，从文件读取
        with open(image_path_or_obj, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
    else:
        # 如果是PIL Image对象，转换为字节流
        buffer = io.BytesIO()
        image_path_or_obj.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def draw_original_element_on_image(image, bounds, bg_color=(255, 0, 0), bg_alpha=128):
    """
    在图片上标注原始元素的bounds，使用红色边框和"original UI component"标签
    
    Args:
        image: PIL图像对象或图片路径
        bounds: 元素的bounds，格式为(x1, y1, x2, y2)或"[x1,y1][x2,y2]"
        bg_color: 背景矩形颜色 (R,G,B)，默认为红色(255, 0, 0)
        bg_alpha: 背景矩形透明度 0=完全透明, 255=不透明，默认为128
        
    Returns:
        标注后的图片对象
    """

    image = image.copy()  # 防止修改原图
    
    # 解析bounds
    if isinstance(bounds, str):
        # 如果是字符串格式"[x1,y1][x2,y2]"，解析为坐标
        import re
        match = re.findall(r"\[(\d+),(\d+)\]", bounds)
        if match and len(match) == 2:
            x1, y1 = int(match[0][0]), int(match[0][1])
            x2, y2 = int(match[1][0]), int(match[1][1])
            bounds = (x1, y1, x2, y2)
    
    # 提取坐标
    x1, y1, x2, y2 = bounds
    
    # 计算组件大小和对角线长度（用于动态调整边框宽度）
    w, h = x2 - x1, y2 - y1
    diag = sqrt(w**2 + h**2)
    
    # 动态边框宽度
    border_width = int(max(2, min(12, diag * 0.02)))
    
    # 创建绘图对象
    draw = ImageDraw.Draw(image)
    
    # 绘制矩形框
    draw.rectangle([x1, y1, x2, y2], outline=bg_color, width=border_width)
    
    # ===== 添加文字标记 =====
    label = "original UI component"
    
    # 动态字体大小（随框大小变化）
    font_size = int(max(16, min(32, diag * 0.08)))
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)  # macOS
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except:
                font = ImageFont.load_default()
    
    # 获取文字大小
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    # 文字放在矩形框上方，居中对齐
    text_x = x1 + (w - text_w) // 2
    text_y = max(0, y1 - text_h - 6)  # 避免超出图片顶部
    
    # 如果上方空间不够，放到矩形框内部顶部
    if text_y < 0:
        text_y = y1 + 6
        text_x = x1 + (w - text_w) // 2
    
    # 背景框（半透明）
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    padding = 4
    bg_coords = [
        text_x - padding, text_y - padding,
        text_x + text_w + padding, text_y + text_h + padding
    ]
    overlay_draw.rectangle(bg_coords, fill=(*bg_color, bg_alpha))  # 使用自定义颜色和透明度
    image = Image.alpha_composite(image, overlay)
    
    # 绘制文字（白色）
    draw = ImageDraw.Draw(image)
    draw.text((text_x, text_y), label, fill="white", font=font)
    
    return image

def draw_replay_element_on_image(image, bounds, id, bg_color=(0, 128, 0), bg_alpha=160):
    """
    在图片上标注新版元素的bounds，使用绿色边框和序号标识
    
    Args:
        image: PIL图像对象
        bounds: 元素的bounds，格式为(x1, y1, x2, y2)或"[x1,y1][x2,y2]"
        id: 元素的编号
        bg_color: 背景矩形颜色 (R,G,B)，默认为绿色(0, 128, 0)
        bg_alpha: 背景矩形透明度 0=完全透明, 255=不透明，默认为160
        
    Returns:
        标注后的图片对象
    """
    image = image.copy()  # 防止修改原图
    # 解析bounds
    if isinstance(bounds, str):
        # 如果是字符串格式"[x1,y1][x2,y2]"，解析为坐标
        import re
        match = re.findall(r"\[(\d+),(\d+)\]", bounds)
        if match and len(match) == 2:
            x1, y1 = int(match[0][0]), int(match[0][1])
            x2, y2 = int(match[1][0]), int(match[1][1])
            bounds = (x1, y1, x2, y2)
    
    # 提取坐标
    x1, y1, x2, y2 = bounds
    
    # 计算组件大小和对角线长度（用于动态调整边框宽度）
    w, h = x2 - x1, y2 - y1
    diag = sqrt(w**2 + h**2)
    
    # 动态边框宽度
    border_width = int(max(2, min(8, diag * 0.02)))
    
    # 创建绘图对象
    draw = ImageDraw.Draw(image)
    
    # 绘制矩形框
    draw.rectangle([x1, y1, x2, y2], outline=bg_color, width=border_width)  # 使用自定义颜色
    
    # 标号处理
    label = str(id)
    
    # 动态字体大小
    font_size = int(max(18, min(48, diag * 0.18)))
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)  # macOS
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except:
                font = ImageFont.load_default()
    
    # 获取文字大小
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    # 智能选择标号位置
    image_width, image_height = image.size
    
    # 计算标号面积与组件面积的比例
    label_area = (text_w + 8) * (text_h + 8)
    component_area = w * h
    occlusion_ratio = label_area / component_area if component_area > 0 else 1
    
    # 判断是放在内部还是外部
    min_area_threshold = 10000  # 最小面积阈值
    max_occlusion_ratio = 0.15  # 最大遮挡比例（15%）
    
    use_external_position = (
        component_area < min_area_threshold or 
        occlusion_ratio > max_occlusion_ratio or
        w < text_w + 16 or  # 组件宽度不够放标号
        h < text_h + 16     # 组件高度不够放标号
    )
    
    if use_external_position:
        # 外部位置：组件框右上角外侧
        text_x = x2 + 4
        text_y = y1
        
        # 边界检查
        if text_x + text_w > image_width:
            # 右侧超出边界，尝试放在左侧
            text_x = x1 - text_w - 4
            if text_x < 0:
                # 左侧也超出边界，尝试放在上方
                text_x = x1
                text_y = y1 - text_h - 4
                if text_y < 0:
                    # 上方也不够，放在下方
                    text_x = x1
                    text_y = y2 + 4
                    if text_y + text_h > image_height:
                        # 最后回退到内部右上角
                        text_x = x2 - text_w - 4 if (x2 - x1) >= text_w + 8 else x1 + 4
                        text_y = y1 + 4
    else:
        # 内部位置：组件框内部右上角
        text_x = x2 - text_w - 4 if (x2 - x1) >= text_w + 8 else x1 + 4
        text_y = y1 + 4
    
    # 最终边界检查
    if text_y + text_h > image_height:
        text_y = image_height - text_h - 4
    if text_y < 0:
        text_y = 4
    if text_x < 0:
        text_x = 4
    if text_x + text_w > image_width:
        text_x = image_width - text_w - 4
    
    # 背景矩形坐标
    padding = 4
    bg_coords = [
        text_x - padding, 
        text_y - padding, 
        text_x + text_w + padding, 
        text_y + text_h + padding
    ]
    
    # 如果图像是RGBA模式，使用半透明背景
    if image.mode == "RGBA":
        # 半透明背景
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle(bg_coords, fill=(*bg_color, bg_alpha))  # 使用自定义颜色和透明度
        image = Image.alpha_composite(image, overlay)
        
        # 绘制文字（白色）
        draw = ImageDraw.Draw(image)
    else:
        # 不支持半透明，直接绘制实心背景
        draw.rectangle(bg_coords, fill=bg_color)  # 使用自定义颜色
    
    # 绘制文字（白色）
    draw.text((text_x, text_y), label, fill="white", font=font)
    
    return image

def get_encoded_image(image, model_type="gpt"):
    """
    将PIL图像对象编码为适合不同LLM模型API的格式
    
    Args:
        image: PIL图像对象
        model_type: 模型类型，支持 "gpt", "qwen", "claude"
        
    Returns:
        适合指定模型的图像数据字典
    """
    import io
    import base64

    
    base64_image = encode_image_to_base64(image)
    
    # 确定图像类型，默认为PNG
    image_type = "png"
    
    # 根据模型类型返回不同格式
    if "gpt" in model_type.lower() or "o4-mini" in model_type.lower() or "deepseek" in model_type.lower() or "qwen" in model_type.lower():
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/{image_type};base64,{base64_image}"}
        }
    elif "qwen" in model_type.lower():  # 另一种Qwen格式
        return {
            "type": "image",
            "image": f"data:image;base64,{base64_image}"
        }
    elif "claude" in model_type.lower():
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": f"image/{image_type}",
                "data": base64_image
            }
        }
    else:
        # 默认格式
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/{image_type};base64,{base64_image}"}
        }


def openai_chat(system_prompt, user_prompt, api_key, model_name, model_type):
    # client = OpenAI(api_key=api_key, base_url="https://api.chatanywhere.tech/v1/")
    client = OpenAI(api_key=api_key)

    if 'deepseek' in model_type:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        # client = OpenAI(api_key=api_key, base_url="https://api.chatanywhere.tech/v1/")

    
    if 'o4-mini' in model_name or 'gpt-5' in model_name or 'gpt-4.1-mini' in model_name:
        temperature = 0.8

    # find documents
    if system_prompt:
        completions = client.beta.chat.completions.parse(
            model=model_name,
            temperature=temperature,
            messages=[
                {
                    "role": "system", 
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt['ori_analyze']
                },
                {
                    "role": "user",
                    "content": user_prompt['update_analyze']
                }
            ]
        )
        results = ''
        for key, completion in enumerate(completions.choices):
            key += 1
            result = completion.message.content
            results += result

    token_usage = {}
    usage = completions.usage
    token_usage['base_model'] = model_name
    token_usage['prompt_tokens'] = usage.prompt_tokens
    token_usage['completion_tokens'] = usage.completion_tokens
    token_usage['total_tokens'] = usage.total_tokens

    return results, token_usage  # Return a dict of results

def get_find_result(analyze_result: str) -> str:
    """
    解析page found的分析结果，返回YES或NO
    """
    find_result = ''

    try:
        # 匹配 Your Answer 段落后面的 YES 或 NO（支持换行和 Markdown 格式）
        m = re.search(
            r'(?is)^\s*(?:#+\s*)?Your\s+Answer\b[\s:：]*([\s\S]*?)\b(YES|NO)\b',
            analyze_result,
            re.M
        )
        if m:
            # 捕获到的结果
            answer_block = m.group(1) + m.group(2)
            # 优先 YES
            if re.search(r'\bYES\b', answer_block, re.I):
                find_result = 'YES'
            elif re.search(r'\bNO\b', answer_block, re.I):
                find_result = 'NO'
    except Exception:
        find_result = ''

    return find_result



def get_component_no(text):
    """
    从LLM响应中提取组件编号
    """
    # 优先匹配 "### Matched_UI_No" 后一行中的中括号内容
    match = re.search(r'### Matched_UI_No\s*\n\s*\[(.*?)\]', text)

    if match:
        result = match.group(1)
        print(result)
        return result
    else:
        # fallback：找最后一个 [] 内的内容
        matches = re.findall(r'\[(.*?)\]', text)
        if matches:
            result = matches[-1]  # 取最后一个
            print(result)
            return result

    print("没有找到匹配内容")
    return ''

def post_process_html_report(sample_path):
    """
    摘要表格后面再加四列：
    如果是success, 比较 Original Element 和 Matched Element 的 Resource ID, Text, Content Desc, Class 是否相同，如果相同，则 True，否则 False
    - Resource ID True or False
    - Text True or False
    - Content Desc True or False
    - Class True or False
    """


    html_report_path = os.path.join(sample_path, "matching_report.html")
    if not os.path.exists(html_report_path):
        print(f"HTML报告文件不存在: {html_report_path}")
        return
        
    with open(html_report_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # 使用BeautifulSoup解析HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 查找摘要表格
    summary_table = soup.select_one('.summary table')
    if not summary_table:
        print("未找到摘要表格")
        return
    
    # 添加新的表头列
    header_row = summary_table.select_one('tr')
    header_row.append(soup.new_tag('th'))
    header_row.contents[-1].string = 'Resource ID Match'
    header_row.append(soup.new_tag('th'))
    header_row.contents[-1].string = 'Text Match'
    header_row.append(soup.new_tag('th'))
    header_row.contents[-1].string = 'Content Desc Match'
    header_row.append(soup.new_tag('th'))
    header_row.contents[-1].string = 'Class Match'
    
    # 查找所有测试用例
    case_containers = soup.select('.case-container')
    
    # 创建一个字典来存储每个测试用例的属性匹配结果
    case_results = {}
    
    # 遍历每个测试用例，提取属性比较结果
    for case in case_containers:
        # 获取测试用例标识信息
        header = case.select_one('.case-header')
        if not header:
            continue
            
        record_app = header.get('data-record-app')
        replay_app = header.get('data-replay-app')
        run_count_elem = header.select_one('h2')
        
        # 提取run_count
        run_count = None
        if run_count_elem:
            run_match = re.search(r'Run (\d+)', run_count_elem.text)
            if run_match:
                run_count = run_match.group(1)
        
        if not (record_app and replay_app and run_count):
            continue
            
        case_id = (record_app, replay_app, run_count)
        
        # 检查是否成功匹配
        result_span = header.select_one('.success, .failure')
        is_success = result_span and 'success' in result_span.get('class', [])
        
        if not is_success:
            # 如果匹配失败，所有属性比较都是False
            case_results[case_id] = {
                'resource_id': False,
                'text': False,
                'content_desc': False,
                'class': False
            }
            continue
        
        # 获取原始元素和匹配元素的属性
        original_attrs = case.select('.column')[0].select('.attribute p') if len(case.select('.column')) > 0 else []
        matched_attrs = case.select('.column')[1].select('.attribute p') if len(case.select('.column')) > 1 else []
        
        # 提取属性值
        original_values = {}
        matched_values = {}
            
        for attr in original_attrs:
            if 'Resource ID:' in attr.text:
                # 使用更精确的方式提取值
                parts = attr.text.split('Resource ID:', 1)
                if len(parts) > 1:
                    value = parts[1].strip()
                    original_values['resource_id'] = '' if value == 'N/A' or value == "" else value
            elif 'Text:' in attr.text:
                parts = attr.text.split('Text:', 1)
                if len(parts) > 1:
                    value = parts[1].strip()
                    original_values['text'] = '' if value == 'N/A' or value == "" else value
            elif 'Content Desc:' in attr.text:
                parts = attr.text.split('Content Desc:', 1)
                if len(parts) > 1:
                    value = parts[1].strip()
                    original_values['content_desc'] = '' if value == 'N/A' or value == "" else value
            elif 'Class:' in attr.text:
                parts = attr.text.split('Class:', 1)
                if len(parts) > 1:
                    value = parts[1].strip()
                    original_values['class'] = '' if value == 'N/A' or value == "" else value
        
            
        for attr in matched_attrs:
            if 'Resource ID:' in attr.text:
                parts = attr.text.split('Resource ID:', 1)
                if len(parts) > 1:
                    value = parts[1].strip()
                    matched_values['resource_id'] = '' if value == 'N/A' or value == "" else value
            elif 'Text:' in attr.text:
                parts = attr.text.split('Text:', 1)
                if len(parts) > 1:
                    value = parts[1].strip()
                    matched_values['text'] = '' if value == 'N/A' or value == "" else value
            elif 'Content Desc:' in attr.text:
                parts = attr.text.split('Content Desc:', 1)
                if len(parts) > 1:
                    value = parts[1].strip()
                    matched_values['content_desc'] = '' if value == 'N/A' or value == "" else value
            elif 'Class:' in attr.text:
                parts = attr.text.split('Class:', 1)
                if len(parts) > 1:
                    value = parts[1].strip()
                    matched_values['class'] = '' if value == 'N/A' or value == "" else value
        
        # 初始化当前case_id的结果字典
        case_results[case_id] = {}
        
        # 比较属性值
        if original_values.get('resource_id') == '' and matched_values.get('resource_id') == '':
            case_results[case_id]['resource_id'] = 'NA'
        else:
            case_results[case_id]['resource_id'] = original_values.get('resource_id') == matched_values.get('resource_id')

        if original_values.get('text') == '' and matched_values.get('text') == '':
            case_results[case_id]['text'] = 'NA'
        else:
            case_results[case_id]['text'] = original_values.get('text') == matched_values.get('text')

        if original_values.get('content_desc') == '' and matched_values.get('content_desc') == '':
            case_results[case_id]['content_desc'] = 'NA'
        else:
            case_results[case_id]['content_desc'] = original_values.get('content_desc') == matched_values.get('content_desc')

        if original_values.get('class') == '' and matched_values.get('class') == '':
            case_results[case_id]['class'] = 'NA'
        else:
            case_results[case_id]['class'] = original_values.get('class') == matched_values.get('class')

        
        # 调试输出 - 每个测试用例的属性值
        # print(f"Case {case_id}:")
        # print(f"  original_values: {original_values}")
        # print(f"  matched_values: {matched_values}")
        # print(f"  match results: {case_results[case_id]}")

    
    # 更新摘要表格中的每一行
    data_rows = summary_table.select('tr')[1:]  # 跳过表头行
    
    for row in data_rows:
        cells = row.select('td')
        if len(cells) < 5:
            continue
            
        record_app = cells[0].text.strip()
        replay_app = cells[1].text.strip()
        run_count = cells[2].text.strip()
        result = cells[3].text.strip()
        
        case_id = (record_app, replay_app, run_count)
        
        # 如果是失败的情况或找不到对应的测试用例结果，添加False
        if result == 'Failure' or case_id not in case_results:
            for _ in range(4):
                row.append(soup.new_tag('td'))
                row.contents[-1].string = 'NA'
                row.contents[-1]['class'] = ['failure']
        else:
            # 添加资源ID匹配结果
            row.append(soup.new_tag('td'))
            row.contents[-1].string = str(case_results[case_id]['resource_id'])
            row.contents[-1]['class'] = ['success'] if case_results[case_id]['resource_id'] else ['failure']
            
            # 添加文本匹配结果
            row.append(soup.new_tag('td'))
            row.contents[-1].string = str(case_results[case_id]['text'])
            row.contents[-1]['class'] = ['success'] if case_results[case_id]['text'] else ['failure']
            
            # 添加内容描述匹配结果
            row.append(soup.new_tag('td'))
            row.contents[-1].string = str(case_results[case_id]['content_desc'])
            row.contents[-1]['class'] = ['success'] if case_results[case_id]['content_desc'] else ['failure']
            
            # 添加类匹配结果
            row.append(soup.new_tag('td'))
            row.contents[-1].string = str(case_results[case_id]['class'])
            row.contents[-1]['class'] = ['success'] if case_results[case_id]['class'] else ['failure']
    
    # 更新CSS样式，添加新列的样式
    style_tag = soup.select_one('style')
    if style_tag:
        new_style = """
                .match-true {
                    color: green;
                    font-weight: bold;
                }
                .match-false {
                    color: red;
                    font-weight: bold;
                }
        """
        style_tag.append(new_style)
    
    # 生成新的HTML文件
    processed_html_path = os.path.join(sample_path, "matching_report_processed.html")
    with open(processed_html_path, 'w', encoding='utf-8') as f:
        f.write(str(soup))
    
    print(f"处理后的HTML报告已生成: {processed_html_path}")

if __name__ == "__main__":
    parent_dir = "/Users/ssw/Desktop/yiheng"
    #获取下面所有的
    # for app_name in os.listdir(parent_dir):
        
    #     if os.path.isdir(os.path.join(parent_dir, app_name)):
    #         print(f"Processing: {app_name}")
    #         post_process_html_report(os.path.join(parent_dir, app_name))
    
    post_process_html_report("/Users/ssw/Downloads/html_report")
    