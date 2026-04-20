"""
进程和端口相关 LangChain 工具。
"""

from langchain_core.tools import tool

from tools.executor import get_executor


@tool
def list_processes(filter_name: str = "") -> str:
    """查看当前运行的进程列表，可按进程名过滤。

    Args:
        filter_name: 可选的进程名关键字过滤，为空则显示所有进程
    """
    executor = get_executor()

    if filter_name:
        cmd = f"ps aux | head -1 && ps aux | grep -i '{filter_name}' | grep -v grep"
    else:
        cmd = "ps aux --sort=-%cpu | head -20"

    result = executor.execute(cmd)

    if not result.success and not result.stdout:
        if filter_name:
            return f"未找到包含 '{filter_name}' 的进程"
        return f"进程查询失败: {result.stderr}"

    output = result.stdout.strip()
    if not output:
        return f"未找到包含 '{filter_name}' 的进程"

    return output


@tool
def check_port(port: int) -> str:
    """检查指定端口的占用情况，返回监听地址、PID和进程名。

    Args:
        port: 要检查的端口号
    """
    if port < 1 or port > 65535:
        return "错误：端口号必须在 1-65535 之间"

    executor = get_executor()
    cmd = f"ss -tlnp | head -1 && ss -tlnp | grep ':{port} '"
    result = executor.execute(cmd)

    if not result.stdout.strip() or result.stdout.strip().count("\n") == 0:
        return f"端口 {port} 当前没有被占用"

    return f"端口 {port} 占用情况:\n{result.stdout.strip()}"


@tool
def list_listening_ports() -> str:
    """查看所有正在监听的端口列表，包含端口号、监听地址和对应进程。"""
    executor = get_executor()
    result = executor.execute("ss -tlnp")

    if not result.success:
        return f"端口查询失败: {result.stderr}"

    return result.stdout.strip()


@tool
def kill_process(pid: int) -> str:
    """终止指定 PID 的进程。这是高风险操作，安全模块会在执行前进行风险审查和二次确认。

    Args:
        pid: 要终止的进程 PID
    """
    if pid <= 1:
        return "错误：拒绝操作 PID <= 1 的进程，这可能导致系统崩溃"

    executor = get_executor()
    # 先查看目标进程信息
    info_result = executor.execute(f"ps -p {pid} -o pid,user,comm,args --no-headers")

    if not info_result.success or not info_result.stdout.strip():
        return f"PID {pid} 对应的进程不存在"

    process_info = info_result.stdout.strip()

    # 执行 kill
    kill_result = executor.execute(f"kill -9 {pid}")

    if not kill_result.success:
        return f"终止进程失败: {kill_result.stderr}"

    return f"进程已终止。原进程信息: {process_info}"
