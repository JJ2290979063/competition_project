"""
程序入口 — 支持 CLI 和 Web 两种启动模式。

启动方式：
  python main.py                           # 默认 CLI 模式
  python main.py --mode remote --host IP   # SSH 远程模式
  python main.py --web                     # Web 界面模式
  python main.py --debug                   # 调试模式
"""

import os
import sys
import logging
import click

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config


def _setup_logging(debug: bool = False):
    """配置日志"""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler("os_agent.log", encoding="utf-8"),
            *([] if not debug else [logging.StreamHandler()]),
        ],
    )


@click.command()
@click.option("--mode", type=click.Choice(["local", "remote"]), default=None,
              help="运行模式：local（本地）或 remote（SSH远程）")
@click.option("--host", default=None, help="SSH 主机地址")
@click.option("--port", default=None, type=int, help="SSH 端口（默认22）")
@click.option("--user", default=None, help="SSH 用户名")
@click.option("--web", is_flag=True, default=False, help="启动 Web 界面")
@click.option("--debug", is_flag=True, default=False, help="显示详细调试日志")
def main(mode, host, port, user, web, debug):
    """OS Agent — 自然语言驱动的 Linux 服务器管理助手"""
    _setup_logging(debug)

    # 命令行参数覆盖环境变量配置
    if mode:
        config.AGENT_MODE = mode
    if host:
        config.SSH_HOST = host
    if port:
        config.SSH_PORT = port
    if user:
        config.SSH_USER = user

    # 检查 API Key
    if not config.ANTHROPIC_API_KEY:
        click.echo("错误：未设置 ANTHROPIC_API_KEY，请在 .env 文件中配置", err=True)
        sys.exit(1)

    # 测试连接
    from tools.executor import get_executor
    executor = get_executor()
    test_result = executor.execute("echo ok")
    if not test_result.success:
        click.echo(f"错误：连接测试失败 — {test_result.stderr}", err=True)
        sys.exit(1)

    if web:
        # 启动 Web 界面
        from interface.web import run_web
        run_web()
    else:
        # 启动 CLI 界面
        from interface.cli import run_cli
        run_cli()


if __name__ == "__main__":
    main()
