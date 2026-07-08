# AI Agent 核心概念 Knowledge Base

记录日期: 2026-07-08

---

## 1. MCP vs A2A 的区别

### MCP = Model Context Protocol

它解决的问题是：

> 一个 AI 模型/Agent 怎么标准化地调用外部工具、读取数据、操作系统、访问数据库、调用 API？

比如你有一个 AI 助手，它想做这些事：

- 读 GitHub issue
- 查数据库
- 操作浏览器
- 读取本地文件
- 调用公司内部 API
- 查询飞书、Notion、Slack
- 执行某个命令

如果没有 MCP，每个工具都要单独适配一套接口。

MCP 的作用就是把这些工具包装成统一协议，让 AI 可以像"插 USB 外设"一样使用它们。

**类比：MCP 像 AI 世界的 USB-C / 插件协议。**

它关注的是：

- 工具怎么暴露给模型
- 模型怎么调用工具
- 工具返回什么结果
- 权限、资源、提示词、上下文怎么管理

例如：

```
AI Agent
  └── MCP Server
        ├── read_file
        ├── search_database
        ├── send_message
        └── run_command
```

### A2A = Agent-to-Agent

它解决的问题是：

> 不同 AI Agent 之间，怎么互相发现、沟通、委托任务、交换结果？

比如有几个 Agent：

- 一个产品经理 Agent
- 一个代码 Agent
- 一个测试 Agent
- 一个运维 Agent
- 一个数据分析 Agent

用户说："帮我实现一个功能，并写测试，最后部署。"

主 Agent 可能会这样分工：

```
主 Agent
  ├── 委托代码 Agent 写代码
  ├── 委托测试 Agent 跑测试
  ├── 委托文档 Agent 写说明
  └── 委托运维 Agent 部署
```

A2A 关注的是 Agent 和 Agent 之间的协作，而不是单个 Agent 调工具。

**类比：A2A 像 AI Agent 之间的"工作流协作协议"或"公司内部沟通协议"。**

它关注的是：

- 一个 Agent 如何描述自己的能力
- 另一个 Agent 如何发现它
- 如何委托任务
- 如何汇报进度
- 如何传递上下文
- 如何返回结果
- 如何处理多轮协作

### MCP 和 A2A 的核心区别

| 对比 | MCP | A2A |
|---|---|---|
| 全称 | Model Context Protocol | Agent-to-Agent |
| 主要对象 | Agent ↔ 工具/数据源 | Agent ↔ Agent |
| 解决问题 | AI 怎么调用外部能力 | AI 之间怎么协作 |
| 类比 | USB-C / 插件系统 | 团队协作 / 工作委托 |
| 典型场景 | 读文件、查数据库、调 API | 多 Agent 分工、任务派发 |
| 粒度 | 工具级 | Agent 级 |
| 谁调用谁 | 模型调用工具 | Agent 调用另一个 Agent |
| 返回结果 | 工具输出 | 任务结果、进度、上下文 |

### 一个直观例子

假设让一个 AI 系统："帮我分析销售数据，生成报告，发给团队。"

**MCP 负责**：让 Agent 能调用这些工具：

```
Agent → MCP → 数据库 / 文档 / 邮件系统
```

**A2A 负责**：让多个 Agent 分工：

```
Agent → A2A → 另一个 Agent
```

### 它们不是竞争关系

> MCP 和 A2A 不是二选一，而是互补。

一个完整的多 Agent 系统里，很可能同时使用两者：

```
用户
 ↓
主 Agent
 ↓ A2A
分析 Agent / 代码 Agent / 测试 Agent
 ↓ MCP
数据库 / GitHub / 浏览器 / 文件系统 / API
```

- A2A 管 Agent 之间怎么协作
- MCP 管 Agent 怎么使用工具

**一句话总结：MCP 让 AI "有手有脚"；A2A 让 AI "会组队干活"。**

---

## 2. A2A 协议规范详解 & Claude Code 是否符合

### A2A 公认协议：Agent2Agent Protocol v0.3.0

由 Google 发起、现在在 A2A Project / Linux Foundation 生态推进的 Agent2Agent Protocol 是目前最主流的开放 A2A 规范。

官方 spec 最新版：**A2A Protocol v0.3.0**（https://a2a-protocol.org/v0.3.0/specification）

它的核心不是"让两个模型直接聊天"，而是定义一套标准：

> 一个 Agent 如何暴露能力、另一个 Agent 如何发现它、如何给它派任务、如何收进度和结果。

### 核心组成

#### 1. Agent Card

每个 Agent 暴露一个类似"名片"的 JSON，说明：我是谁、我会什么技能、我的 endpoint 在哪里、支持哪些输入/输出模式、需要什么认证。

```json
{
  "name": "Code Review Agent",
  "description": "Reviews pull requests and suggests fixes",
  "url": "https://agent.example.com/a2a",
  "protocolVersion": "0.3.0",
  "skills": [
    {
      "id": "code_review",
      "name": "Code Review",
      "description": "Review code changes"
    }
  ]
}
```

#### 2. Transport

A2A v0.3.0 支持几种传输方式，都是基于 HTTP(S)：

- **JSON-RPC 2.0**
- **HTTP+JSON / REST**
- **gRPC**
- 流式更新通常用 **SSE (Server-Sent Events)**

#### 3. Message

Agent 之间传递的消息，不只是纯文本。它有 `role` 和 `parts`：

```json
{
  "role": "user",
  "parts": [
    { "kind": "text", "text": "请帮我 review 这个 PR" }
  ]
}
```

Part 可以是：TextPart（文本）、FilePart（文件）、DataPart（结构化 JSON 数据）

#### 4. Task

A2A 的核心单位是 **Task**，不是单轮 chat。

一个 Agent 给另一个 Agent 发任务，对方返回 task id，然后任务会经历状态变化：

```
submitted → working → input-required → completed / failed / canceled / rejected / auth-required
```

这很适合长任务。

#### 5. 常见方法（JSON-RPC）

```
message/send      — 发起/继续一个任务
message/stream    — 发起任务并流式接收进度
tasks/get         — 查询任务状态
tasks/cancel      — 取消任务
tasks/resubscribe — 重新订阅长任务进度
```

### 它和 MCP 的结构差异

```
MCP 的核心对象：tool / resource / prompt
A2A 的核心对象：agent / skill / message / task / artifact
```

- MCP 更像"工具调用协议"
- A2A 更像"任务委托协议"

### Claude Code 符合 A2A 协议吗？

**结论：Claude Code 本身不是原生 A2A-compliant。**

Claude Code 明确支持的是：

- **MCP**：连接工具、数据库、API、外部系统
- **Subagents**：Claude Code 内部的子 Agent
- **Agent Teams**（实验性）：多个 Claude Code session 协作

但这些都不等于官方 A2A Protocol。

#### Claude Code 的 subagents 不是 A2A

它更像内部编排机制，缺少：标准 Agent Card、标准 A2A HTTP endpoint、标准 `message/send`、标准 Task 状态协议、标准跨厂商发现/调用机制。

#### Claude Code 的 Agent Teams 也不是严格 A2A

更接近 A2A 的理念（多实例协作），但它是 Claude Code 的实验特性，不是 A2A v0.3.0 协议实现。

### Claude Code 能不能接入 A2A？

可以，但需要包一层 wrapper：

```
A2A Client → HTTP / JSON-RPC / REST → A2A Wrapper → Claude Code CLI / SDK → 真实执行
```

wrapper 需要：暴露 Agent Card、实现 `message/send` / `message/stream`、把 A2A task 映射成 Claude Code session、把输出映射成 A2A Artifact、处理认证/权限。

### 判断标准

判断一个系统是不是 A2A-compliant：

1. 有没有标准 Agent Card？
2. 有没有公开的 A2A HTTP/gRPC endpoint？
3. 是否实现标准操作（message/send, tasks/get）？
4. 是否用 A2A 的 Task / Message / Part / Artifact 模型？
5. 另一个厂商的 A2A Client 能不能无需私有适配就调用它？

Claude Code 默认答案大多是：**否**。

**总结：A2A 的主流开放协议是 Agent2Agent Protocol v0.3.0；Claude Code 有 Agent 协作能力，但不是原生 A2A-compliant，只能通过封装变成 A2A Agent。**

---

## 3. ReAct = Reasoning + Acting

### 什么是 ReAct

ReAct 不是前端框架 React，而是 AI Agent 领域的核心范式：

> **Re**asoning + **Act**ing = **ReAct**

来自 2022 年论文（Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models"），现在是几乎所有主流 Agent 系统的底层思考模式。

### 核心思想

传统 LLM 两种用法：

1. **Chain-of-Thought (CoT)**：让模型"想"，一步步推理，但不行动
2. **Acting only**：让模型直接调用工具，但不解释为什么

ReAct 把两者结合：

> 先想为什么要做 → 做 → 看到结果 → 再想下一步 → 再做 → …… 直到完成

### 一个循环长这样

```
Thought: 用户问天气，我需要查他的城市
Action: search_weather(city="上海")
Observation: 上海今天 32°C，多云

Thought: 拿到了，直接回答
Action: reply("上海今天32度，多云")
```

每一轮都是三步：

| 步骤 | 含义 |
|---|---|
| **Thought** | 模型的推理/思考（为什么要做这个） |
| **Action** | 实际调用工具/执行操作 |
| **Observation** | 工具返回的结果 |

### 为什么重要？

**没有 ReAct 之前**：纯推理会瞎编/过时；纯行动会盲目不知道信哪个。

**有了 ReAct 之后**：

- **可解释**：每一步都有推理
- **可纠错**：看到 Observation 不对，可以重新想
- **可迭代**：多轮尝试
- **接地气**：推理基于真实工具返回

### 你用过的系统几乎都是 ReAct

Claude Code、OpenClaw、Cursor、各种 Agent 框架底层都是这个模式。

### 和其他模式的对比

| 模式 | 特点 | 缺点 |
|---|---|---|
| **纯 CoT** | 只推理不行动 | 无法获取真实信息 |
| **纯 Act** | 只调工具不思考 | 盲目执行，不知道何时停 |
| **ReAct** | 推理 + 行动交替 | 每步都要推理，token 多一些 |
| **Plan-then-Act** | 先整体规划再执行 | 不灵活，计划赶不上变化 |
| **Reflexion** | ReAct + 失败后反思 | 更慢，但更强 |

### ReAct 的变体/进阶

```
ReAct（基础）
  ├── Reflexion = ReAct + 失败后自我反思
  ├── LATS = ReAct + 树搜索（多条路径并行探索）
  ├── Plan-and-Solve = 先规划再 ReAct 执行
  └── ReWOO = 把所有 Action 一次性规划好再批量执行（减少来回）
```

**一句话总结：ReAct = 让 AI Agent 像人一样工作：想一步、做一步、看结果、再想下一步。它不是某个库或框架，而是一种思考-行动循环的设计模式。**

---

## 4. 多模态模型架构（不是 MoE）

### 多模态 ≠ MoE

- **多模态 (Multimodal)**：能处理多种输入/输出类型（文本、图像、音频、视频）
- **MoE (Mixture of Experts)**：一种模型内部的稀疏计算结构

它们是两个独立的概念，可以组合但不是一回事。

### 多模态模型的主流架构

#### 流派一：Encoder + LLM（接线式）— 最常见

```
图像 → 视觉编码器 (ViT) → 投影层 → LLM
文本 → Tokenizer → LLM
音频 → 音频编码器 (Whisper) → 投影层 → LLM
```

每种模态有专门的编码器，把非文本信息"翻译"成 LLM 能理解的 token 序列。

代表：GPT-4o、Claude (Opus/Sonnet)、LLaVA、Qwen-VL、InternVL

```
┌─────────────┐     ┌───────────┐     ┌─────────┐
│ Image       │────▶│ ViT       │────▶│         │
│ (pixels)    │     │ Encoder   │     │         │
└─────────────┘     └───────────┘     │         │
                          │            │   LLM   │──▶ 文本输出
                     Projection        │ Decoder │
                          │            │         │
┌─────────────┐     ┌────▼──────┐     │         │
│ Text        │────▶│ Tokenizer │────▶│         │
└─────────────┘     └───────────┘     └─────────┘
```

#### 流派二：原生多模态（统一 tokenizer）

不用单独的编码器，直接把所有模态都变成 token 序列，从头训练。

```
图像 → 图像 tokenizer → tokens ─┐
文本 → 文本 tokenizer → tokens ──┼──▶ 统一 Transformer
音频 → 音频 tokenizer → tokens ─┘
```

代表：Gemini 系列、GPT-4o（声称原生多模态）、Chameleon (Meta)、Fuyu (Adept)

优势：模态之间融合更深。劣势：训练成本极高。

#### 流派三：Cross-Attention 融合

在 LLM 的 Transformer 层里插入 cross-attention，让文本 token 能"看到"图像特征。

```
图像特征 ──────────────────────┐
                               ▼ (cross-attention)
文本 token → Self-Attn → Cross-Attn → FFN → ...
```

代表：Flamingo (DeepMind)、Kosmos

#### 流派四：Diffusion + LLM（生成式多模态）

能同时理解和生成多种模态：

```
理解方向：图像 → 编码器 → LLM → 文本描述
生成方向：文本 → LLM → Diffusion 解码器 → 图像
```

代表：DALL-E 3、Gemini、Janus (DeepSeek)

### MoE 是什么？

MoE = Mixture of Experts = 混合专家模型

```
输入 token → Router（路由器决定去哪些专家）→ 选择 top-k 个专家 → 加权合并输出
```

- 模型总参数量很大（比如 1.8T）
- 每个 token 只激活一小部分专家（比如 8 个里选 2 个）
- 推理时实际计算量远小于总参数量

类比：大公司有 100 个部门，但每个任务只需要 2-3 个部门协作。

### MoE 和多模态的关系

它们是正交的两个维度：

| | Dense（稠密） | MoE（稀疏） |
|---|---|---|
| **纯文本** | GPT-4、Claude | Mixtral、DeepSeek-V3 |
| **多模态** | LLaVA、InternVL | Grok、部分 Gemini |

### 哪些多模态模型用了 MoE？

| 模型 | 多模态 | MoE |
|---|---|---|
| GPT-4（传闻） | ✅ | ✅（据传 8×220B） |
| Gemini 1.5/2.5 | ✅ | ✅（据传） |
| Grok-2/3 | ✅ | ✅ |
| DeepSeek-VL2 | ✅ | ✅（MoE backbone） |
| Claude Opus/Sonnet | ✅ | ❓（未公开，可能 Dense） |
| LLaVA、Qwen-VL | ✅ | ❌（Dense） |
| Mixtral | ❌（纯文本） | ✅ |

### 总结

```
多模态模型
├── 输入侧：怎么处理不同模态？
│   ├── 方案 A：专用编码器 + 投影到 LLM（最常见）
│   ├── 方案 B：统一 tokenizer（原生多模态）
│   └── 方案 C：Cross-Attention 融合
├── 骨干网络：Transformer 内部结构？
│   ├── Dense（全参数激活）
│   └── MoE（稀疏激活，路由选专家）← 可选项，不是必选
└── 输出侧：能输出什么？
    ├── 纯文本输出（大多数）
    ├── 文本 + 图像生成（Gemini、GPT-4o）
    └── 文本 + 音频生成（GPT-4o voice）
```

**一句话总结：多模态是"能力"（处理多种输入输出），MoE 是"结构"（稀疏激活省算力）。两者可以组合，但互相独立。大部分多模态模型的核心架构是"专用编码器 + 投影层 + LLM backbone"，MoE 只是 backbone 的一种可选实现。**

---

## 5. Function Calling、并行/串行、Claude Code 真实 Agent 实现

### Function Calling 基础机制

一次模型调用可以返回多个 tool_use 请求。整个流程是：

```
用户消息 → 模型推理 → 返回 N 个 tool_use block → 客户端执行 → 返回 N 个 tool_result → 下一轮
```

以 Claude API 为例，一次 response 可能长这样：

```json
{
  "role": "assistant",
  "content": [
    { "type": "text", "text": "我来同时查两个文件" },
    { "type": "tool_use", "id": "toolu_01", "name": "read_file", "input": {"path": "a.py"} },
    { "type": "tool_use", "id": "toolu_02", "name": "read_file", "input": {"path": "b.py"} }
  ],
  "stop_reason": "tool_use"
}
```

模型一次性返回了 2 个 tool call。接下来客户端（Agent 框架）要决定并行还是串行。

### 并行 vs 串行：谁决定的？

**模型决定"调什么"，框架/客户端决定"怎么执行"。**

Anthropic 官方文档明确说：

> "The API doesn't prescribe an execution order: you can run the calls concurrently (Promise.all, asyncio.gather), sequentially in the order they appear, or in any combination that suits your tools."

| 决定什么 | 谁决定 |
|---|---|
| 调哪些工具、传什么参数 | **模型** |
| 并行还是串行执行 | **Agent 框架 / 客户端代码** |
| 是否跳过某个 call | **Agent 框架** |

#### 并行 vs 串行的判断原则

```
并行适合：
  ✅ 读操作（读文件、搜索、查询）
  ✅ 互相独立、无副作用
  ✅ 不共享状态

串行适合：
  ✅ 有副作用的写操作
  ✅ 后一个依赖前一个的结果
  ✅ 操作同一个资源
  ✅ 顺序有业务含义
```

大多数 Agent 框架做法：**同一轮返回的多个 tool call → 默认并行执行（模型认为它们独立才会同时返回）**

### Claude Code 真实 Agent Loop 源码分析

Claude Code 源码（2026-03 泄露的 TypeScript 原版 510K+ 行 + 社区 Rust 重写 ~20K 行）。

#### 核心架构：一个异步生成器

整个 Agent Loop 在 `query.ts`，约 1729 行，是一个 AsyncGenerator：

```typescript
export async function* query(
  params: QueryParams,
): AsyncGenerator<StreamEvent | Message | ToolUseSummaryMessage, Terminal>
```

#### 简化后的核心循环（Rust 重写版，88 行）

```python
def run_turn(user_input):
    session.messages.append(UserMessage(user_input))

    while True:
        if iterations > max_iterations:
            raise Error("Max iterations exceeded")

        # 1. 调用 LLM
        response = api_client.stream(system_prompt, session.messages)

        # 2. 解析 response
        assistant_message = parse_response(response)
        session.messages.append(assistant_message)

        # 3. 提取 tool calls
        tool_calls = extract_tool_uses(assistant_message)

        # 4. 没有 tool call → 结束
        if not tool_calls:
            break

        # 5. 执行每个 tool call
        for tool_name, input in tool_calls:
            permission = authorize(tool_name, input)
            if permission == Allow:
                result = tool_executor.execute(tool_name, input)
                session.messages.append(ToolResult(result))
            else:
                session.messages.append(ToolResult(deny_reason, is_error=True))
```

#### 状态机：7 个状态，只有 3 个是正常路径

```
BuildConfig → CallModel → ProcessStream → CheckStop → ExecuteTools → 回到 BuildConfig
                                              ↓
                                           Terminal（结束）
```

4 个额外状态是错误恢复：
- FallbackModel：API 报错时切换备选模型
- max_tokens 处理：response 被截断时重试
- 413 处理：上下文太大时压缩
- DoomLoop 检测：Agent 重复相同操作时强制终止

#### 并行工具执行的真实实现

TypeScript 原版中，工具执行用**流式并发执行器**：

```
模型返回多个 tool_use blocks
    ↓
Streaming Tool Executor（并发执行）
    ↓
每完成一个 → yield 结果给消费者
    ↓
全部完成 → 组装成 tool_result 数组 → 下一轮 API 调用
```

> "Concurrent tool execution yields results incrementally. The streaming tool executor yields each tool result as it completes."

Claude Code 的策略：**同一轮的多个 tool call → 默认并发执行 → 每个完成时立即 yield 给 UI → 全部完成后才进入下一轮 API 调用。**

#### 但权限检查是串行的

```python
for tool_name, input in tool_calls:
    permission = authorize(tool_name, input)  # ← 串行！
```

因为权限弹窗需要用户交互，不能并行弹 5 个。

完整流程：

```
tool_calls 列表 → 串行检查权限 → 通过的并发执行 → 被拒的返回 error → 全部结果组装 → 下一轮
```

### Claude Code 完整架构图

```
┌─────────────────────────────────────────────────────────┐
│                    用户输入                               │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│  QueryEngine.ts（Session 生命周期管理）                    │
│  - 组装 system prompt                                    │
│  - 管理 message history                                  │
│  - 决定何时调用 agent loop                               │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│  query.ts（核心 Agent Loop，AsyncGenerator）              │
│                                                         │
│  while (true) {                                         │
│    1. BuildConfig（组装请求）                             │
│    2. CallModel（流式调用 API）                           │
│    3. ProcessStream（解析 response）                      │
│    4. CheckStop（检查是否结束）                           │
│       ├─ end_turn → return Terminal                      │
│       └─ tool_use → ExecuteTools                        │
│    5. ExecuteTools:                                      │
│       ├─ 串行权限检查                                    │
│       ├─ 并发执行通过的 tools                            │
│       └─ yield 每个结果                                  │
│    6. 循环回 BuildConfig                                 │
│  }                                                      │
│                                                         │
│  错误恢复:                                              │
│    - 413 → 压缩上下文重试                                │
│    - max_tokens → 继续生成                               │
│    - API error → FallbackModel                          │
│    - DoomLoop → 强制终止                                 │
└─────────────────────────────────────────────────────────┘
         │                    │                │
         ▼                    ▼                ▼
┌──────────────┐  ┌───────────────┐  ┌──────────────┐
│ api/claude.ts │  │ tools/* (18+) │  │ compact/*    │
│ LLM Streaming │  │ 工具执行       │  │ 上下文压缩    │
└──────────────┘  └───────────────┘  └──────────────┘
```

### 关键设计决策总结

| 设计点 | Claude Code 的选择 | 为什么 |
|---|---|---|
| Loop 结构 | AsyncGenerator | 流式输出 + 背压控制 + 多消费者 |
| 状态管理 | Messages 数组（唯一状态） | 可持久化、可重放、可压缩 |
| 终止条件 | 模型自己决定不再调 tool | 不是框架硬编码何时停 |
| 同轮多 tool | **并发执行** | 减少延迟，模型认为它们独立 |
| 权限检查 | **串行** | 需要用户交互，不能并行弹窗 |
| 错误处理 | 错误作为 ToolResult 反馈给模型 | 模型可以自适应换策略 |
| 子 Agent | 复用同一 runtime，限制工具集 | 不能递归 spawn（防无限循环） |
| 上下文溢出 | 自动 compact（压缩历史） | 不报错，静默处理 |

### 并行/串行决策的本质

并行/串行的决策本质上是**模型在做**：

- 如果模型认为两个操作独立 → 同一轮返回两个 tool_use → 框架并发执行
- 如果模型认为有依赖 → 只返回一个，等结果回来再决定下一步 → 天然串行

框架层面只是"忠实执行"模型的判断。

**真实 Agent 实现本质：一个 while 循环 + 一个 message 数组 + 并发工具执行器 + 错误恢复。核心只有 88 行，剩下 1600+ 行全是处理异常情况。**

### 参考资料

- Claude Code 源码分析：https://y-agent.github.io/inside-claude-code/02-agent-loop-query-engine.html
- Rust 重写版：https://github.com/instructkr/claw-code
- A2A Protocol 官方：https://a2a-protocol.org/v0.3.0/specification
- Anthropic Parallel Tool Use 文档：https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use
- ReAct 论文：Yao et al., 2022, "ReAct: Synergizing Reasoning and Acting in Language Models"