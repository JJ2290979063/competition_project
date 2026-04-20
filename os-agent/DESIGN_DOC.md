# OS Agent 设计说明文档

> 本文档详细说明 OS Agent 的架构设计、核心机制、技术选型和设计取舍。
> 所有内容基于项目实际代码，可与源码对照阅读。

---

## 一、整体架构设计

### 1.1 系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户终端 (Terminal)                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 自然语言输入
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    interface/cli.py                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ 欢迎横幅     │  │ 系统健康报告  │  │ 工具执行进度回调       │  │
│  │ _show_welcome│  │ _show_health │  │ _tool_progress         │  │
│  └─────────────┘  └──────────────┘  └────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              Markdown 渲染 + Rich Panel 输出                │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────────┘
                           │ user_input
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      agent/core.py                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    OSAgent.chat()                         │   │
│  │                                                          │   │
│  │  ┌─────────┐    ┌──────────┐    ┌─────────────────────┐  │   │
│  │  │ 构建    │───▶│ 调用 LLM │───▶│ 解析 JSON 响应      │  │   │
│  │  │ messages│    │ _call_llm│    │ _parse_llm_response │  │   │
│  │  └─────────┘    └──────────┘    └──────────┬──────────┘  │   │
│  │                                            │              │   │
│  │                    ┌───────────────────────┼──────┐       │   │
│  │                    ▼                       ▼      ▼       │   │
│  │              ┌──────────┐          ┌──────┐ ┌─────────┐   │   │
│  │              │  plan    │          │final │ │ 工具调用 │   │   │
│  │              │ 任务拆解 │          │answer│ │ 分支     │   │   │
│  │              └──────────┘          └──────┘ └────┬────┘   │   │
│  │                                                  │        │   │
│  │                              ┌───────────────────┤        │   │
│  │                              ▼                   ▼        │   │
│  │                     ┌──────────────┐   ┌──────────────┐   │   │
│  │                     │ 安全检查     │   │ needs_confirm│   │   │
│  │                     │_security_chk │   │ 二次确认     │   │   │
│  │                     └──────┬───────┘   └──────┬───────┘   │   │
│  │                            │                  │           │   │
│  │                            ▼                  ▼           │   │
│  │                     ┌──────────────┐   ┌──────────────┐   │   │
│  │                     │ _invoke_tool │   │execute_with  │   │   │
│  │                     │              │   │_sudo         │   │   │
│  │                     └──────┬───────┘   └──────┬───────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  tools/disk.py   │ │ tools/process.py │ │tools/user_mgmt.py│
│  - check_disk    │ │ - list_processes │ │ - create_user    │
│  - find_large    │ │ - check_port     │ │ - delete_user    │
│  - check_inode   │ │ - kill_process   │ │ - list_users     │
└────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
         │                    │                     │
         └────────────────────┼─────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    tools/executor.py                             │
│  ┌─────────────────────┐    ┌──────────────────────────────┐    │
│  │   LocalExecutor     │    │      SSHExecutor             │    │
│  │   (subprocess)      │    │      (paramiko)              │    │
│  │   execute()         │    │      execute()               │    │
│  │   execute_with_sudo │    │      execute_with_sudo()     │    │
│  └─────────────────────┘    └──────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              目标服务器 (本地 / SSH 远程)                         │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 数据流说明

一次完整的用户交互经历以下数据流：

1. **用户输入** → `cli.py` 的 `run_cli()` 接收原始文本
2. **Agent 处理** → `core.py` 的 `chat()` 方法启动 ReAct 循环
3. **LLM 决策** → 通过 Anthropic SDK 调用模型，获取 JSON 格式的动作指令
4. **安全检查** → `_security_check()` 对高风险工具做正则 + LLM 双层风险评估
5. **工具执行** → `_invoke_tool()` 调用对应工具函数，工具内部通过 `executor` 执行命令
6. **二次确认** → 如果工具返回 `needs_confirm`，弹出确认面板，确认后用 sudo 执行
7. **结果反馈** → 工具结果附带进度信息返回给 LLM，驱动下一步决策
8. **最终回复** → LLM 输出 `final_answer`，CLI 层用 Rich Markdown + Panel 渲染

### 1.3 模块职责划分

| 模块 | 文件 | 职责 |
|------|------|------|
| 入口 | `main.py` | CLI 参数解析、日志配置、连接测试、启动界面 |
| 配置 | `config.py` | 环境变量加载、SSH/API/模型参数管理 |
| 核心 | `agent/core.py` | ReAct 循环、工具调度、安全检查、环境探测 |
| 提示词 | `agent/prompts.py` | SYSTEM_PROMPT、RISK_ANALYSIS_PROMPT |
| 记忆 | `agent/memory.py` | 滑动窗口对话记忆、历史导出 |
| 界面 | `interface/cli.py` | Rich 终端渲染、欢迎横幅、健康报告、进度回调 |
| 磁盘工具 | `tools/disk.py` | 磁盘使用率、inode、大文件搜索 |
| 进程工具 | `tools/process.py` | 进程列表、端口查询、进程终止 |
| 文件工具 | `tools/file_ops.py` | 目录浏览、文件搜索、文件内容查看 |
| 用户工具 | `tools/user_mgmt.py` | 用户增删查 |
| 执行器 | `tools/executor.py` | 本地/SSH 命令执行、sudo 提权 |
| 风险检测 | `security/risk_detector.py` | 五级风险评估、正则规则 + LLM 兜底 |
| 确认处理 | `security/confirm_handler.py` | Rich 风险面板、用户交互确认 |

---

## 二、意图解析机制

### 2.1 模型选择与接入方式

项目使用 Claude 模型，通过 Anthropic Python SDK 接入：

```python
# config.py
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://ruoli.dev")
MODEL_NAME = "claude-opus-4-6"
MAX_TOKENS = 2048
TEMPERATURE = 0  # 确保输出稳定性
```

关键设计决策：
- **Temperature 设为 0**：工具调用场景需要确定性输出，避免 JSON 格式不稳定
- **通过中转站访问**：`ANTHROPIC_BASE_URL` 配置为中转站地址，解决国内网络访问问题
- **MAX_TOKENS = 2048**：足够生成详细的自然语言回复，同时控制成本

### 2.2 手动 ReAct 循环

项目的核心是一个手动实现的 ReAct（Reasoning + Acting）循环，位于 `agent/core.py` 的 `chat()` 方法中：

```
用户输入 → [构建 messages] → LLM 决策 → 解析 JSON
                                           │
                              ┌─────────────┼─────────────┐
                              ▼             ▼             ▼
                          final_answer    plan         工具调用
                          (返回结果)    (任务拆解)    (执行+反馈)
                                           │             │
                                           └──────┬──────┘
                                                  │
                                           继续循环（最多15次）
```

循环的核心逻辑：

```python
for _ in range(MAX_ITERATIONS):  # MAX_ITERATIONS = 15
    llm_text = self._call_llm(messages)
    parsed = _parse_llm_response(llm_text)

    if parsed is None:          # LLM 直接回复文本（非 JSON）
        return llm_text

    action = parsed.get("action", "")

    if action == "final_answer": # 最终回复
        return action_input

    if action == "plan":         # 任务拆解
        # 格式化计划，驱动执行步骤1
        continue

    # 工具调用 → 安全检查 → 执行 → 结果反馈
    result = _invoke_tool(action, tool_args)
    messages.append(...)         # 结果加入上下文
    # 继续循环
```

### 2.3 JSON 格式约束

LLM 的所有输出都被约束为严格的 JSON 格式：

```json
{"action": "工具函数名", "action_input": {"参数名": "参数值"}}
{"action": "final_answer", "action_input": "最终回复内容"}
{"action": "plan", "action_input": {"goal": "目标", "steps": ["步骤1", "步骤2"]}}
```

解析逻辑（`_parse_llm_response`）的容错设计：

1. 去除 markdown 代码块包裹（` ```json ... ``` `）
2. 用正则 `\{.*\}` 提取 JSON 对象（支持 LLM 在 JSON 前后添加文字）
3. 验证 JSON 中必须包含 `action` 字段
4. 解析失败时返回 `None`，将 LLM 原始文本作为直接回复

这种设计的优势：
- **稳定性**：JSON 格式比 ReAct 文本格式（Thought/Action/Observation）更容易解析
- **容错性**：即使 LLM 输出格式不完美，正则提取也能工作
- **可扩展性**：新增动作类型只需添加 JSON 分支，无需修改解析逻辑

### 2.4 多步任务的 plan 机制

当用户输入包含多个步骤或条件判断时，Agent 会先输出执行计划：

**触发条件**（在 SYSTEM_PROMPT 中定义）：
- 连接词：然后、再、接着、之后、并且、同时
- 条件词：如果、假如、当...时、超过、不足
- 汇总词：给我一个概览、整体情况、综合报告

**执行流程**：

```
用户: "检查磁盘，如果超过80%就找大文件"
  │
  ▼
LLM 输出 plan:
  {"action": "plan", "action_input": {
    "goal": "检查磁盘并根据条件搜索大文件",
    "steps": ["查询磁盘使用情况", "判断并搜索大文件", "汇总建议"]
  }}
  │
  ▼
系统格式化计划文本，追加到 messages:
  "已制定执行计划，目标：...
   步骤1：查询磁盘使用情况
   步骤2：...
   现在请开始执行步骤1"
  │
  ▼
LLM 开始逐步执行，每步调用工具后收到进度提示:
  "已完成 1 个工具调用。请继续执行下一步..."
  │
  ▼
所有步骤完成后，LLM 输出 final_answer 汇总结果
```

`execution_log` 列表记录每步的工具名、输入参数和执行结果，用于最终汇总时提供完整上下文。

---

## 三、安全风险控制机制

### 3.1 五级风险体系

安全系统定义了五个风险等级（`security/risk_detector.py`）：

```python
class RiskLevel(IntEnum):
    SAFE = 0       # 只读操作，直接执行
    LOW = 1        # 轻微修改，直接执行但记录日志
    MEDIUM = 2     # 中等风险，提示用户但可执行
    HIGH = 3       # 高风险，必须二次确认
    CRITICAL = 4   # 极危险，直接拒绝执行
```

各级别的处理策略：

| 等级 | 颜色 | 图标 | 处理方式 | 典型操作 |
|------|------|------|----------|----------|
| SAFE | — | — | 直接执行 | df、ps、ls、cat |
| LOW | — | — | 执行并记录日志 | 未匹配已知模式的命令 |
| MEDIUM | 黄色 | ⚠️ | 弹出确认面板 | useradd、apt install、systemctl restart |
| HIGH | 红色 | 🔴 | 弹出警告面板 | userdel、kill -9、iptables、shutdown |
| CRITICAL | 红色 | ⛔ | 直接拦截 | rm -rf /、mkfs、dd 写磁盘、删除 root |

### 3.2 CRITICAL 级别规则（直接拦截）

以下操作被识别为 CRITICAL，系统直接拦截，不提供确认选项：

| 规则 | 正则模式 | 拦截原因 |
|------|----------|----------|
| 删除根目录 | `rm -rf /` 及变体 | 摧毁整个系统 |
| 删除系统核心目录 | `rm ... /(etc\|boot\|bin\|sbin\|lib\|usr)` | 导致系统无法启动 |
| 格式化磁盘 | `mkfs.` | 清除所有数据 |
| 直写磁盘 | `dd if=/dev/zero of=/dev/sdX` | 摧毁磁盘数据 |
| 重定向到磁盘设备 | `> /dev/sdX` | 破坏分区表 |
| 删除 root 用户 | `userdel root` | 系统完全不可用 |
| 根目录权限清零 | `chmod 000 /` | 系统完全无法访问 |
| 递归更改根目录所有者 | `chown -R ... /` | 破坏系统权限 |
| Fork bomb | `:(){ :\|:& };:` | 耗尽系统资源 |
| 覆盖关键系统文件 | `> /etc/passwd` 等 | 破坏用户认证 |

### 3.3 HIGH 级别规则（需要二次确认）

| 规则 | 正则模式 | 风险原因 |
|------|----------|----------|
| 删除用户 | `userdel` | 不可逆操作 |
| 修改关键配置 | `vi /etc/sudoers` 等 | 影响系统安全 |
| 停止关键服务 | `systemctl stop sshd` | 可能导致远程连接中断 |
| 强制终止进程 | `kill -9` | 可能导致数据丢失 |
| 修改防火墙 | `iptables -A/-D/-F` | 可能导致网络中断 |
| 递归权限变更 | `chmod -R ... /home` | 影响范围大 |
| 递归删除文件 | `rm -rf` | 需确认目标路径 |
| 系统关机/重启 | `shutdown`、`reboot` | 影响所有服务 |
| 修改密码 | `passwd` | 安全敏感操作 |
| 删除定时任务 | `crontab -r` | 不可逆 |

### 3.4 MEDIUM 级别规则（提示后可执行）

| 规则 | 正则模式 | 风险原因 |
|------|----------|----------|
| 创建用户 | `useradd` | 增加系统访问入口 |
| 安装/卸载软件 | `apt install`、`yum remove` | 改变系统环境 |
| 重启服务 | `systemctl restart` | 可能影响业务 |
| 修改系统配置 | `vi /etc/...` | 配置变更 |
| sed 就地修改 | `sed -i` | 文件内容变更 |
| 修改权限/所有者 | `chmod`、`chown` | 权限变更 |
| 移动/覆盖配置 | `mv /etc/...`、`cp ... /etc/` | 配置文件变更 |

### 3.5 SAFE 级别规则（直接执行）

以下只读操作被识别为安全，直接执行无需确认：

- 系统信息查询：`df`、`du`、`free`、`uptime`、`uname`、`hostname`、`whoami`、`id`
- 进程/网络查看：`ps`、`top`、`ss`、`netstat`、`lsof`、`ip`、`ifconfig`
- 文件查看：`ls`、`cat`、`head`、`tail`、`less`、`more`、`wc`、`file`、`stat`
- 搜索工具：`find`、`locate`、`grep`、`awk`、`sort`、`uniq`、`cut`
- 服务状态查看：`systemctl status`、`systemctl is-active`、`systemctl list`
- 日志查看：`journalctl`、`dmesg`
- 包信息查询：`rpm -q`、`dpkg -l`、`pip list`

### 3.6 双层判断机制：正则优先 + LLM 语义兜底

风险检测采用两层判断策略：

```
命令输入
  │
  ▼
第一层：正则规则匹配（毫秒级）
  │
  ├── 命中 SAFE_PATTERNS → 返回 SAFE，直接执行
  ├── 命中 CRITICAL_PATTERNS → 返回 CRITICAL，直接拦截
  ├── 命中 HIGH_PATTERNS → 返回 HIGH，要求确认
  ├── 命中 MEDIUM_PATTERNS → 返回 MEDIUM，提示确认
  │
  └── 未命中任何规则
        │
        ▼
第二层：Claude API 语义分析（秒级）
  │
  ├── 调用 Claude 模型分析命令风险
  ├── 使用 RISK_ANALYSIS_PROMPT 模板
  ├── 返回 JSON 格式的风险评估结果
  │
  └── API 调用失败 → 兜底返回 LOW
```

**设计原因**：

1. **正则优先**：已知危险模式用正则匹配，速度快（毫秒级），不消耗 API 额度
2. **LLM 兜底**：正则无法覆盖所有场景（如组合命令、管道命令），LLM 能做语义级分析
3. **安全兜底**：LLM 分析失败时默认返回 LOW（而非 SAFE），确保未知命令至少被记录日志
4. **成本控制**：大部分命令在正则层就能判断，只有少数未知命令才调用 API

### 3.7 二次确认交互流程

```
工具调用
  │
  ▼
_security_check() ─── 安全中间件层（core.py）
  │                    对 TOOLS_NEED_REVIEW 中的工具做风险检测
  │                    （kill_process, create_user, delete_user）
  │
  ├── CRITICAL → 显示 ⛔ 拦截面板 → 返回拦截信息
  ├── HIGH → 显示 🔴 警告面板 → 等待 yes/no
  ├── MEDIUM → 显示 ⚠️ 确认面板 → 等待 yes/no
  └── SAFE/LOW → 直接通过
        │
        ▼
_invoke_tool() ─── 工具执行层
  │
  ▼
_parse_confirm_result() ─── 工具返回值检查
  │                         检测是否为 needs_confirm JSON
  │
  ├── 是 needs_confirm → 构建 RiskResult → 弹出确认面板
  │     │
  │     ├── 用户确认 yes → execute_with_sudo() 执行
  │     │     │
  │     │     ├── 成功 → "操作成功执行"
  │     │     └── 失败 → _friendly_exec_error() 友好提示
  │     │
  │     └── 用户取消 no → "用户已取消操作"
  │
  └── 普通结果 → 直接返回给 LLM
```

这种双层确认设计的原因：
- **安全中间件层**：在工具执行前拦截，基于命令文本做风险评估
- **工具返回层**：工具内部做业务校验（如用户是否存在、是否为系统用户），返回 `needs_confirm` 让上层处理确认和 sudo 执行
- **分离关注点**：安全检查和业务逻辑解耦，工具不需要关心确认交互

### 3.8 sudo 权限提升机制

`executor.py` 中的 `execute_with_sudo()` 方法：

- **LocalExecutor**：直接在命令前加 `sudo` 前缀
- **SSHExecutor**：通过 `echo 'password' | sudo -S command` 方式传入密码
  - 密码从 `config.SSH_PASSWORD` 读取
  - 如果未配置密码，回退到无密码 `sudo`（依赖 NOPASSWD 配置）

---

## 四、核心 Prompt 设计

### 4.1 SYSTEM_PROMPT 完整内容

```
你是一个专业的 Linux 服务器管理助手，负责帮助用户通过自然语言完成服务器管理任务。

你的工作原则：
- 准确理解用户意图，选择合适的工具执行操作
- 优先使用只读命令获取信息，再考虑修改类命令
- 对任何可能影响系统稳定性的操作，主动说明风险
- 操作完成后，用清晰的中文总结执行结果
- 如果用户的指令不够明确，先询问澄清再执行
- 如果一个任务需要多步操作，逐步执行并报告每一步的结果

你可以使用以下工具：
- check_disk_usage: 查看磁盘使用情况，无需参数
- check_disk_inode: 查看 inode 使用情况，无需参数
- find_large_files: 查找大文件，参数：path(str), min_size_mb(int)
- list_processes: 查看进程列表，参数：filter_name(str，可选)
- check_port: 检查端口占用，参数：port(int)
- list_listening_ports: 查看所有监听端口，无需参数
- kill_process: 结束进程，参数：pid(int)
- list_directory: 查看目录内容，参数：path(str)
- search_file: 搜索文件，参数：filename(str), search_path(str)
- show_file_content: 查看文件内容，参数：path(str), lines(int)
- get_file_info: 查看文件信息，参数：path(str)
- list_users: 查看用户列表，无需参数
- create_user: 创建用户，参数：username(str)
- delete_user: 删除用户，参数：username(str), remove_home(bool)
- check_user_exists: 检查用户是否存在，参数：username(str)

当你需要调用工具时，必须严格按照以下 JSON 格式输出：
{"action": "工具函数名", "action_input": {"参数名": "参数值"}}

当你已经得到工具执行结果并可以回答用户时，输出：
{"action": "final_answer", "action_input": "你的最终回复内容"}

【多步任务编排】
当用户的请求包含多个步骤或条件判断时，先输出执行计划：
{"action": "plan", "action_input": {"goal": "目标", "steps": ["步骤1", "步骤2"]}}

【回复格式规范 - 必须遵守】
1. 禁止直接粘贴命令行原始输出
2. 数据必须转化为结论性语言
3. 进程信息要说明关键字段含义
4. 用户信息要去除技术噪音
5. 错误信息要友好化
6. 结果要带有情境判断
7. 使用 emoji 增强可读性
```

（完整内容见 `agent/prompts.py`，此处省略部分示例以控制篇幅）

### 4.2 各部分设计思路

**角色定义**（第1段）：
- 明确"Linux 服务器管理助手"的角色边界
- "通过自然语言完成"强调去命令行化的核心目标

**工作原则**（6条）：
- "优先使用只读命令"：安全第一原则，先查后改
- "主动说明风险"：不是默默执行，而是让用户知情
- "先询问澄清再执行"：避免误操作
- "逐步执行并报告"：为多步任务编排铺垫

**工具列表**：
- 每个工具都标注了参数名和类型
- 这是 LLM 生成正确 JSON 的关键——没有参数说明，LLM 无法知道该传什么

**JSON 格式约束**：
- 明确要求"不要输出其他内容"——减少 LLM 在 JSON 外添加文字的概率
- 三种动作类型（工具调用、final_answer、plan）覆盖所有场景

**回复格式规范**：
- 7 条规则确保 LLM 不会直接粘贴原始命令输出
- 每条规则都有错误示例和正确示例，帮助 LLM 理解期望
- emoji 使用规范避免过度使用

### 4.3 环境信息注入

`OSAgent.__init__` 中调用 `_detect_environment()` 探测服务器环境，将结果追加到 SYSTEM_PROMPT 后面：

```
【当前服务器环境信息 - 请基于此做出准确判断】
- 操作系统：Ubuntu 22.04.3 LTS
- 主机名：server-01
- 当前用户：jj280012
- 是否有sudo权限：是
- 内核版本：5.15.0-91-generic
- 根目录磁盘使用率：44%
- 内存使用：1.2Gi/3.8Gi
- CPU核心数：2

【基于环境的判断规则】
- 如果当前用户不是 root 且无 sudo 权限，用户管理类操作需提示权限不足
- 如果根目录磁盘使用率超过 80%，主动提醒用户注意磁盘空间
- 始终根据实际 OS 类型推荐对应的命令（Ubuntu 用 apt，CentOS 用 yum）
```

这样 LLM 在每次对话时都能基于真实环境做出准确判断，而不是说"我需要先查询一下"。

### 4.4 RISK_ANALYSIS_PROMPT

用于 LLM 语义级风险分析的提示词模板：

```
分析以下 Linux 命令的安全风险等级。

命令：{command}
执行上下文：{context}

请从以下维度评估：
1. 是否影响系统核心文件或目录
2. 是否不可逆（删除、格式化等）
3. 影响范围（单个文件 vs 批量 vs 系统级）
4. 是否涉及权限或安全配置

返回严格的 JSON 格式：
{"level": "SAFE|LOW|MEDIUM|HIGH|CRITICAL", "reason": "...", "suggestion": "...", "blocked": true/false}
```

设计要点：
- 四个评估维度覆盖了安全分析的核心关注点
- 要求返回 JSON 格式，便于程序解析
- `blocked` 字段让 LLM 自行判断是否应该拦截

---

## 五、技术选型与设计取舍

### 5.1 为什么用手动 ReAct 而不是 LangChain AgentExecutor

**选择**：手动实现 ReAct 循环（`chat()` 方法中的 for 循环）

**放弃**：LangChain 的 `AgentExecutor`、`create_react_agent` 等高级抽象

**原因**：

1. **可控性**：手动循环可以在每一步插入自定义逻辑（安全检查、进度回调、needs_confirm 处理），AgentExecutor 的回调机制不够灵活
2. **透明性**：手动循环的每一步都清晰可见，便于调试和日志记录。AgentExecutor 内部的状态机较为复杂，出问题时难以定位
3. **安全需求**：项目的核心卖点是安全机制，需要在工具执行前后插入多层检查。AgentExecutor 的 `tool_run_callbacks` 无法满足"工具返回 needs_confirm 后弹出确认面板再用 sudo 执行"这种复杂流程
4. **依赖最小化**：只使用 LangChain 的 `@tool` 装饰器定义工具接口，不依赖其 Agent 运行时，减少版本兼容问题

**代价**：
- 需要自己处理消息格式、循环终止、异常恢复
- 没有 AgentExecutor 的内置 token 限制和自动截断

### 5.2 为什么选择 JSON 格式而不是 ReAct 文本格式

**选择**：LLM 输出严格 JSON（`{"action": "...", "action_input": {...}}`）

**放弃**：经典 ReAct 文本格式（`Thought: ... Action: ... Action Input: ...`）

**原因**：

1. **解析稳定性**：JSON 有明确的语法规则，`json.loads()` 要么成功要么失败，不存在模糊地带。ReAct 文本格式需要用正则提取 Thought/Action/Action Input，容易因 LLM 输出格式不一致而解析失败
2. **参数传递**：JSON 天然支持嵌套结构，工具参数可以是字典、列表等复杂类型。ReAct 文本格式的 Action Input 通常是字符串，需要额外解析
3. **plan 扩展**：plan 动作的 `action_input` 包含 `goal` 和 `steps` 两个字段，JSON 格式天然支持，文本格式需要自定义分隔符
4. **容错设计**：`_parse_llm_response` 用正则 `\{.*\}` 提取 JSON，即使 LLM 在 JSON 前后添加了文字也能正确解析

**代价**：
- LLM 偶尔会输出不合法的 JSON（如尾部逗号、单引号），需要容错处理
- 没有 Thought 字段，LLM 的推理过程不可见（但这对用户体验无影响）

### 5.3 为什么选择 Claude 模型（通过中转站）

**选择**：Claude 模型，通过 `ANTHROPIC_BASE_URL` 配置中转站访问

**原因**：

1. **中文能力**：Claude 的中文理解和生成能力优秀，适合中文自然语言交互场景
2. **指令遵循**：Claude 对 JSON 格式约束的遵循度高，Temperature=0 时输出稳定
3. **安全意识**：Claude 内置的安全意识与项目的安全机制互补
4. **API 兼容性**：Anthropic SDK 接口简洁，`system` 参数天然支持系统提示词注入

### 5.4 工具层的 LangChain @tool 装饰器

虽然没有使用 LangChain 的 Agent 运行时，但保留了 `@tool` 装饰器：

```python
from langchain_core.tools import tool

@tool
def check_disk_usage() -> str:
    """查看磁盘使用情况..."""
```

**原因**：
- `@tool` 提供了标准化的工具接口（`.invoke()` 方法、参数校验）
- 工具的 docstring 可以自动生成工具描述（虽然当前项目在 SYSTEM_PROMPT 中手动维护）
- 如果未来需要迁移到 LangChain Agent，工具层无需修改

### 5.5 对话记忆的滑动窗口设计

```python
class AgentMemory:
    def __init__(self, window_size: int = 10):
        self._messages: deque = deque(maxlen=window_size * 2)
```

**选择**：固定窗口大小（10轮 = 20条消息），使用 `deque` 自动淘汰旧消息

**原因**：
- 简单可靠，不需要 token 计数
- 10 轮对话足够覆盖大部分交互场景
- `deque(maxlen=...)` 自动丢弃最旧的消息，无需手动管理

**代价**：
- 超过 10 轮后早期上下文丢失
- 没有基于 token 的精确截断，可能浪费上下文窗口

---

## 六、已知局限与改进方向

### 6.1 当前版本的已知局限

**1. 工具覆盖范围有限**

当前只有 15 个工具，覆盖磁盘、进程、文件、用户四个领域。缺少：
- 网络诊断工具（ping、traceroute、curl）
- 服务管理工具（systemctl 的完整封装）
- 日志分析工具（journalctl、日志文件解析）
- 包管理工具（apt/yum 的安装、更新、搜索）
- 定时任务管理（crontab 查看和编辑）

**2. 自然语言输出依赖 LLM 遵循度**

回复格式规范完全依赖 SYSTEM_PROMPT 中的指令约束。如果 LLM 不遵循（尤其是在复杂场景下），仍可能直接粘贴原始命令输出。当前没有后处理层来强制转换格式。

**3. 安全规则的正则局限性**

正则规则无法覆盖所有危险命令的变体，例如：
- 通过变量间接构造危险命令：`CMD="rm -rf /"; $CMD`
- 通过 base64 编码绕过：`echo "cm0gLXJmIC8=" | base64 -d | bash`
- 通过管道组合：`find / -delete`

LLM 语义分析可以部分弥补，但也不是万能的。

**4. 多步任务的条件判断依赖 LLM**

plan 机制中的条件判断（如"如果磁盘超过 80%"）完全由 LLM 在上下文中自行判断，没有程序化的条件评估。如果 LLM 误判条件，可能跳过或错误执行步骤。

**5. 对话记忆无持久化**

`AgentMemory` 使用内存中的 `deque`，程序退出后对话历史丢失。虽然有 `save_to_file()` 方法，但需要用户手动调用 `/save`。

**6. SSH 密码明文传输**

`execute_with_sudo()` 中通过 `echo 'password' | sudo -S` 传入密码，密码会出现在进程列表中（`/proc/*/cmdline`）。虽然 SSH 通道本身是加密的，但在目标服务器上存在短暂的明文暴露风险。

**7. 单一模型依赖**

当前硬编码使用 Claude 模型，如果 API 不可用或额度耗尽，整个系统无法工作。没有模型降级或备选方案。

### 6.2 改进方向

**1. 输出后处理层**

在 LLM 回复和用户展示之间增加一个后处理层，用正则或规则检测回复中是否包含原始命令输出格式（如 `Filesystem Size Used`、`USER PID %CPU`），如果检测到则自动触发二次格式化。

**2. 流式输出**

当前 LLM 调用是同步阻塞的，用户需要等待完整回复。可以改用 Anthropic SDK 的流式 API（`stream=True`），实现打字机效果，提升交互体验。

**3. 工具自动发现**

当前工具列表在 `TOOL_REGISTRY` 和 `SYSTEM_PROMPT` 中双重维护，容易不一致。可以实现工具自动注册机制，从 `@tool` 装饰器的 docstring 自动生成 SYSTEM_PROMPT 中的工具描述。

**4. 沙箱执行环境**

对于高风险命令，可以先在 Docker 容器或 chroot 环境中试运行，确认无破坏性后再在真实环境执行。

**5. 操作审计日志**

记录所有工具调用的完整审计日志（时间、用户、命令、结果、风险等级），支持事后审查和合规需求。

**6. 多模型支持**

抽象模型调用层，支持 Claude、GPT-4、Gemini 等多个模型，实现自动降级和负载均衡。

**7. Web 界面增强**

当前 Web 界面（`interface/web.py`）功能较基础，可以增加：
- 实时命令执行日志面板
- 服务器监控仪表盘
- 操作历史时间线
- 多服务器管理

**8. 插件化工具系统**

将工具系统改为插件架构，支持用户自定义工具包，通过配置文件注册新工具，无需修改核心代码。

---

## 附录：项目文件结构

```
os-agent/
├── main.py                    # 程序入口
├── config.py                  # 配置管理
├── requirements.txt           # Python 依赖
├── .env                       # 环境变量（不入库）
├── os_agent.log               # 运行日志
│
├── agent/                     # Agent 核心
│   ├── core.py                # ReAct 循环、工具调度
│   ├── prompts.py             # Prompt 模板
│   └── memory.py              # 对话记忆
│
├── interface/                 # 用户界面
│   ├── cli.py                 # CLI 终端界面
│   └── web.py                 # Web 界面
│
├── tools/                     # 工具集
│   ├── executor.py            # 命令执行器（本地/SSH）
│   ├── disk.py                # 磁盘工具
│   ├── process.py             # 进程工具
│   ├── file_ops.py            # 文件工具
│   └── user_mgmt.py           # 用户管理工具
│
├── security/                  # 安全模块
│   ├── risk_detector.py       # 风险检测器
│   └── confirm_handler.py     # 二次确认处理器
│
└── tests/                     # 测试
```


