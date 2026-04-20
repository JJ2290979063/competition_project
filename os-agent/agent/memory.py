"""
多轮对话记忆管理。

使用 langchain_core 的消息原语实现滑动窗口记忆，
保留最近 N 轮对话，支持导出对话历史到文件。

注：LangChain 1.x 已移除旧版 ConversationBufferWindowMemory，
这里基于 HumanMessage/AIMessage 手动实现等效功能。
"""

import json
import logging
from collections import deque
from datetime import datetime
from typing import List, Dict

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

logger = logging.getLogger(__name__)


class AgentMemory:
    """多轮对话记忆管理器（滑动窗口）"""

    def __init__(self, window_size: int = 10):
        self._window_size = window_size
        self._messages: deque = deque(maxlen=window_size * 2)  # 每轮2条消息
        self._full_log: List[Dict] = []  # 完整对话日志（用于导出）

    def add_interaction(self, user_input: str, agent_response: str) -> None:
        """记录一轮对话"""
        self._messages.append(HumanMessage(content=user_input))
        self._messages.append(AIMessage(content=agent_response))
        self._full_log.append({
            "timestamp": datetime.now().isoformat(),
            "user": user_input,
            "agent": agent_response,
        })

    def get_history(self) -> str:
        """获取格式化的对话历史"""
        if not self._messages:
            return "暂无对话历史"

        lines = []
        for msg in self._messages:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            lines.append(f"[{role}] {msg.content}")
        return "\n".join(lines)

    def get_messages(self) -> List[BaseMessage]:
        """获取原始消息列表，供 Agent 使用"""
        return list(self._messages)

    def clear(self) -> None:
        """清空对话历史"""
        self._messages.clear()
        self._full_log.clear()
        logger.info("对话历史已清空")

    def save_to_file(self, filepath: str = "chat_history.json") -> str:
        """将完整对话历史保存到文件"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self._full_log, f, ensure_ascii=False, indent=2)
        logger.info("对话历史已保存到 %s", filepath)
        return filepath
