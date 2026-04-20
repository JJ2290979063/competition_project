"""
底层命令执行器 — 统一的命令执行接口，支持本地和 SSH 两种模式。

设计思路：
- CommandResult 数据类封装统一返回结构
- BaseExecutor 抽象基类定义接口
- LocalExecutor 使用 subprocess，SSHExecutor 使用 paramiko
- SSHExecutor 复用连接，避免重复握手
- 所有异常内部消化，绝不向上抛出
"""

import subprocess
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import paramiko

from config import config

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """命令执行结果"""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    success: bool = False

    def __str__(self) -> str:
        if self.success:
            return self.stdout.strip() if self.stdout else "(命令执行成功，无输出)"
        error_msg = self.stderr.strip() if self.stderr else "未知错误"
        return f"命令执行失败 (exit_code={self.exit_code}): {error_msg}"


class BaseExecutor(ABC):
    """执行器抽象基类"""

    @abstractmethod
    def execute(self, command: str, timeout: int = 30) -> CommandResult:
        """执行命令并返回结果"""
        pass

    def execute_with_sudo(self, command: str, timeout: int = 30) -> CommandResult:
        """使用 sudo 执行命令，子类可覆盖"""
        cmd = command.strip()
        if not cmd.startswith("sudo "):
            cmd = f"sudo {cmd}"
        return self.execute(cmd, timeout=timeout)

    @abstractmethod
    def close(self) -> None:
        """释放资源"""
        pass


class LocalExecutor(BaseExecutor):
    """本地命令执行器，使用 subprocess"""

    def execute(self, command: str, timeout: int = 30) -> CommandResult:
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return CommandResult(
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                success=(proc.returncode == 0),
            )
        except subprocess.TimeoutExpired:
            logger.warning("命令执行超时: %s", command)
            return CommandResult(stderr=f"命令执行超时（{timeout}秒）", exit_code=-1, success=False)
        except Exception as e:
            logger.error("本地执行异常: %s", e)
            return CommandResult(stderr=str(e), exit_code=-1, success=False)

    def execute_with_sudo(self, command: str, timeout: int = 30) -> CommandResult:
        cmd = command.strip()
        if not cmd.startswith("sudo "):
            cmd = f"sudo {cmd}"
        return self.execute(cmd, timeout=timeout)

    def close(self) -> None:
        pass  # 本地执行器无需释放资源


class SSHExecutor(BaseExecutor):
    """SSH 远程命令执行器，使用 paramiko，复用连接"""

    def __init__(
        self,
        host: str = None,
        port: int = None,
        username: str = None,
        password: str = None,
        key_path: str = None,
    ):
        self.host = host or config.SSH_HOST
        self.port = port or config.SSH_PORT
        self.username = username or config.SSH_USER
        self.password = password or config.SSH_PASSWORD
        self.key_path = key_path or config.SSH_KEY_PATH
        self._client: Optional[paramiko.SSHClient] = None

    def _get_client(self) -> paramiko.SSHClient:
        """获取 SSH 连接，复用已有连接"""
        if self._client is not None:
            transport = self._client.get_transport()
            if transport is not None and transport.is_active():
                return self._client
            # 连接已断开，关闭后重建
            self._client.close()
            self._client = None

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": 10,
        }

        # 优先使用密钥认证，其次密码
        if self.key_path:
            connect_kwargs["key_filename"] = self.key_path
        elif self.password:
            connect_kwargs["password"] = self.password

        client.connect(**connect_kwargs)
        self._client = client
        logger.info("SSH 连接建立: %s@%s:%d", self.username, self.host, self.port)
        return self._client

    def execute(self, command: str, timeout: int = 30) -> CommandResult:
        try:
            client = self._get_client()
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()

            return CommandResult(
                stdout=out,
                stderr=err,
                exit_code=exit_code,
                success=(exit_code == 0),
            )
        except paramiko.SSHException as e:
            logger.error("SSH 执行异常: %s", e)
            # 连接可能已失效，重置
            self._client = None
            return CommandResult(stderr=f"SSH 执行错误: {e}", exit_code=-1, success=False)
        except Exception as e:
            logger.error("远程执行异常: %s", e)
            return CommandResult(stderr=str(e), exit_code=-1, success=False)

    def execute_with_sudo(self, command: str, timeout: int = 30) -> CommandResult:
        cmd = command.strip()
        if cmd.startswith("sudo "):
            cmd = cmd[5:]
        sudo_password = self.password or config.SSH_PASSWORD
        if sudo_password:
            wrapped = f"echo '{sudo_password}' | sudo -S {cmd}"
        else:
            wrapped = f"sudo {cmd}"
        return self.execute(wrapped, timeout=timeout)

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
            logger.info("SSH 连接已关闭")


# 全局执行器实例（单例）
_executor: Optional[BaseExecutor] = None


def get_executor() -> BaseExecutor:
    """工厂函数：根据配置返回对应执行器（单例）"""
    global _executor
    if _executor is None:
        if config.AGENT_MODE == "remote":
            _executor = SSHExecutor()
        else:
            _executor = LocalExecutor()
        logger.info("初始化执行器: mode=%s", config.AGENT_MODE)
    return _executor
