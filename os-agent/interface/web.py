"""
Web 界面 — FastAPI + WebSocket 实时对话。

端点：
  GET  /         → 前端 HTML 页面
  WS   /ws/chat  → WebSocket 实时对话
  GET  /api/status → 连接状态
"""

import json
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from config import config
from agent.core import OSAgent
from tools.executor import get_executor

logger = logging.getLogger(__name__)

# 全局 Agent 实例
_agent = None


def _get_agent() -> OSAgent:
    global _agent
    if _agent is None:
        _agent = OSAgent()
    return _agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Web 服务启动")
    yield
    logger.info("Web 服务关闭")


app = FastAPI(title="OS Agent", lifespan=lifespan)


# ========== 前端 HTML ==========
HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OS Agent — 服务器管理助手</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #1a1a2e; color: #e0e0e0;
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    height: 100vh; display: flex; flex-direction: column;
  }
  #header {
    background: #16213e; padding: 12px 24px;
    border-bottom: 1px solid #0f3460;
    display: flex; align-items: center; justify-content: space-between;
  }
  #header h1 { color: #00d4aa; font-size: 18px; }
  #status { font-size: 12px; color: #888; }
  #status.connected { color: #00d4aa; }
  #status.disconnected { color: #e94560; }
  #chat-container {
    flex: 1; overflow-y: auto; padding: 16px 24px;
  }
  .message { margin-bottom: 16px; animation: fadeIn 0.3s; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; } }
  .message.user .bubble {
    background: #0f3460; border: 1px solid #1a5276;
    border-radius: 12px 12px 4px 12px;
    padding: 10px 16px; display: inline-block; max-width: 80%;
    float: right;
  }
  .message.agent .bubble {
    background: #16213e; border: 1px solid #1a3a4a;
    border-radius: 12px 12px 12px 4px;
    padding: 10px 16px; display: inline-block; max-width: 85%;
  }
  .message .label {
    font-size: 11px; color: #666; margin-bottom: 4px;
  }
  .message.user .label { text-align: right; }
  .message::after { content: ''; display: table; clear: both; }
  .bubble p { margin: 4px 0; line-height: 1.6; }
  .bubble code { background: #0a0a1a; padding: 2px 6px; border-radius: 3px; font-size: 13px; }
  .bubble pre { background: #0a0a1a; padding: 10px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
  .bubble pre code { background: none; padding: 0; }
  .bubble table { border-collapse: collapse; margin: 8px 0; width: 100%; }
  .bubble th, .bubble td { border: 1px solid #333; padding: 6px 10px; text-align: left; }
  .bubble th { background: #0f3460; }
  .risk-warning { color: #e94560; font-weight: bold; }

  #input-area {
    background: #16213e; padding: 12px 24px;
    border-top: 1px solid #0f3460;
    display: flex; gap: 10px;
  }
  #user-input {
    flex: 1; background: #1a1a2e; border: 1px solid #0f3460;
    border-radius: 8px; padding: 10px 16px; color: #e0e0e0;
    font-family: inherit; font-size: 14px; outline: none;
  }
  #user-input:focus { border-color: #00d4aa; }
  #send-btn {
    background: #00d4aa; color: #1a1a2e; border: none;
    border-radius: 8px; padding: 10px 20px; cursor: pointer;
    font-weight: bold; font-size: 14px;
  }
  #send-btn:hover { background: #00b894; }
  #send-btn:disabled { background: #555; cursor: not-allowed; }

  .thinking {
    color: #00d4aa; font-style: italic;
  }
  .thinking::after {
    content: ''; animation: dots 1.5s infinite;
  }
  @keyframes dots {
    0%, 20% { content: '.'; }
    40% { content: '..'; }
    60%, 100% { content: '...'; }
  }
</style>
</head>
<body>
  <div id="header">
    <h1>OS Agent</h1>
    <span id="status" class="disconnected">● 未连接</span>
  </div>
  <div id="chat-container"></div>
  <div id="input-area">
    <input id="user-input" type="text" placeholder="输入自然语言指令..." autocomplete="off" />
    <button id="send-btn" onclick="sendMessage()">发送</button>
  </div>

<script>
  const chatContainer = document.getElementById('chat-container');
  const userInput = document.getElementById('user-input');
  const sendBtn = document.getElementById('send-btn');
  const statusEl = document.getElementById('status');
  let ws = null;

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/chat`);

    ws.onopen = () => {
      statusEl.textContent = '● 已连接';
      statusEl.className = 'connected';
    };

    ws.onmessage = (event) => {
      // 移除 thinking 提示
      const thinkingEl = document.querySelector('.thinking-msg');
      if (thinkingEl) thinkingEl.remove();

      const data = JSON.parse(event.data);
      addMessage('agent', data.response);
      sendBtn.disabled = false;
      userInput.disabled = false;
      userInput.focus();
    };

    ws.onclose = () => {
      statusEl.textContent = '● 已断开';
      statusEl.className = 'disconnected';
      setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      statusEl.textContent = '● 连接错误';
      statusEl.className = 'disconnected';
    };
  }

  function addMessage(role, content) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    const label = role === 'user' ? '你' : 'OS Agent';

    let rendered = content;
    if (role === 'agent') {
      try { rendered = marked.parse(content); } catch(e) {}
    } else {
      rendered = escapeHtml(content);
    }

    div.innerHTML = `<div class="label">${label}</div><div class="bubble">${rendered}</div>`;
    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  function showThinking() {
    const div = document.createElement('div');
    div.className = 'message agent thinking-msg';
    div.innerHTML = '<div class="label">OS Agent</div><div class="bubble"><span class="thinking">正在思考</span></div>';
    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  function sendMessage() {
    const text = userInput.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

    addMessage('user', text);
    ws.send(JSON.stringify({ message: text }));
    userInput.value = '';
    sendBtn.disabled = true;
    userInput.disabled = true;
    showThinking();
  }

  userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  connect();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


@app.get("/api/status")
async def api_status():
    executor = get_executor()
    result = executor.execute("hostname")
    return {
        "mode": config.AGENT_MODE,
        "connected": result.success,
        "hostname": result.stdout.strip() if result.success else None,
        "target": f"{config.SSH_USER}@{config.SSH_HOST}:{config.SSH_PORT}"
        if config.AGENT_MODE == "remote" else "localhost",
    }


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    agent = _get_agent()
    logger.info("WebSocket 连接建立")

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            user_input = msg.get("message", "").strip()

            if not user_input:
                continue

            # 在线程池中运行同步的 agent.chat（避免阻塞事件循环）
            response = await asyncio.to_thread(agent.chat, user_input)

            await websocket.send_text(json.dumps({
                "response": response,
            }, ensure_ascii=False))

    except WebSocketDisconnect:
        logger.info("WebSocket 连接断开")
    except Exception as e:
        logger.error("WebSocket 异常: %s", e)


def run_web(host: str = "0.0.0.0", port: int = 8000):
    """启动 Web 服务"""
    import uvicorn
    print(f"OS Agent Web 界面启动: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
