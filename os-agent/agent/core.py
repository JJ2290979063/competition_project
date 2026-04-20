"""
Agent 主逻辑 — 整个项目的核心。

手动实现 ReAct 循环：LLM 决策 → 解析 JSON → 执行工具 → 反馈结果，
最多循环 MAX_ITERATIONS 次。工具执行前接入安全检查。
"""

import json
import logging
import re
from typing import Callable, Optional

from anthropic import Anthropic

from config import config
from agent.prompts import SYSTEM_PROMPT
from agent.memory import AgentMemory
from security.risk_detector import RiskDetector, RiskLevel, RiskResult
from security.confirm_handler import ConfirmHandler

from tools.executor import get_executor
from tools.disk import check_disk_usage, check_disk_inode, find_large_files
from tools.process import list_processes, check_port, list_listening_ports, kill_process
from tools.file_ops import list_directory, search_file, show_file_content, get_file_info
from tools.user_mgmt import list_users, create_user, delete_user, check_user_exists

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

TOOLS_NEED_REVIEW = {
    "kill_process",
    "create_user",
    "delete_user",
}

TOOL_REGISTRY = {
    "check_disk_usage": check_disk_usage,
    "check_disk_inode": check_disk_inode,
    "find_large_files": find_large_files,
    "list_processes": list_processes,
    "check_port": check_port,
    "list_listening_ports": list_listening_ports,
    "kill_process": kill_process,
    "list_directory": list_directory,
    "search_file": search_file,
    "show_file_content": show_file_content,
    "get_file_info": get_file_info,
    "list_users": list_users,
    "create_user": create_user,
    "delete_user": delete_user,
    "check_user_exists": check_user_exists,
}

TOOL_CHINESE_NAMES = {
    "check_disk_usage": "查询磁盘使用情况",
    "check_disk_inode": "查询 inode 使用情况",
    "find_large_files": "搜索大文件",
    "list_processes": "查询进程列表",
    "check_port": "检查端口占用",
    "list_listening_ports": "查询所有监听端口",
    "list_directory": "查看目录内容",
    "search_file": "搜索文件",
    "show_file_content": "读取文件内容",
    "get_file_info": "获取文件信息",
    "list_users": "查询用户列表",
    "create_user": "创建用户",
    "delete_user": "删除用户",
    "check_user_exists": "检查用户是否存在",
    "kill_process": "结束进程",
}

ERROR_MESSAGES = {
    "Permission denied": "权限不足，该操作需要管理员权限。",
    "No such file": "指定的文件或目录不存在，请检查路径是否正确。",
    "Connection refused": "连接被拒绝，目标服务可能未启动。",
    "command not found": "该命令在当前系统中不存在，可能需要先安装相关软件包。",
    "timeout": "操作超时，服务器响应较慢，请稍后重试。",
}


def friendly_error(raw_error: str) -> str:
    for key, msg in ERROR_MESSAGES.items():
        if key.lower() in raw_error.lower():
            return msg
    return f"操作遇到问题：{raw_error}。如需帮助请描述您的具体需求。"


def _parse_confirm_result(result: str) -> dict | None:
    """检查工具返回值是否为 needs_confirm JSON"""
    try:
        data = json.loads(result)
        if isinstance(data, dict) and data.get("needs_confirm"):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _friendly_exec_error(stderr: str) -> str:
    """将 sudo 执行失败的 stderr 转为友好提示"""
    lower = stderr.lower()
    if "password" in lower or "incorrect" in lower:
        return "执行失败：sudo 密码错误或未配置，请检查 .env 中的 SSH_PASSWORD。"
    if "permission" in lower:
        return "执行失败：当前用户没有执行此操作的权限。"
    return f"执行失败：{stderr.strip() or '未知错误'}"

def _extract_command(tool_name: str, args: dict) -> str:
    if tool_name == "kill_process":
        return f"kill -9 {args.get('pid', '')}"
    elif tool_name == "create_user":
        return f"useradd -m -s {args.get('shell', '/bin/bash')} {args.get('username', '')}"
    elif tool_name == "delete_user":
        flag = "-r " if args.get("remove_home", False) else ""
        return f"userdel {flag}{args.get('username', '')}"
    return ""


def _parse_llm_response(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
        if "action" in data:
            return data
    except json.JSONDecodeError:
        pass
    return None


def _invoke_tool(tool_name: str, tool_input: dict) -> str:
    tool_func = TOOL_REGISTRY.get(tool_name)
    if not tool_func:
        return f"错误：未知工具 '{tool_name}'"
    try:
        return tool_func.invoke(tool_input)
    except Exception as e:
        return f"工具执行失败: {e}"


class OSAgent:
    """操作系统智能管理 Agent"""

    def __init__(self, on_tool_start: Optional[Callable[[str, dict], None]] = None):
        self.client = Anthropic(
            api_key=config.ANTHROPIC_API_KEY,
            base_url=config.ANTHROPIC_BASE_URL,
        )
        self.memory = AgentMemory(window_size=10)
        self.risk_detector = RiskDetector()
        self.confirm_handler = ConfirmHandler()
        self.on_tool_start = on_tool_start

        self.env_info = self._detect_environment()
        self.system_prompt_with_env = SYSTEM_PROMPT + "\n" + self._format_env_prompt(self.env_info)

    def _detect_environment(self) -> dict:
        """连接成功后自动探测服务器环境"""
        executor = get_executor()
        env_info = {}

        probes = [
            ("cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'", "os_name"),
            ("hostname", "hostname"),
            ("whoami", "current_user"),
            ("id", "user_id_info"),
            ("uname -r", "kernel"),
            ("df -h / | tail -1 | awk '{print $5}'", "root_disk_usage"),
            ("free -h 2>/dev/null | grep Mem | awk '{print $3\"/\"$2}'", "memory_usage"),
            ("uptime -p 2>/dev/null || uptime", "uptime"),
            ("nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 未知", "cpu_cores"),
        ]

        for cmd, key in probes:
            result = executor.execute(cmd)
            env_info[key] = result.stdout.strip() if result.success and result.stdout.strip() else "未知"

        sudo_check = executor.execute("sudo -n true 2>/dev/null && echo yes || echo no")
        env_info["has_sudo"] = "是" if sudo_check.success and "yes" in sudo_check.stdout else "否"

        logger.info("服务器环境探测完成: %s", env_info.get("hostname", "未知"))
        return env_info

    @staticmethod
    def _format_env_prompt(env_info: dict) -> str:
        """将环境信息格式化为注入 system prompt 的文本"""
        return f"""
【当前服务器环境信息 - 请基于此做出准确判断】
- 操作系统：{env_info.get('os_name', '未知')}
- 主机名：{env_info.get('hostname', '未知')}
- 当前用户：{env_info.get('current_user', '未知')}
- 用户权限：{env_info.get('user_id_info', '未知')}
- 是否有sudo权限：{env_info.get('has_sudo', '未知')}
- 内核版本：{env_info.get('kernel', '未知')}
- 根目录磁盘使用率：{env_info.get('root_disk_usage', '未知')}
- 内存使用：{env_info.get('memory_usage', '未知')}
- 系统运行时间：{env_info.get('uptime', '未知')}
- CPU核心数：{env_info.get('cpu_cores', '未知')}

【基于环境的判断规则】
- 如果当前用户不是 root 且无 sudo 权限，用户管理类操作需提示权限不足
- 如果根目录磁盘使用率超过 80%，主动提醒用户注意磁盘空间
- 如果内存使用超过 90%，主动提醒用户注意内存压力
- 始终根据实际 OS 类型推荐对应的命令（Ubuntu 用 apt，CentOS 用 yum）
"""

    def _call_llm(self, messages: list[dict]) -> str:
        response = self.client.messages.create(
            model=config.MODEL_NAME,
            max_tokens=config.MAX_TOKENS,
            temperature=config.TEMPERATURE,
            system=self.system_prompt_with_env,
            messages=messages,
        )
        return response.content[0].text

    def _security_check(self, tool_name: str, tool_input: dict) -> str | None:
        if tool_name not in TOOLS_NEED_REVIEW:
            return None
        command = _extract_command(tool_name, tool_input)
        if not command:
            return None
        risk = self.risk_detector.detect(command, context=f"工具: {tool_name}")
        logger.info("安全审查 [%s] 命令='%s' → %s", tool_name, command, risk.level.name)
        if risk.level == RiskLevel.CRITICAL:
            self.confirm_handler.request_confirm(risk, command)
            return f"操作已被安全系统拦截: {risk.reason}"
        if risk.level >= RiskLevel.MEDIUM:
            if not self.confirm_handler.request_confirm(risk, command):
                return "用户取消了此操作"
        return None

    def chat(self, user_input: str) -> str:
        try:
            history = self.memory.get_messages()
            messages = []
            for msg in history:
                role = "user" if hasattr(msg, "type") and msg.type == "human" else "assistant"
                messages.append({"role": role, "content": msg.content})
            messages.append({"role": "user", "content": user_input})

            execution_log = []

            for _ in range(MAX_ITERATIONS):
                llm_text = self._call_llm(messages)
                logger.debug("LLM 输出: %s", llm_text)

                parsed = _parse_llm_response(llm_text)
                if parsed is None:
                    self.memory.add_interaction(user_input, llm_text)
                    return llm_text

                action = parsed.get("action", "")
                action_input = parsed.get("action_input", {})

                if action == "final_answer":
                    answer = action_input if isinstance(action_input, str) else str(action_input)
                    self.memory.add_interaction(user_input, answer)
                    return answer

                if action == "plan":
                    goal = action_input.get("goal", "") if isinstance(action_input, dict) else ""
                    steps = action_input.get("steps", []) if isinstance(action_input, dict) else []
                    plan_text = f"已制定执行计划，目标：{goal}\n"
                    for i, step in enumerate(steps, 1):
                        plan_text += f"  步骤{i}：{step}\n"
                    plan_text += "\n现在请开始执行步骤1，调用对应工具获取数据。"
                    messages.append({"role": "assistant", "content": llm_text})
                    messages.append({"role": "user", "content": plan_text})
                    continue

                if action not in TOOL_REGISTRY:
                    messages.append({"role": "assistant", "content": llm_text})
                    messages.append({"role": "user", "content": f"错误：未知工具 '{action}'，请使用可用工具列表中的工具。"})
                    continue

                tool_args = action_input if isinstance(action_input, dict) else {}
                blocked = self._security_check(action, tool_args)
                if blocked:
                    messages.append({"role": "assistant", "content": llm_text})
                    messages.append({"role": "user", "content": f"工具 {action} 执行结果：{blocked}"})
                    continue

                if self.on_tool_start:
                    self.on_tool_start(action, tool_args)

                result = _invoke_tool(action, tool_args)
                logger.info("工具 [%s] 执行完成，结果长度: %d", action, len(result))

                # 检查工具是否返回了需要二次确认的操作
                confirm_data = _parse_confirm_result(result)
                if confirm_data:
                    risk_level_str = confirm_data.get("risk_level", "HIGH")
                    command = confirm_data.get("command", "")
                    description = confirm_data.get("description", "")

                    risk = RiskResult(
                        level=RiskLevel[risk_level_str],
                        reason=description,
                        suggestion="请确认是否继续执行",
                        blocked=False,
                    )
                    confirmed = self.confirm_handler.request_confirm(risk, command)

                    if not confirmed:
                        result = "用户已取消操作。"
                    else:
                        executor = get_executor()
                        exec_result = executor.execute_with_sudo(command)
                        if exec_result.success:
                            result = f"操作成功执行。\n{exec_result.stdout.strip()}"
                        else:
                            result = _friendly_exec_error(exec_result.stderr)

                execution_log.append({"tool": action, "input": tool_args, "result": result})

                progress = (
                    f"工具 {action} 执行结果：\n{result}\n\n"
                    f"（已完成 {len(execution_log)} 个工具调用。"
                    f"请根据结果继续执行下一步，或者如果所有步骤已完成，"
                    f"请用 final_answer 汇总所有结果给用户。）"
                )
                messages.append({"role": "assistant", "content": llm_text})
                messages.append({"role": "user", "content": progress})

            final = self._call_llm(messages)
            self.memory.add_interaction(user_input, final)
            return final

        except Exception as e:
            logger.error("Agent 执行异常: %s", e, exc_info=True)
            error_msg = friendly_error(str(e))
            self.memory.add_interaction(user_input, error_msg)
            return error_msg

    def clear_history(self) -> None:
        self.memory.clear()

    def get_history(self) -> str:
        return self.memory.get_history()

    def save_history(self, filepath: str = "chat_history.json") -> str:
        return self.memory.save_to_file(filepath)
