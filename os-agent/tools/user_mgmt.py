"""
用户管理 LangChain 工具。
"""

import json
import re
from langchain_core.tools import tool

from tools.executor import get_executor


@tool
def list_users() -> str:
    """查看系统中可登录的正常用户列表，包含用户名、UID和家目录。"""
    executor = get_executor()
    result = executor.execute(
        "cat /etc/passwd | grep -v nologin | grep -v '/bin/false' | grep -v '/usr/sbin/nologin'"
    )

    if not result.success:
        return f"用户查询失败: {result.stderr}"

    lines = result.stdout.strip().split("\n")
    if not lines or lines == [""]:
        return "未找到可登录用户"

    output_lines = ["用户名\t\tUID\t家目录\t\t\tShell"]
    output_lines.append("-" * 60)
    for line in lines:
        parts = line.split(":")
        if len(parts) >= 7:
            username = parts[0]
            uid = parts[2]
            home = parts[5]
            shell = parts[6]
            output_lines.append(f"{username}\t\t{uid}\t{home}\t\t\t{shell}")

    return "\n".join(output_lines)


@tool
def create_user(username: str, shell: str = "/bin/bash") -> str:
    """创建新系统用户。这是中等风险操作，安全模块会在执行前进行风险审查。

    Args:
        username: 新用户名，只允许字母、数字和下划线，长度3-32
        shell: 用户Shell，默认 /bin/bash
    """
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{2,31}$", username):
        return "错误：用户名不合法，只允许字母、数字和下划线，长度3-32，且以字母或下划线开头"

    executor = get_executor()
    exists = executor.execute(f"id {username} 2>/dev/null")
    if exists.success:
        return f"用户 '{username}' 已存在，无需重复创建"

    cmd = f"useradd -m -s {shell} {username}"
    return json.dumps({
        "needs_confirm": True,
        "risk_level": "MEDIUM",
        "command": cmd,
        "description": f"即将创建用户 {username}（Shell: {shell}），需要管理员权限",
    }, ensure_ascii=False)


@tool
def delete_user(username: str, remove_home: bool = False) -> str:
    """删除系统用户。这是高风险操作，安全模块会在执行前进行风险审查和二次确认。

    Args:
        username: 要删除的用户名
        remove_home: 是否同时删除家目录，默认不删除
    """
    if username == "root":
        return "错误：绝对禁止删除 root 用户！此操作将导致系统无法使用"

    executor = get_executor()
    id_result = executor.execute(f"id -u {username}")
    if not id_result.success:
        return f"用户 '{username}' 不存在，无需删除"

    try:
        uid = int(id_result.stdout.strip())
        if uid < 1000:
            return f"错误：拒绝删除系统用户 '{username}'（UID={uid}），系统用户不可删除"
    except ValueError:
        pass

    flag = "-r " if remove_home else ""
    cmd = f"userdel {flag}{username}".strip()
    home_note = "及其家目录" if remove_home else ""
    return json.dumps({
        "needs_confirm": True,
        "risk_level": "HIGH",
        "command": cmd,
        "description": f"即将删除用户 {username}{home_note}，此操作不可逆",
    }, ensure_ascii=False)


@tool
def check_user_exists(username: str) -> str:
    """检查指定用户是否存在，并返回其基本信息。

    Args:
        username: 要查询的用户名
    """
    executor = get_executor()
    result = executor.execute(f"id {username}")

    if not result.success:
        return f"用户 '{username}' 不存在"

    return f"用户 '{username}' 存在: {result.stdout.strip()}"
