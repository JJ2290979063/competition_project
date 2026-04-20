"""
工具层单元测试。

测试内容：
- executor 本地执行
- 各工具函数的基本调用（使用本地模式）
"""

import os
import sys
import unittest

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 强制使用本地模式
os.environ.setdefault("AGENT_MODE", "local")

from tools.executor import LocalExecutor, CommandResult


class TestCommandResult(unittest.TestCase):
    def test_success_str(self):
        r = CommandResult(stdout="hello\n", stderr="", exit_code=0, success=True)
        self.assertIn("hello", str(r))

    def test_failure_str(self):
        r = CommandResult(stdout="", stderr="not found", exit_code=1, success=False)
        self.assertIn("not found", str(r))

    def test_empty_success(self):
        r = CommandResult(stdout="", stderr="", exit_code=0, success=True)
        self.assertIn("无输出", str(r))


class TestLocalExecutor(unittest.TestCase):
    def setUp(self):
        self.executor = LocalExecutor()

    def test_echo(self):
        result = self.executor.execute("echo hello")
        self.assertTrue(result.success)
        self.assertIn("hello", result.stdout)

    def test_exit_code(self):
        result = self.executor.execute("exit 42")
        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 42)

    def test_timeout(self):
        # sleep 命令在 Windows 上不可用，跳过
        if sys.platform == "win32":
            self.skipTest("sleep not available on Windows")
        result = self.executor.execute("sleep 10", timeout=1)
        self.assertFalse(result.success)
        self.assertIn("超时", result.stderr)

    def test_invalid_command(self):
        result = self.executor.execute("nonexistent_command_12345")
        self.assertFalse(result.success)


class TestDiskTools(unittest.TestCase):
    """测试磁盘工具（本地模式，仅 Linux）"""

    def setUp(self):
        if sys.platform == "win32":
            self.skipTest("Disk tools require Linux")

    def test_check_disk_usage(self):
        from tools.disk import check_disk_usage
        result = check_disk_usage.invoke({})
        self.assertIsInstance(result, str)
        # df -h 应该包含 Filesystem 或类似头部
        self.assertTrue(len(result) > 0)

    def test_find_large_files_rejects_relative(self):
        from tools.disk import find_large_files
        result = find_large_files.invoke({"path": "relative/path"})
        self.assertIn("绝对路径", result)

    def test_find_large_files_rejects_dotdot(self):
        from tools.disk import find_large_files
        result = find_large_files.invoke({"path": "/tmp/../etc"})
        self.assertIn("..", result)


class TestProcessTools(unittest.TestCase):
    def setUp(self):
        if sys.platform == "win32":
            self.skipTest("Process tools require Linux")

    def test_check_port_invalid(self):
        from tools.process import check_port
        result = check_port.invoke({"port": 0})
        self.assertIn("1-65535", result)

    def test_kill_process_reject_pid1(self):
        from tools.process import kill_process
        result = kill_process.invoke({"pid": 1})
        self.assertIn("拒绝", result)


class TestFileOpsTools(unittest.TestCase):
    def setUp(self):
        if sys.platform == "win32":
            self.skipTest("File ops tools require Linux")

    def test_show_file_rejects_shadow(self):
        from tools.file_ops import show_file_content
        result = show_file_content.invoke({"path": "/etc/shadow"})
        self.assertIn("敏感文件", result)


class TestUserMgmtTools(unittest.TestCase):
    def test_create_user_invalid_name(self):
        from tools.user_mgmt import create_user
        result = create_user.invoke({"username": "ab"})  # 太短
        self.assertIn("不合法", result)

    def test_create_user_special_chars(self):
        from tools.user_mgmt import create_user
        result = create_user.invoke({"username": "user@name"})
        self.assertIn("不合法", result)

    def test_delete_user_root(self):
        from tools.user_mgmt import delete_user
        result = delete_user.invoke({"username": "root"})
        self.assertIn("禁止", result)


if __name__ == "__main__":
    unittest.main()
