"""
CLI 交互界面 — 使用 rich 库实现美观的终端交互。

功能：
- 欢迎横幅 + 连接状态
- 多轮对话循环
- spinner 动画表示思考中
- 彩色输出 + Markdown 渲染
- 特殊命令：/clear, /history, /help, /save
"""

import sys
import logging

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.table import Table
from rich.theme import Theme

from config import config
from agent.core import OSAgent, TOOL_CHINESE_NAMES

logger = logging.getLogger(__name__)

# 自定义主题
custom_theme = Theme({
    "user": "bold cyan",
    "agent": "green",
    "warning": "bold yellow",
    "error": "bold red",
    "info": "dim",
})

console = Console(theme=custom_theme)


WELCOME_BANNER = r"""
  ___  ____       _                    _
 / _ \/ ___|     / \   __ _  ___ _ __ | |_
| | | \___ \    / _ \ / _` |/ _ \ '_ \| __|
| |_| |___) |  / ___ \ (_| |  __/ | | | |_
 \___/|____/  /_/   \_\__, |\___|_| |_|\__|
                      |___/
"""

HELP_TEXT = """
**可用命令：**

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/clear` | 清空对话历史 |
| `/history` | 查看对话历史 |
| `/save` | 保存对话历史到文件 |
| `exit` / `quit` | 退出程序 |

**使用示例：**
- 查看磁盘使用情况
- 80端口被什么程序占用了？
- 帮我找一下超过500MB的大文件
- 创建一个叫 testuser 的用户
"""


def _parse_usage_percent(value: str) -> int | None:
    """从 '45%' 这样的字符串中提取数字"""
    try:
        return int(value.strip().replace("%", ""))
    except (ValueError, AttributeError):
        return None


def _usage_style(percent: int | None) -> str:
    if percent is None:
        return "white"
    if percent >= 90:
        return "bold red"
    if percent >= 70:
        return "bold yellow"
    return "green"


def _show_system_health(env_info: dict):
    """用 rich Table 展示系统健康报告"""
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="cyan", width=14)
    table.add_column(style="white")

    table.add_row("操作系统", env_info.get("os_name", "未知"))
    table.add_row("主机名", env_info.get("hostname", "未知"))
    table.add_row("当前用户", env_info.get("current_user", "未知"))
    table.add_row("sudo 权限", env_info.get("has_sudo", "未知"))
    table.add_row("内核版本", env_info.get("kernel", "未知"))
    table.add_row("CPU 核心数", env_info.get("cpu_cores", "未知"))
    table.add_row("运行时间", env_info.get("uptime", "未知"))

    disk_raw = env_info.get("root_disk_usage", "未知")
    disk_pct = _parse_usage_percent(disk_raw)
    disk_style = _usage_style(disk_pct)
    disk_text = Text(disk_raw, style=disk_style)
    if disk_pct is not None and disk_pct >= 80:
        disk_text.append("  ⚠ 磁盘空间不足", style="bold red")
    table.add_row("磁盘使用率", disk_text)

    mem_raw = env_info.get("memory_usage", "未知")
    table.add_row("内存使用", mem_raw)

    console.print(Panel(table, title="[bold green]系统健康报告[/]", border_style="green", expand=False))


def _show_welcome():
    """显示欢迎横幅和连接状态"""
    console.print(WELCOME_BANNER, style="bold cyan")

    mode = config.AGENT_MODE
    if mode == "remote":
        status_text = f"SSH 远程模式 → {config.SSH_USER}@{config.SSH_HOST}:{config.SSH_PORT}"
    else:
        status_text = "本地模式"

    content = Text()
    content.append(f"  连接模式：{status_text}\n", style="bold green")

    panel = Panel(
        content,
        title="[bold green] 连接成功 [/bold green]",
        border_style="green",
        expand=False,
    )
    console.print(panel)
    console.print("[dim]输入自然语言指令开始操作，输入 /help 查看帮助，输入 exit 退出[/dim]\n")


def _handle_special_command(command: str, agent: OSAgent) -> bool:
    """
    处理特殊命令。返回 True 表示已处理，False 表示非特殊命令。
    """
    cmd = command.strip().lower()

    if cmd == "/help":
        console.print(Markdown(HELP_TEXT))
        return True

    if cmd == "/clear":
        agent.clear_history()
        console.print("[info]对话历史已清空[/info]")
        return True

    if cmd == "/history":
        history = agent.get_history()
        console.print(Panel(history, title="对话历史", border_style="cyan"))
        return True

    if cmd == "/save":
        filepath = agent.save_history()
        console.print(f"[info]对话历史已保存到 {filepath}[/info]")
        return True

    return False


def _tool_progress(tool_name: str, tool_args: dict):
    """工具执行前的进度提示回调"""
    cn_name = TOOL_CHINESE_NAMES.get(tool_name, tool_name)
    console.print(f"  [dim]→ 正在执行：{cn_name}...[/dim]")


def run_cli():
    """启动 CLI 交互循环"""
    _show_welcome()

    try:
        with console.status("[bold cyan]正在探测服务器环境...[/bold cyan]", spinner="dots"):
            agent = OSAgent(on_tool_start=_tool_progress)
        _show_system_health(agent.env_info)
        console.print()
    except Exception as e:
        console.print(f"[error]Agent 初始化失败: {e}[/error]")
        sys.exit(1)

    while True:
        try:
            user_input = console.input("[user]OS-Agent > [/user]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[info]再见！[/info]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            console.print("[info]再见！[/info]")
            break

        if _handle_special_command(user_input, agent):
            continue

        console.print()
        console.print("[dim]🤔 正在理解您的指令...[/dim]")
        response = agent.chat(user_input)

        console.print()
        try:
            md = Markdown(response)
            console.print(Panel(md, title="[bold green]OS Agent[/]",
                                border_style="green", padding=(1, 2), expand=False))
        except Exception:
            console.print(Panel(response, title="[bold green]OS Agent[/]",
                                border_style="green", padding=(1, 2), expand=False))
        console.print()
