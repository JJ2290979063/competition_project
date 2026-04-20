"""
二次确认交互逻辑 — 使用 rich 库展示风险警告并获取用户确认。
"""

import logging
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from security.risk_detector import RiskResult, RiskLevel

logger = logging.getLogger(__name__)
console = Console()


class ConfirmHandler:
    """二次确认处理器"""

    def request_confirm(self, risk_result: RiskResult, command: str) -> bool:
        if risk_result.level == RiskLevel.CRITICAL:
            self._show_panel(risk_result, command, "red", "⛔", "危险操作 - 已拦截")
            console.print("[red]  此操作已被系统拦截，无法执行。[/red]\n")
            logger.warning("CRITICAL 操作已拦截: %s | 原因: %s", command, risk_result.reason)
            return False

        if risk_result.level == RiskLevel.HIGH:
            self._show_panel(risk_result, command, "red", "🔴", "高风险操作 - 需要确认")
            return self._ask_confirm()

        if risk_result.level == RiskLevel.MEDIUM:
            self._show_panel(risk_result, command, "yellow", "⚠️", "操作确认")
            return self._ask_confirm()

        return True

    def _show_panel(self, risk: RiskResult, command: str,
                    color: str, icon: str, title: str) -> None:
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(style=f"{color} bold", width=12)
        table.add_column(style="white")

        table.add_row("风险等级", f"[{color}]{risk.level.name}[/{color}]")
        table.add_row("操作说明", risk.reason)
        table.add_row("执行命令", f"[dim]{command}[/dim]")
        table.add_row("建议", risk.suggestion)

        console.print(Panel(
            table,
            title=f"[bold {color}]{icon} {title}[/bold {color}]",
            border_style=color,
            padding=(1, 2),
            expand=False,
        ))

    def _ask_confirm(self) -> bool:
        while True:
            try:
                answer = console.input(
                    "[bold]  是否确认执行？请输入 [green]yes[/green] / [red]no[/red]：[/bold]"
                ).strip().lower()
                if answer in ("yes", "y"):
                    logger.info("用户确认执行")
                    console.print("[green]  ✅ 已确认，正在执行...[/green]\n")
                    return True
                elif answer in ("no", "n"):
                    logger.info("用户取消执行")
                    console.print("[yellow]  ❌ 已取消操作。[/yellow]\n")
                    return False
                else:
                    console.print("  [dim]请输入 yes 或 no[/dim]")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]  ❌ 已取消操作。[/yellow]\n")
                return False
