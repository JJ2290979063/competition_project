"""
风险检测系统 — 评分重点（15分）。

设计思路：
1. 优先使用正则规则做快速匹配（覆盖已知危险模式）
2. 规则无法判断时调用 Claude API 做语义分析兜底
3. 结果包含中文解释，清晰告知用户风险原因
"""

import re
import json
import logging
from enum import IntEnum
from dataclasses import dataclass
from typing import Optional

from anthropic import Anthropic

from config import config
from agent.prompts import RISK_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


class RiskLevel(IntEnum):
    SAFE = 0       # 只读操作，直接执行
    LOW = 1        # 轻微修改，直接执行但记录日志
    MEDIUM = 2     # 中等风险，提示用户但可执行
    HIGH = 3       # 高风险，必须二次确认
    CRITICAL = 4   # 极危险，直接拒绝执行


@dataclass
class RiskResult:
    level: RiskLevel
    reason: str        # 风险原因（中文）
    suggestion: str    # 建议操作
    blocked: bool      # 是否直接拦截


# ========== 规则定义 ==========

# CRITICAL: 直接拦截，不可通过确认执行
CRITICAL_PATTERNS = [
    # rm -rf / 及其变体
    (r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|"
     r"-[a-zA-Z]*f[a-zA-Z]*r)[a-zA-Z]*\s+/\s*$", "删除根目录下所有文件，将摧毁整个系统"),
    (r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|"
     r"-[a-zA-Z]*f[a-zA-Z]*r)[a-zA-Z]*\s+/\*", "删除根目录下所有文件，将摧毁整个系统"),
    # 删除核心系统目录
    (r"rm\s+.*\s+/(etc|boot|bin|sbin|lib|lib64|usr)\b", "删除系统核心目录，将导致系统无法启动"),
    # 格式化命令
    (r"mkfs\.", "格式化磁盘分区，将清除所有数据"),
    (r"dd\s+.*if=/dev/(zero|random|urandom)\s+.*of=/dev/[a-z]", "直接向磁盘写零/随机数据，将摧毁磁盘数据"),
    # 直写磁盘
    (r">\s*/dev/[sh]d[a-z]", "直接重定向到磁盘设备，将破坏分区表"),
    # 删除 root 用户
    (r"userdel\s+.*root", "删除 root 用户将导致系统完全不可用"),
    # chmod 000 /
    (r"chmod\s+.*000\s+/\s*$", "将根目录权限设为000，系统将完全无法访问"),
    (r"chmod\s+.*000\s+/(etc|bin|sbin|lib|usr)", "将系统核心目录权限设为000，系统将无法运行"),
    # chown -R 到系统目录
    (r"chown\s+-R\s+.*\s+/\s*$", "递归更改根目录所有者，将破坏系统权限"),
    (r"chown\s+-R\s+.*\s+/(etc|bin|sbin|lib|usr)\b", "递归更改系统核心目录所有者"),
    # :(){ :|:& };: fork bomb
    (r":\(\)\s*\{", "fork bomb，将耗尽系统资源导致系统崩溃"),
    # > /etc/passwd 等
    (r">\s*/etc/(passwd|shadow|group|sudoers)", "直接覆盖关键系统文件"),
]

# HIGH: 需要用户二次确认
HIGH_PATTERNS = [
    (r"userdel\s+", "删除系统用户是不可逆操作"),
    (r"(vi|vim|nano|cat\s*>|tee)\s+/etc/(sudoers|passwd|shadow|fstab|ssh)",
     "修改关键系统配置文件"),
    (r"systemctl\s+(stop|disable|mask)\s+(sshd|ssh|firewalld|iptables|systemd|NetworkManager)",
     "停止关键系统服务可能导致远程连接中断或网络不可用"),
    (r"kill\s+(-9\s+|.*-KILL\s+)", "强制终止进程可能导致数据丢失"),
    (r"iptables\s+.*(-A|-D|-I|-F)\s+", "修改防火墙规则可能导致网络连接中断"),
    (r"firewall-cmd\s+", "修改防火墙规则可能导致网络连接中断"),
    (r"chmod\s+-R\s+.*/(home|var|opt|srv)\b", "递归权限变更影响范围大"),
    (r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|"
     r"-[a-zA-Z]*f[a-zA-Z]*r)\s+", "递归删除文件，请确认目标路径正确"),
    (r"shutdown|reboot|poweroff|init\s+[0-6]", "系统关机/重启操作"),
    (r"passwd\s+", "修改用户密码"),
    (r"crontab\s+-r", "删除所有定时任务"),
]

# MEDIUM: 提示风险，用户知情后执行
MEDIUM_PATTERNS = [
    (r"useradd\s+", "创建新用户会增加系统访问入口"),
    (r"(yum|apt|dnf|pip)\s+(install|remove|purge|uninstall)\s+", "安装/卸载软件包会改变系统环境"),
    (r"systemctl\s+(restart|start|enable)\s+", "重启/启动服务可能影响正在运行的业务"),
    (r"(vi|vim|nano|cat\s*>|tee)\s+/etc/", "修改系统配置文件"),
    (r"sed\s+-i\s+", "sed 就地修改文件"),
    (r"chmod\s+", "修改文件权限"),
    (r"chown\s+", "修改文件所有者"),
    (r"mv\s+/etc/", "移动系统配置文件"),
    (r"cp\s+.*\s+/etc/", "覆盖系统配置文件"),
]

# SAFE: 只读操作
SAFE_PATTERNS = [
    r"^(df|du|free|uptime|uname|hostname|whoami|id|w|who|last|date|cal)\b",
    r"^(ps|top|htop|ss|netstat|lsof|ip|ifconfig)\b",
    r"^(ls|ll|cat|head|tail|less|more|wc|file|stat|type|which|whereis)\b",
    r"^(find|locate|grep|egrep|fgrep|awk|sort|uniq|cut|tr)\b",
    r"^sed\s+(?!-i\b)",  # sed 只读模式安全，sed -i 就地修改不安全
    r"^(echo|printf|test|\[)\b",
    r"^(systemctl\s+status|systemctl\s+is-active|systemctl\s+list)",
    r"^(journalctl|dmesg)\b",
    r"^(rpm\s+-q|dpkg\s+-l|pip\s+list|pip\s+show)\b",
]


class RiskDetector:
    """风险检测器"""

    def __init__(self):
        self._client: Optional[Anthropic] = None

    def _get_client(self) -> Anthropic:
        if self._client is None:
            self._client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        return self._client

    def detect(self, command: str, context: str = "") -> RiskResult:
        """
        检测命令的风险等级。
        优先使用规则匹配，无法判断时调用 Claude API 语义分析。
        """
        command = command.strip()

        # 1. 先检查是否为已知安全操作
        for pattern in SAFE_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return RiskResult(
                    level=RiskLevel.SAFE,
                    reason="只读查询操作，无风险",
                    suggestion="可以直接执行",
                    blocked=False,
                )

        # 2. 检查 CRITICAL
        for pattern, reason in CRITICAL_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return RiskResult(
                    level=RiskLevel.CRITICAL,
                    reason=f"极危险操作：{reason}",
                    suggestion="此操作已被系统拦截，禁止执行",
                    blocked=True,
                )

        # 3. 检查 HIGH
        for pattern, reason in HIGH_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return RiskResult(
                    level=RiskLevel.HIGH,
                    reason=f"高风险操作：{reason}",
                    suggestion="需要您的明确确认后才能执行",
                    blocked=False,
                )

        # 4. 检查 MEDIUM
        for pattern, reason in MEDIUM_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return RiskResult(
                    level=RiskLevel.MEDIUM,
                    reason=f"中等风险：{reason}",
                    suggestion="建议确认操作目标后执行",
                    blocked=False,
                )

        # 5. 规则无法判断 → 调用 Claude API 语义分析
        return self._llm_analyze(command, context)

    def _llm_analyze(self, command: str, context: str) -> RiskResult:
        """使用 Claude API 做语义级别的风险分析"""
        try:
            client = self._get_client()
            prompt = RISK_ANALYSIS_PROMPT.format(command=command, context=context or "无")

            response = client.messages.create(
                model=config.MODEL_NAME,
                max_tokens=512,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip()

            # 尝试提取 JSON（兼容被 markdown 包裹的情况）
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                level_map = {
                    "SAFE": RiskLevel.SAFE,
                    "LOW": RiskLevel.LOW,
                    "MEDIUM": RiskLevel.MEDIUM,
                    "HIGH": RiskLevel.HIGH,
                    "CRITICAL": RiskLevel.CRITICAL,
                }
                level = level_map.get(data.get("level", "LOW").upper(), RiskLevel.LOW)
                return RiskResult(
                    level=level,
                    reason=data.get("reason", "AI 分析结果"),
                    suggestion=data.get("suggestion", "请谨慎操作"),
                    blocked=data.get("blocked", False),
                )
        except Exception as e:
            logger.warning("Claude 风险分析失败，回退到 LOW: %s", e)

        # 兜底：无法判断时默认 LOW
        return RiskResult(
            level=RiskLevel.LOW,
            reason="未匹配到已知风险模式，AI 分析不可用，默认低风险",
            suggestion="操作看起来相对安全，但请确认目标正确",
            blocked=False,
        )
