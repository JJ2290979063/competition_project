"""
安全模块单元测试。

测试 RiskDetector 的规则匹配准确性，覆盖 CRITICAL / HIGH / MEDIUM / SAFE 各级别。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from security.risk_detector import RiskDetector, RiskLevel


class TestRiskDetectorCritical(unittest.TestCase):
    """CRITICAL 级别：必须拦截"""

    def setUp(self):
        self.detector = RiskDetector()

    def test_rm_rf_root(self):
        r = self.detector.detect("rm -rf /")
        self.assertEqual(r.level, RiskLevel.CRITICAL)
        self.assertTrue(r.blocked)

    def test_rm_rf_root_star(self):
        r = self.detector.detect("rm -rf /*")
        self.assertEqual(r.level, RiskLevel.CRITICAL)
        self.assertTrue(r.blocked)

    def test_rm_etc(self):
        r = self.detector.detect("rm -rf /etc")
        self.assertEqual(r.level, RiskLevel.CRITICAL)

    def test_rm_boot(self):
        r = self.detector.detect("rm -rf /boot")
        self.assertEqual(r.level, RiskLevel.CRITICAL)

    def test_mkfs(self):
        r = self.detector.detect("mkfs.ext4 /dev/sda1")
        self.assertEqual(r.level, RiskLevel.CRITICAL)

    def test_dd_zero(self):
        r = self.detector.detect("dd if=/dev/zero of=/dev/sda bs=1M")
        self.assertEqual(r.level, RiskLevel.CRITICAL)

    def test_userdel_root(self):
        r = self.detector.detect("userdel root")
        self.assertEqual(r.level, RiskLevel.CRITICAL)

    def test_chmod_000_root(self):
        r = self.detector.detect("chmod 000 /")
        self.assertEqual(r.level, RiskLevel.CRITICAL)

    def test_redirect_to_disk(self):
        r = self.detector.detect("> /dev/sda")
        self.assertEqual(r.level, RiskLevel.CRITICAL)

    def test_chown_recursive_root(self):
        r = self.detector.detect("chown -R nobody /")
        self.assertEqual(r.level, RiskLevel.CRITICAL)

    def test_fork_bomb(self):
        r = self.detector.detect(":(){ :|:& };:")
        self.assertEqual(r.level, RiskLevel.CRITICAL)

    def test_overwrite_passwd(self):
        r = self.detector.detect("> /etc/passwd")
        self.assertEqual(r.level, RiskLevel.CRITICAL)


class TestRiskDetectorHigh(unittest.TestCase):
    """HIGH 级别：需要二次确认"""

    def setUp(self):
        self.detector = RiskDetector()

    def test_userdel(self):
        r = self.detector.detect("userdel testuser")
        self.assertEqual(r.level, RiskLevel.HIGH)
        self.assertFalse(r.blocked)

    def test_stop_sshd(self):
        r = self.detector.detect("systemctl stop sshd")
        self.assertEqual(r.level, RiskLevel.HIGH)

    def test_kill_signal(self):
        r = self.detector.detect("kill -9 1234")
        self.assertEqual(r.level, RiskLevel.HIGH)

    def test_iptables_add(self):
        r = self.detector.detect("iptables -A INPUT -p tcp --dport 22 -j DROP")
        self.assertEqual(r.level, RiskLevel.HIGH)

    def test_rm_rf_directory(self):
        r = self.detector.detect("rm -rf /home/user/data")
        self.assertEqual(r.level, RiskLevel.HIGH)

    def test_shutdown(self):
        r = self.detector.detect("shutdown -h now")
        self.assertEqual(r.level, RiskLevel.HIGH)

    def test_reboot(self):
        r = self.detector.detect("reboot")
        self.assertEqual(r.level, RiskLevel.HIGH)

    def test_passwd(self):
        r = self.detector.detect("passwd testuser")
        self.assertEqual(r.level, RiskLevel.HIGH)

    def test_edit_sudoers(self):
        r = self.detector.detect("vim /etc/sudoers")
        self.assertEqual(r.level, RiskLevel.HIGH)


class TestRiskDetectorMedium(unittest.TestCase):
    """MEDIUM 级别：提示后可执行"""

    def setUp(self):
        self.detector = RiskDetector()

    def test_useradd(self):
        r = self.detector.detect("useradd -m testuser")
        self.assertEqual(r.level, RiskLevel.MEDIUM)

    def test_yum_install(self):
        r = self.detector.detect("yum install -y nginx")
        self.assertEqual(r.level, RiskLevel.MEDIUM)

    def test_apt_install(self):
        r = self.detector.detect("apt install nginx")
        self.assertEqual(r.level, RiskLevel.MEDIUM)

    def test_systemctl_restart(self):
        r = self.detector.detect("systemctl restart nginx")
        self.assertEqual(r.level, RiskLevel.MEDIUM)

    def test_chmod(self):
        r = self.detector.detect("chmod 755 /opt/app/script.sh")
        self.assertEqual(r.level, RiskLevel.MEDIUM)

    def test_sed_etc(self):
        r = self.detector.detect("sed -i 's/old/new/g' /etc/nginx/nginx.conf")
        self.assertEqual(r.level, RiskLevel.MEDIUM)


class TestRiskDetectorSafe(unittest.TestCase):
    """SAFE 级别：只读操作，直接执行"""

    def setUp(self):
        self.detector = RiskDetector()

    def test_df(self):
        r = self.detector.detect("df -h")
        self.assertEqual(r.level, RiskLevel.SAFE)

    def test_ps(self):
        r = self.detector.detect("ps aux")
        self.assertEqual(r.level, RiskLevel.SAFE)

    def test_ls(self):
        r = self.detector.detect("ls -la /tmp")
        self.assertEqual(r.level, RiskLevel.SAFE)

    def test_cat(self):
        r = self.detector.detect("cat /etc/hostname")
        self.assertEqual(r.level, RiskLevel.SAFE)

    def test_ss(self):
        r = self.detector.detect("ss -tlnp")
        self.assertEqual(r.level, RiskLevel.SAFE)

    def test_uptime(self):
        r = self.detector.detect("uptime")
        self.assertEqual(r.level, RiskLevel.SAFE)

    def test_whoami(self):
        r = self.detector.detect("whoami")
        self.assertEqual(r.level, RiskLevel.SAFE)

    def test_systemctl_status(self):
        r = self.detector.detect("systemctl status nginx")
        self.assertEqual(r.level, RiskLevel.SAFE)

    def test_free(self):
        r = self.detector.detect("free -m")
        self.assertEqual(r.level, RiskLevel.SAFE)

    def test_uname(self):
        r = self.detector.detect("uname -a")
        self.assertEqual(r.level, RiskLevel.SAFE)


if __name__ == "__main__":
    unittest.main()
