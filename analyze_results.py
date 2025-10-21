

import subprocess
import sys
import os

def run_check_output_script(parent_dir, target, min_json=100, min_states=99):
    """
    运行check_output.sh脚本并捕获输出
    
    Args:
        parent_dir (str): 父目录路径
        target (str): 目标类型 (record 或 replay)
        min_json (int): events下最少json文件数
        min_states (int): states下期望的状态数量
    
    Returns:
        tuple: (return_code, stdout, stderr)
    """
    # 构建命令
    script_path = os.path.join(os.path.dirname(__file__), "check_output.sh")
    cmd = [
        "bash", script_path,
        "-t", target,
        "-p", parent_dir,
        "-j", str(min_json),
        "-s", str(min_states)
    ]
    
    try:
        # 执行命令并捕获输出
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=parent_dir  # 设置工作目录
        )
        
        return result.returncode, result.stdout, result.stderr
        
    except Exception as e:
        return -1, "", str(e)

def run_check_output_interactive(parent_dir, target, min_json=100, min_states=99):
    """
    以交互方式运行check_output.sh脚本（实时显示输出）
    
    Args:
        parent_dir (str): 父目录路径
        target (str): 目标类型 (record 或 replay)
        min_json (int): events下最少json文件数
        min_states (int): states下期望的状态数量
    
    Returns:
        int: 返回码
    """
    script_path = os.path.join(os.path.dirname(__file__), "check_output.sh")
    cmd = [
        "bash", script_path,
        "-t", target,
        "-p", parent_dir,
        "-j", str(min_json),
        "-s", str(min_states)
    ]
    
    try:
        # 实时显示输出
        result = subprocess.run(cmd, cwd=parent_dir)
        return result.returncode
        
    except Exception as e:
        print(f"执行错误: {e}")
        return -1

if __name__ == "__main__":
    import argparse

    # 参数
    parser = argparse.ArgumentParser(description="分析结果并调用check_output.sh脚本")
    parser.add_argument("--parent_dir", type=str, required=True, help="父目录路径")
    parser.add_argument("--target", type=str, required=True, choices=["record", "replay"], help="目标类型")
    parser.add_argument("--min_json", type=int, default=100, help="events下最少json文件数")
    parser.add_argument("--min_states", type=int, default=99, help="states下期望的状态数量")
    parser.add_argument("--interactive", action="store_true", help="以交互方式运行（实时显示输出）")
    args = parser.parse_args()

    print(f"📁 工作目录: {args.parent_dir}")
    print(f"🎯 目标类型: {args.target}")
    print(f"📊 最小JSON文件数: {args.min_json}")
    print(f"📊 期望状态数: {args.min_states}")
    print("-" * 50)

    if args.interactive:
        # 交互模式：实时显示输出
        print("🔄 以交互模式运行check_output.sh...")
        return_code = run_check_output_interactive(
            args.parent_dir, 
            args.target, 
            args.min_json, 
            args.min_states
        )
        print(f"脚本执行完成，返回码: {return_code}")
    else:
        # 捕获模式：获取所有输出
        print("🔄 运行check_output.sh并捕获输出...")
        return_code, stdout, stderr = run_check_output_script(
            args.parent_dir, 
            args.target, 
            args.min_json, 
            args.min_states
        )
        
        print(f"返回码: {return_code}")
        print("\n=== 标准输出 ===")
        print(stdout)
        
        if stderr:
            print("\n=== 错误输出 ===")
            print(stderr)
        
        # 可以根据返回码和输出内容进行进一步处理
        if return_code == 0:
            print("✅ 脚本执行成功")
        else:
            print("❌ 脚本执行失败")
    