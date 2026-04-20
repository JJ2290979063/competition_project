# OS Agent 项目开发汇总

## 一、项目概况

| 项目 | 说明 |
|------|------|
| 目标 | xFUSION AI Hackathon 2026 预赛 — 自然语言驱动的 Linux 服务器管理 AI Agent |
| 技术栈 | Python 3.11+ / Anthropic Claude API / LangChain 1.x / Paramiko / FastAPI / Rich |
| 源文件数 | 22 个 `.py` 文件 + 2 个配置文件 |
| 测试用例 | 67 个（全部通过，11 个因 Windows 环境跳过，部署到 Linux 后可全量运行） |

---

## 二、各阶段完成情况

### Phase 1 — 核心可用 ✅

| 文件 | 功能 | 状态 |
|------|------|------|
| `config.py` | 集中配置管理，环境变量驱动 | ✅ 完成 |
| `requirements.txt` | 依赖清单 | ✅ 完成 |
| `.env.example` | 环境变量模板 | ✅ 完成 |
| `tools/executor.py` | 命令执行器（LocalExecutor + SSHExecutor，连接复用） | ✅ 完成 |
| `tools/disk.py` | 磁盘工具 3 个（df -h / df -i / find 大文件） | ✅ 完成 |
| `tools/process.py` | 进程工具 4 个（ps / ss 端口 / 监听列表 / kill） | ✅ 完成 |
| `tools/file_ops.py` | 文件工具 4 个（ls / find / head / stat） | ✅ 完成 |
| `tools/user_mgmt.py` | 用户工具 4 个（列表 / 创建 / 删除 / 存在检查） | ✅ 完成 |
| `agent/prompts.py` | 系统提示词 + 风险分析提示词 | ✅ 完成 |
| `agent/memory.py` | 滑动窗口对话记忆（10 轮），支持导出 JSON | ✅ 完成 |
| `agent/core.py` | Agent 核心（LangChain create_agent + 安全 middleware） | ✅ 完成 |

### Phase 2 — 安全控制 ✅

| 文件 | 功能 | 状态 |
|------|------|------|
| `security/risk_detector.py` | 5 级风险检测（正则规则优先 + Claude API 语义兜底） | ✅ 完成 |
| `security/confirm_handler.py` | Rich 彩色风险面板 + yes/no 二次确认 | ✅ 完成 |
| Agent 集成 | `wrap_tool_call` middleware 在工具执行前自动拦截审查 | ✅ 完成 |

**风险规则覆盖：**
- CRITICAL（12 条规则）：rm -rf / / mkfs / dd / userdel root / chmod 000 / fork bomb 等 → 直接拦截
- HIGH（10 条规则）：userdel / stop sshd / kill -9 / iptables / shutdown 等 → 二次确认
- MEDIUM（8 条规则）：useradd / yum install / systemctl restart / sed -i 等 → 提示后执行
- SAFE（8 条规则）：df / ps / ls / cat / ss / systemctl status 等 → 直接放行

### Phase 3 — 体验完善 ✅

| 文件 | 功能 | 状态 |
|------|------|------|
| `interface/cli.py` | Rich CLI 界面（欢迎横幅 / spinner / Markdown 渲染 / 特殊命令） | ✅ 完成 |
| `main.py` | Click 入口（--mode / --host / --web / --debug） | ✅ 完成 |

### Phase 4 — 加分项 ✅

| 文件 | 功能 | 状态 |
|------|------|------|
| `interface/web.py` | FastAPI + WebSocket 实时对话 Web 界面（终端风格 UI） | ✅ 完成 |

### Phase 6 — 测试 ✅

| 文件 | 覆盖内容 | 用例数 |
|------|---------|--------|
| `tests/test_tools.py` | executor / 各工具函数 / 安全校验 | 16 |
| `tests/test_security.py` | RiskDetector 四级规则匹配准确性 | 37 |
| `tests/test_scenarios.py` | 8 个演示场景的集成测试 | 14 |

---

## 三、架构与数据流

```
用户输入（自然语言）
    │
    ▼
┌─────────────────────────────────────────────┐
│  interface/cli.py 或 interface/web.py       │
│  （接收输入，显示 spinner，渲染 Markdown）    │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  agent/core.py — OSAgent.chat()             │
│  ┌───────────────────────────────────────┐  │
│  │ LangChain create_agent (LangGraph)    │  │
│  │  ├─ system_prompt (agent/prompts.py)  │  │
│  │  ├─ 15 个 @tool 工具                  │  │
│  │  └─ safety middleware (wrap_tool_call) │  │
│  └───────────────────────────────────────┘  │
│  ┌───────────────────────────────────────┐  │
│  │ agent/memory.py — 滑动窗口 10 轮      │  │
│  └───────────────────────────────────────┘  │
└──────────────────┬──────────────────────────┘
                   │ 工具调用时
                   ▼
┌─────────────────────────────────────────────┐
│  safety middleware                           │
│  ├─ security/risk_detector.py → 风险等级     │
│  └─ security/confirm_handler.py → 用户确认   │
│     CRITICAL → 拦截返回                      │
│     HIGH/MEDIUM → 确认后放行或取消            │
│     LOW/SAFE → 直接放行                      │
└──────────────────┬──────────────────────────┘
                   │ 放行后
                   ▼
┌─────────────────────────────────────────────┐
│  tools/*.py — 具体工具函数                   │
│  └─ tools/executor.py                       │
│     ├─ LocalExecutor (subprocess)           │
│     └─ SSHExecutor (paramiko, 连接复用)      │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
              目标 Linux 服务器
```

---

## 四、开发过程中的修复记录

| 问题 | 原因 | 修复方式 |
|------|------|---------|
| `langchain.memory` 导入失败 | LangChain 1.x 移除了旧版 Memory 模块 | 用 `deque` + `HumanMessage/AIMessage` 手动实现滑动窗口 |
| `create_tool_calling_agent` 不存在 | LangChain 1.x 重构为 `create_agent` + LangGraph | 重写 `agent/core.py` 使用新 API |
| `sed -i` 被误判为 SAFE | SAFE 规则中 `sed` 匹配了 `sed -i` | 拆分规则：`sed` 只读安全，`sed -i` 归入 MEDIUM |
| 写操作工具不执行命令 | `create_user`/`delete_user`/`kill_process` 只返回描述字符串 | 改为真正执行命令，安全审查由 middleware 在调用前完成 |

---

## 五、你接下来需要做的事

### 第一步：环境配置（必须）

1. **创建 `.env` 文件**
   ```bash
   cd os-agent
   cp .env.example .env
   ```
   填入你的 Anthropic API Key 和目标 Linux 服务器的 SSH 信息：
   ```
   ANTHROPIC_API_KEY=sk-ant-xxxxx
   SSH_HOST=你的服务器IP
   SSH_PORT=22
   SSH_USER=root
   SSH_PASSWORD=你的密码
   AGENT_MODE=remote
   ```

2. **确认 `config.py` 中的模型名称**
   当前设置为 `claude-sonnet-4-20250514`。如果你的 API Key 对应的模型不同（比如用的是中转站），需要改成你可用的模型 ID。

### 第二步：在 Linux 服务器上测试（必须）

项目是 Linux 服务器管理工具，必须连接真实 Linux 环境才能完整运行。两种方式：

- **远程模式**（推荐）：在 Windows 上运行 `python main.py --mode remote --host 你的IP`，通过 SSH 连接服务器
- **本地模式**：把项目部署到 Linux 服务器上，运行 `python main.py --mode local`

启动后依次测试路线文档中的 8 个演示场景：
```
1. "查看一下当前磁盘使用情况"
2. "80端口被什么程序占用了？"
3. "帮我找一下系统里超过500MB的大文件"
4. "创建一个叫 testuser 的普通用户"        → 应弹出 MEDIUM 风险确认
5. "把 testuser 这个用户删掉，连家目录一起"  → 应弹出 HIGH 风险确认
6. "清空一下根目录"                        → 应被 CRITICAL 直接拦截
7. "查看当前所有用户" → "刚才看到的那些用户里，有没有最近登录过的？"
8. "帮我检查一下磁盘，如果超过80%就找出大文件，然后告诉我该怎么处理"
```

### 第三步：根据测试结果调整

可能需要调整的地方：
- **Prompt 调优**（`agent/prompts.py`）：如果 Agent 理解意图不准确，调整系统提示词
- **风险规则补充**（`security/risk_detector.py`）：如果发现漏判或误判，增减正则规则
- **模型参数**（`config.py`）：如果回复太长/太短，调整 `MAX_TOKENS`

### 第四步：准备比赛提交材料

按比赛要求准备：

| 材料 | 说明 |
|------|------|
| 演示视频 | 录制场景 1-8 的完整操作流程（CLI 界面） |
| 源代码 | 本项目代码（删除 `.env` 文件后提交） |
| 设计文档 | 写一份 `README.md`，说明架构设计、意图解析逻辑、安全机制 |
| Prompt 说明 | 整理 `agent/prompts.py` 中的核心 Prompt |
| 自测记录 | 运行 `python -m unittest discover -s tests -v` 的截图 |

### 第五步（可选加分）

- 启动 Web 界面：`python main.py --web`，在浏览器访问 `http://localhost:8000`
- 如果有余力，可以集成语音输入（Whisper），路线文档中标注为 Phase 4 加分项
