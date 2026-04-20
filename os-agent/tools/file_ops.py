"""
文件和目录操作 LangChain 工具。
"""

import os
from langchain_core.tools import tool

from tools.executor import get_executor

# 禁止读取的敏感文件列表
SENSITIVE_FILES = {
    "/etc/shadow",
    "/etc/gshadow",
    "/etc/shadow-",
    "/etc/gshadow-",
}


@tool
def list_directory(path: str) -> str:
    """查看指定目录的内容，包含权限、大小、修改时间等信息。

    Args:
        path: 要查看的目录路径
    """
    if ".." in path:
        return "错误：路径中不允许包含 '..'"

    executor = get_executor()
    result = executor.execute(f"ls -lah {path}")

    if not result.success:
        return f"目录查看失败: {result.stderr}"

    return result.stdout.strip()


@tool
def search_file(filename: str, search_path: str = "/") -> str:
    """在指定路径下按文件名搜索文件。

    Args:
        filename: 要搜索的文件名（支持通配符）
        search_path: 搜索起始路径，默认为根目录
    """
    if ".." in search_path:
        return "错误：路径中不允许包含 '..'"

    executor = get_executor()
    cmd = f'find {search_path} -maxdepth 10 -name "{filename}" 2>/dev/null | head -20'
    result = executor.execute(cmd, timeout=60)

    if not result.success and not result.stdout:
        return f"搜索失败: {result.stderr}"

    if not result.stdout.strip():
        return f"在 {search_path} 下未找到名为 '{filename}' 的文件"

    return f"搜索结果:\n{result.stdout.strip()}"


@tool
def show_file_content(path: str, lines: int = 50) -> str:
    """查看文件内容（默认前50行，最多200行）。

    Args:
        path: 文件路径
        lines: 显示行数，默认50行
    """
    # 安全校验：拒绝敏感文件
    normalized = os.path.normpath(path)
    if normalized in SENSITIVE_FILES:
        return f"错误：拒绝读取敏感文件 {path}，该文件包含系统安全信息"

    # 限制最多200行
    lines = min(lines, 200)

    executor = get_executor()
    result = executor.execute(f"head -n {lines} '{path}'")

    if not result.success:
        return f"文件读取失败: {result.stderr}"

    return result.stdout.strip()


@tool
def get_file_info(path: str) -> str:
    """查看文件的详细信息，包含大小、权限、所有者、时间戳等。

    Args:
        path: 文件路径
    """
    executor = get_executor()
    result = executor.execute(f"stat '{path}'")

    if not result.success:
        return f"文件信息获取失败: {result.stderr}"

    return result.stdout.strip()
