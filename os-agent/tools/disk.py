"""
磁盘相关 LangChain 工具。
"""

import os
from langchain_core.tools import tool

from tools.executor import get_executor


@tool
def check_disk_usage() -> str:
    """查看磁盘使用情况，返回各分区的挂载点、总容量、已用空间、可用空间和使用率。
    如果某分区使用率超过80%会额外给出警告提示。"""
    executor = get_executor()
    result = executor.execute("df -h")

    if not result.success:
        return f"磁盘查询失败: {result.stderr}"

    lines = result.stdout.strip().split("\n")
    if len(lines) < 2:
        return "磁盘信息为空"

    warnings = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 5:
            usage_str = parts[4].replace("%", "")
            try:
                usage = int(usage_str)
                if usage >= 80:
                    mount = parts[5] if len(parts) >= 6 else parts[0]
                    warnings.append(f"  [警告] {mount} 使用率已达 {usage}%，建议清理空间")
            except ValueError:
                pass

    output = result.stdout.strip()
    if warnings:
        output += "\n\n--- 磁盘使用警告 ---\n" + "\n".join(warnings)

    return output


@tool
def check_disk_inode() -> str:
    """查看磁盘 inode 使用情况，返回各分区的 inode 总数、已用、可用和使用率。"""
    executor = get_executor()
    result = executor.execute("df -i")

    if not result.success:
        return f"inode 查询失败: {result.stderr}"

    return result.stdout.strip()


@tool
def find_large_files(path: str = "/", min_size_mb: int = 100) -> str:
    """在指定路径下查找超过指定大小的大文件。

    Args:
        path: 搜索的目标路径，必须是绝对路径
        min_size_mb: 最小文件大小（MB），默认100MB
    """
    # 安全校验：必须是绝对路径，不允许路径遍历
    if not os.path.isabs(path):
        return "错误：路径必须是绝对路径"
    if ".." in path:
        return "错误：路径中不允许包含 '..'"

    executor = get_executor()
    cmd = f"find {path} -type f -size +{min_size_mb}M -exec ls -lhS {{}} + 2>/dev/null | head -20"
    result = executor.execute(cmd, timeout=60)

    if not result.success:
        return f"大文件查找失败: {result.stderr}"

    if not result.stdout.strip():
        return f"在 {path} 下未找到超过 {min_size_mb}MB 的文件"

    return f"超过 {min_size_mb}MB 的大文件:\n{result.stdout.strip()}"
