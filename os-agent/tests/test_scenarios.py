"""
演示场景测试 — 对应比赛要求的 8 个演示场景。

注意：这些测试需要在有 ANTHROPIC_API_KEY 的环境下运行，
且需要连接到真实 Linux 服务器（本地或 SSH）。

不设置 API Key 时，仅测试工具层和安全模块（不经过 LLM）。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AGENT_MODE", "local")

from security.risk_detector import RiskDetector, RiskLevel


class TestScenario1_DiskQuery(unittest.TestCase):
    """场景1：基础信息查询 — 查看磁盘使用情况"""

    def setUp(self):
        if sys.platform == "win32":
            self.skipTest("Requires Linux")

    def test_disk_usage_returns_data(self):
        from tools.disk import check_disk_usage
        result = check_disk_usage.invoke({})
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 10)


class TestScenario2_PortQuery(unittest.TestCase):
    """场景2：进程查询 — 80端口被什么程序占用"""

    def setUp(self):
        if sys.platform == "win32":
            self.skipTest("Requires Linux")

    def test_port_check(self):
        from tools.process import check_port
        result = check_port.invoke({"port": 80})
        self.assertIsInstance(result, str)
        # 不管有没有占用都应返回有意义的文字
        self.assertTrue("80" in result)


class TestScenario3_LargeFiles(unittest.TestCase):
    """场景3：文件搜索 — 超过500MB的大文件"""

    def setUp(self):
        if sys.platform == "win32":
            self.skipTest("Requires Linux")

    def test_find_large_files(self):
        from tools.disk import find_large_files
        result = find_large_files.invoke({"path": "/tmp", "min_size_mb": 500})
        self.assertIsInstance(result, str)


class TestScenario4_CreateUser(unittest.TestCase):
    """场景4：用户管理（正常） — 创建用户应提示 MEDIUM 风险"""

    def test_create_user_risk(self):
        detector = RiskDetector()
        r = detector.detect("useradd -m -s /bin/bash testuser")
        self.assertEqual(r.level, RiskLevel.MEDIUM)
        self.assertFalse(r.blocked)

    def test_create_user_tool_returns_result(self):
        from tools.user_mgmt import create_user
        result = create_user.invoke({"username": "testuser"})
        # 在非 Linux 环境下会返回失败信息，但不应崩溃
        self.assertIsInstance(result, str)


class TestScenario5_DeleteUser(unittest.TestCase):
    """场景5：高风险拦截（删除用户） — 应提示 HIGH 风险"""

    def test_delete_user_risk(self):
        detector = RiskDetector()
        r = detector.detect("userdel -r testuser")
        self.assertEqual(r.level, RiskLevel.HIGH)
        self.assertFalse(r.blocked)

    def test_delete_user_tool_returns_result(self):
        from tools.user_mgmt import delete_user
        result = delete_user.invoke({"username": "testuser", "remove_home": True})
        # 在非 Linux 环境下会返回失败信息，但不应崩溃
        self.assertIsInstance(result, str)


class TestScenario6_CriticalBlock(unittest.TestCase):
    """场景6：极危险操作拦截 — 清空根目录必须被拦截"""

    def test_rm_rf_root_blocked(self):
        detector = RiskDetector()
        r = detector.detect("rm -rf /")
        self.assertEqual(r.level, RiskLevel.CRITICAL)
        self.assertTrue(r.blocked)

    def test_rm_rf_star_blocked(self):
        detector = RiskDetector()
        r = detector.detect("rm -rf /*")
        self.assertEqual(r.level, RiskLevel.CRITICAL)
        self.assertTrue(r.blocked)

    def test_mkfs_blocked(self):
        detector = RiskDetector()
        r = detector.detect("mkfs.ext4 /dev/sda1")
        self.assertEqual(r.level, RiskLevel.CRITICAL)
        self.assertTrue(r.blocked)

    def test_dd_blocked(self):
        detector = RiskDetector()
        r = detector.detect("dd if=/dev/zero of=/dev/sda")
        self.assertEqual(r.level, RiskLevel.CRITICAL)
        self.assertTrue(r.blocked)


class TestScenario7_ContextMemory(unittest.TestCase):
    """场景7：多轮对话 — 验证对话记忆可以保持上下文"""

    def test_memory_stores_and_retrieves(self):
        from agent.memory import AgentMemory
        mem = AgentMemory(window_size=10)
        mem.add_interaction("查看所有用户", "系统中有 root, admin, deploy 三个可登录用户")
        mem.add_interaction("哪些最近登录过？", "根据 last 命令，admin 最近登录过")

        history = mem.get_history()
        self.assertIn("所有用户", history)
        self.assertIn("admin", history)

    def test_memory_window(self):
        from agent.memory import AgentMemory
        mem = AgentMemory(window_size=2)
        mem.add_interaction("问题1", "回答1")
        mem.add_interaction("问题2", "回答2")
        mem.add_interaction("问题3", "回答3")

        # 窗口大小为2，最早的应该被淘汰
        messages = mem.get_messages()
        texts = " ".join(m.content for m in messages)
        self.assertNotIn("问题1", texts)
        self.assertIn("问题3", texts)


class TestScenario8_ChainedTasks(unittest.TestCase):
    """场景8：连续任务 — 验证工具可以被连续调用"""

    def setUp(self):
        if sys.platform == "win32":
            self.skipTest("Requires Linux")

    def test_disk_then_find(self):
        from tools.disk import check_disk_usage, find_large_files

        usage = check_disk_usage.invoke({})
        self.assertIsInstance(usage, str)

        files = find_large_files.invoke({"path": "/tmp", "min_size_mb": 100})
        self.assertIsInstance(files, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
