# 鸟瞰架构

> **原文标题：** Bird’s Eye Architecture  
> **原文副标题：** Architectural overview of Claude Code: a 512K-line React-in-terminal AI agent  
> **来源：** https://y-agent.github.io/inside-claude-code/00-birds-eye-architecture.html  
> **翻译日期：** 2026-07-26

Claude Code 架构概览：一个拥有 51.2 万行代码、在终端中运行 React 的 AI 智能体

## 1. 背景与范围

Claude Code v2.1.88 随 npm 包发布时，意外捆绑了一份 59.8 MB 的 source map（源映射）。源映射是一种将压缩后的生产代码映射回原始、可读源代码的文件。这次意外包含暴露了 Anthropic 生产级 AI 编程智能体完整、未经压缩的架构：每一个模块路径、函数名和功能标志。

该代码库由约 1,884 个文件、51.2 万行 TypeScript 构成。它使用 React 和 Ink（终端渲染器）构建，通过三级权限系统编排 40 个工具，并使用 ML 分类器对 shell 命令进行安全分类。其规模可与 Linux 内核 v1.0 相提并论。

本系列分为九个章节、共 19 篇，对这一架构进行分析。作为开篇，本文给出架构概览：识别共享智能体引擎，并追踪六层架构如何贯穿每一个子系统。后续各篇将详细研究每个子系统。

提取结果形成了下方交互式浏览器所展示的目录结构。点击任意文件夹即可展开并查看其内容、代码行数（LOC），以及介绍它的对应篇目。

上方目录树中的每个目录都带有一个 Part N 徽章，链接到介绍它的文章。下面按功能分组，简要浏览 `src/` 下的每个顶层子目录。

### 工具与平台层

- **`utils/`**（180K LOC，564 个文件）—— 最大的目录，占代码库的 35%。包含供其他所有模块使用的解析器、验证器、平台抽象和共享辅助函数。子领域包括提示词片段工具（[Part III.1](https://y-agent.github.io/inside-claude-code/03-prompt-assembly.html)）、通过 Seatbelt/Bubblewrap 实现的操作系统级沙箱（[Part IV.2](https://y-agent.github.io/inside-claude-code/06-safety-sandbox.html)）、配置加载器（[Part V.2](https://y-agent.github.io/inside-claude-code/09-auth-providers-flags.html)）、生命周期 hook 工具（[Part III.4](https://y-agent.github.io/inside-claude-code/11-hooks-lifecycle.html)），以及 fork 后的 Ink 终端渲染器（[Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)）。这个目录很能代表成熟的生产系统：可见功能建立在深厚的解析、验证和平台抽象之上。

### 前端 / 终端 UI

前端层合计约 140K LOC（占代码库 27%）—— 比大多数竞品工具的全部代码还要多。

- **`components/`**（81K LOC，389 个文件）—— 构成终端 UI 的 React/Ink 组件。包括根组件 `App.tsx`、权限对话框、流式 Markdown 输出、多行输入、状态栏和各工具专用的输出渲染器。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`hooks/`**（19K LOC，104 个文件）—— 用于状态管理的自定义 React hook：输入历史、API 密钥验证、工具权限（[Part IV.2](https://y-agent.github.io/inside-claude-code/06-safety-sandbox.html)）和通知投递（[Part III.4](https://y-agent.github.io/inside-claude-code/11-hooks-lifecycle.html)）。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`ink/`**（20K LOC，96 个文件）—— 一份 fork 后的 Ink 终端渲染器，带有自定义组件、DOM 抽象、输入事件处理和终端颜色工具。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`commands/`**（26K LOC，189 个文件）—— 用户可在会话中调用的 80 多个斜杠命令（`/branch`、`/advisor`、`/autofix-pr` 等）。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`keybindings/`**（3K LOC，14 个文件）—— 用于模式切换、导航和自定义绑定的键盘快捷键系统。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`screens/`**（6K LOC，3 个文件）—— 顶层屏幕组件：`REPL.tsx`（主交互界面）、`Doctor.tsx`（诊断）和 `ResumeConversation.tsx`（恢复会话）。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`vim/`**（1.5K LOC，5 个文件）—— 面向终端输入、支持移动、操作符和文本对象的 Vim 模式。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`buddy/`**（1.3K LOC，6 个文件）—— 伴侣精灵与通知助手，在长时间操作期间提供视觉反馈。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`state/`**（1.2K LOC，6 个文件）—— 通过 Zustand store 管理全局应用状态。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`context/`**（1K LOC，9 个文件）—— 用于通知（[Part III.4](https://y-agent.github.io/inside-claude-code/11-hooks-lifecycle.html)）、模态框和叠加层的 React context provider。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`outputStyles/`**（98 LOC，1 个文件）—— 用于自定义渲染格式的输出样式加载器。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。
- **`moreright/`**（25 LOC，1 个文件）—— 面向宽输出的水平滚动 hook。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。

### 后端 / 智能体引擎

后端合计约 320K LOC（62%），涵盖智能体循环、工具执行、API 通信和提示词组装。

- **`services/`**（54K LOC，130 个文件）—— 分担多种关注点的后端服务：Claude API 适配器（[Part II.1](https://y-agent.github.io/inside-claude-code/02-agent-loop-query-engine.html)）、上下文压缩级联（[Part III.2](https://y-agent.github.io/inside-claude-code/04-context-compaction.html)）、MCP 服务器生命周期（[Part VI.1](https://y-agent.github.io/inside-claude-code/10-model-context-protocol.html)）、遥测（[Part IX.1](https://y-agent.github.io/inside-claude-code/14-hidden-costs-context-manipulation.html)）、OAuth 流程（[Part V.2](https://y-agent.github.io/inside-claude-code/09-auth-providers-flags.html)）、记忆提取与团队同步（[Part III.3](https://y-agent.github.io/inside-claude-code/17-memory-hierarchy.html)）、插件服务层（[Part VI.3](https://y-agent.github.io/inside-claude-code/13-plugin-architecture.html)）、智能体会话摘要（[Part II.3](https://y-agent.github.io/inside-claude-code/07-multi-agent-orchestration.html)）、自动文档化（[Part VI.2](https://y-agent.github.io/inside-claude-code/12-skills-system.html)）、设置同步（[Part V.2](https://y-agent.github.io/inside-claude-code/09-auth-providers-flags.html)）和语音 I/O（[Part VIII.1](https://y-agent.github.io/inside-claude-code/18-native-runtime-voice-portability.html)）。
- **`tools/`**（51K LOC，184 个文件）—— 约 40 个遵循统一 Strategy 模式接口的工具实现。包括文件 I/O 工具（Read、Edit、Write、Glob、Grep）、子智能体生成器 `AgentTool`（[Part II.3](https://y-agent.github.io/inside-claude-code/07-multi-agent-orchestration.html)）、带沙箱的 shell 执行（[Parts 5](https://y-agent.github.io/inside-claude-code/05-tool-system.html)、[6](https://y-agent.github.io/inside-claude-code/06-safety-sandbox.html)）、MCP 代理（[Part VI.1](https://y-agent.github.io/inside-claude-code/10-model-context-protocol.html)）、技能调用（[Part VI.2](https://y-agent.github.io/inside-claude-code/12-skills-system.html)），以及任务、notebook 和 LSP 工具。详见 [Part IV.1](https://y-agent.github.io/inside-claude-code/05-tool-system.html)。
- **`cli/`**（12K LOC，19 个文件）—— CLI 传输层：参数解析、退出处理和终端打印。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。

### 智能体编排与上下文

- **`query/`**（652 LOC，4 个文件）—— 查询引擎配置和 token 预算计算，用于确定如何分配会话上下文。详见 [Part II.1](https://y-agent.github.io/inside-claude-code/02-agent-loop-query-engine.html)。
- **`tasks/`**（3.3K LOC，12 个文件）—— 面向本地智能体子进程、队友任务、远程智能体、本地 shell 和后台“梦境”摘要任务的任务执行框架。详见 [Part II.3](https://y-agent.github.io/inside-claude-code/07-multi-agent-orchestration.html)。
- **`coordinator/`**（369 LOC，1 个文件）—— 多智能体编排的协调器模式，父智能体在该模式下向子智能体分派子任务。详见 [Part II.3](https://y-agent.github.io/inside-claude-code/07-multi-agent-orchestration.html)。
- **`skills/`**（4K LOC，20 个文件）—— SKILL.md 加载器与注册表：发现、解析领域专长并将其注入系统提示词。详见 [Part VI.2](https://y-agent.github.io/inside-claude-code/12-skills-system.html)。
- **`schemas/`**（222 LOC，1 个文件）—— 用于验证 hook 配置文件的 hook schema 定义。详见 [Part III.4](https://y-agent.github.io/inside-claude-code/11-hooks-lifecycle.html)。
- **`plugins/`**（182 LOC，2 个文件）—— 面向可分发扩展包的插件发现与生命周期管理。详见 [Part VI.3](https://y-agent.github.io/inside-claude-code/13-plugin-architecture.html)。

### 记忆与上下文管理

- **`memdir/`**（1.7K LOC，8 个文件）—— CLAUDE.md 记忆目录系统：读取、写入并索引可跨会话保留的持久记忆文件。详见 [Part III.3](https://y-agent.github.io/inside-claude-code/17-memory-hierarchy.html)。
- **`assistant/`**（87 LOC，1 个文件）—— 会话历史持久化，使对话在断开连接后仍可恢复。详见 [Part III.2](https://y-agent.github.io/inside-claude-code/04-context-compaction.html)。

### 远程与原生运行时

- **`bridge/`**（12.6K LOC，31 个文件）—— 用于 VS Code 和 JetBrains 集成的 IDE 桥接子系统：WebSocket 传输、消息路由和会话移交。详见 [Part VII.1](https://y-agent.github.io/inside-claude-code/16-remote-runtime-bridge.html)。
- **`remote/`**（1.1K LOC，4 个文件）—— 面向云端智能体执行的远程会话管理。详见 [Part VII.1](https://y-agent.github.io/inside-claude-code/16-remote-runtime-bridge.html)。
- **`server/`**（358 LOC，3 个文件）—— 直连服务器模式，使 IDE 客户端无需桥接中继即可连接。详见 [Part VII.1](https://y-agent.github.io/inside-claude-code/16-remote-runtime-bridge.html)。
- **`upstreamproxy/`**（740 LOC，2 个文件）—— 用于通过企业代理路由 API 流量的 HTTP 代理中继。详见 [Part VII.1](https://y-agent.github.io/inside-claude-code/16-remote-runtime-bridge.html)。
- **`native-ts/`**（4K LOC，4 个文件）—— 原生 TypeScript 模块：颜色差异算法、tree-sitter 文件索引和 Yoga 布局绑定。详见 [Part VIII.1](https://y-agent.github.io/inside-claude-code/18-native-runtime-voice-portability.html)。
- **`voice/`**（54 LOC，1 个文件）—— 启用语音输入/输出的语音模式功能标志。详见 [Part VIII.1](https://y-agent.github.io/inside-claude-code/18-native-runtime-voice-portability.html)。

### 配置与入口点

- **`entrypoints/`**（4K LOC，8 个文件）—— CLI（`cli.tsx`）、MCP 服务器（`mcp.ts`）、初始化（`init.ts`）和 SDK（`sdk/`，[Part II.2](https://y-agent.github.io/inside-claude-code/15-agent-sdk-structured-io.html)）的应用入口点。详见 [Part I.2](https://y-agent.github.io/inside-claude-code/01-end-to-end-workflow.html)。
- **`constants/`**（2.6K LOC，21 个文件）—— 功能标志、模型列表、API 速率限制和 beta 标志（[Part IX.1](https://y-agent.github.io/inside-claude-code/14-hidden-costs-context-manipulation.html)）。详见 [Part V.2](https://y-agent.github.io/inside-claude-code/09-auth-providers-flags.html)。
- **`migrations/`**（603 LOC，11 个文件）—— 在不同 Claude Code 版本间升级配置的设置迁移脚本。详见 [Part V.2](https://y-agent.github.io/inside-claude-code/09-auth-providers-flags.html)。
- **`bootstrap/`**（1.8K LOC，1 个文件）—— 初始化运行时环境的应用引导状态。详见 [Part I.2](https://y-agent.github.io/inside-claude-code/01-end-to-end-workflow.html)。
- **`types/`**（3.4K LOC，11 个文件）—— 代码库各处使用的共享 TypeScript 类型定义。详见 [Part II.1](https://y-agent.github.io/inside-claude-code/02-agent-loop-query-engine.html)。

### 顶层根文件

- **`main.tsx`** —— 将入口点与 React 渲染连接起来的应用根节点（[Part I.2](https://y-agent.github.io/inside-claude-code/01-end-to-end-workflow.html)）。
- **`QueryEngine.ts`**、**`query.ts`** —— 查询引擎类与编排逻辑（[Part II.1](https://y-agent.github.io/inside-claude-code/02-agent-loop-query-engine.html)）。
- **`Tool.ts`**、**`tools.ts`** —— 工具基类与注册表（[Part IV.1](https://y-agent.github.io/inside-claude-code/05-tool-system.html)）。
- **`Task.ts`** —— 用于管理智能体子进程的任务基类（[Part II.3](https://y-agent.github.io/inside-claude-code/07-multi-agent-orchestration.html)）。
- **`commands.ts`** —— 斜杠命令注册表（[Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)）。
- **`context.ts`** —— 面向提示词组装的上下文类型定义（[Part III.1](https://y-agent.github.io/inside-claude-code/03-prompt-assembly.html)）。
- **`cost-tracker.ts`** —— token 成本跟踪与报告（[Part IX.1](https://y-agent.github.io/inside-claude-code/14-hidden-costs-context-manipulation.html)）。
- **`setup.ts`** —— 设置与初始化逻辑（[Part I.2](https://y-agent.github.io/inside-claude-code/01-end-to-end-workflow.html)）。
- **`ink.ts`** —— Ink 渲染器设置（[Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)）。

### Vendor 目录

- **`vendor/`**（438 LOC，4 个文件）—— 四个用 C/C++ 和 Rust 编写并随项目提供的 N-API 原生模块：`audio-capture-src/`（跨平台音频，151 LOC）、`image-processor-src/`（兼容 Sharp 的图像处理，162 LOC）、`modifiers-napi-src/`（macOS 键盘修饰键检测，67 LOC）和 `url-handler-src/`（macOS Apple Events URL 处理器，58 LOC）。它们会编译为平台专用二进制文件，并通过 `src/native-ts/` 中的 TypeScript 包装器访问。详见 [Part VIII.1](https://y-agent.github.io/inside-claude-code/18-native-runtime-voice-portability.html)。

---

## 2. 共享引擎，多种接口

和大多数生产级 AI 编程智能体一样，Claude Code 作为终端应用（TUI）运行。其关键架构洞见，是将**共享智能体引擎**（约 320K LOC）与消费其输出的多种**接口适配器**清晰分离。引擎生成事件流（模型 token、工具调用、结果、错误）；每个适配器将这些事件渲染到不同媒介。引擎不了解显示层，UI 也不了解 API 协议。代码库使用 TypeScript 编写（512K LOC），运行于 Bun 运行时（冷启动约 150ms）。

### 共享智能体引擎（约 320K LOC，62%）

Claude Code 的核心是一个独立于任何用户界面的**共享智能体引擎**。它包含 ReAct 循环（在模型推理与工具执行之间交替）、约 40 个工具实现、Claude API 客户端、提示词组装、上下文压缩、权限执行和多智能体编排。主要目录为 `src/tools/`（51K LOC）、`src/services/`（54K LOC）和 `src/utils/`（180K LOC）。智能体循环详见 [Part II.1](https://y-agent.github.io/inside-claude-code/02-agent-loop-query-engine.html)。

### 共享引擎之上的三种入口模式

引擎暴露一个流式事件接口——在事件（模型 token、工具调用、工具结果、错误）生成时逐一 yield。三种不同的入口模式消费这一接口，各自面向不同用例：

1. **CLI**（约 140K LOC）—— 交互式终端 UI。这是一个完整的声明式 UI 应用，拥有 389 个组件、模态权限对话框、流式 Markdown 渲染、80 多个斜杠命令和 Vim 键位绑定。用户在终端中运行 `claude` 时，交互的就是这一界面。详见 [Part V.1](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。

2. **SDK** —— 一种无头编程接口，用于将 Claude Code 嵌入脚本、CI/CD 流水线和自定义应用。SDK 通过结构化 API 暴露同一个智能体引擎：调用者可发送任务、接收流式结果并控制执行，而不需要任何终端 UI。正因如此，才能在 shell 脚本中运行 `claude -p "fix the bug"`，或在 Node.js 程序中使用 `import { query } from "@anthropic-ai/claude-code"`。详见 [Part II.2](https://y-agent.github.io/inside-claude-code/15-agent-sdk-structured-io.html)。

3. **Bridge / MCP** —— 面向 IDE 集成（VS Code、JetBrains）和模型上下文协议的协议适配器。桥接子系统（12.6K LOC）管理 IDE 扩展与运行中的 Claude Code 实例之间的 WebSocket 连接。MCP 入口点则将 Claude Code 本身变成可供其他智能体调用的 MCP 服务器。详见 [Parts 10](https://y-agent.github.io/inside-claude-code/10-model-context-protocol.html) 和 [16](https://y-agent.github.io/inside-claude-code/16-remote-runtime-bridge.html)。

正是这种三入口模式设计，使代码库能够清晰划分为引擎代码与接口代码。引擎不了解终端、IDE 或 HTTP——它只负责生成事件。每种入口模式再将这些事件适配到各自媒介。

---

## 3. 六层架构

**Claude Code 的架构由六层堆叠而成，并严格向下依赖——每一层只依赖其下方各层，这与操作系统内核和网络协议栈采用的原则相同。**

这种分层设计很重要，因为它使系统保持模块化：无需 UI 即可测试工具执行引擎，无需 API 即可测试权限系统，添加新工具也不必改动智能体循环。这一不变量在 51.2 万行代码中始终如一。

![](https://y-agent.github.io/inside-claude-code/00-birds-eye-architecture_files/mediabag/six-layers.svg)

**图 1：六层架构。每一层只依赖其下方各层。**

以下小节自底向上追踪每一层。层编号是分析性的，而非源码中的字面划分：源代码并未如此命名这些层，但导入图清楚地呈现了这种依赖结构。

### 第 1 层：入口与引导

在智能体开始工作之前，它必须完成用户身份验证、加载配置、检测平台并选择入口模式——所有工作都要在约 150ms 内完成。`src/main.tsx` 是唯一入口点。它并行执行受 I/O 限制的初始化步骤（读取配置、预取凭据、记录分析检查点），以保持快速启动。配置遵循严格的优先级层次：环境变量 > 本地 `.claude/settings.json` > 项目 `CLAUDE.md` > 用户设置 > 默认值。借助这一层次，企业管理员无需修改用户配置，就能覆盖本地偏好（例如强制启用沙箱模式）。

引导过程还会决定启动哪一种**入口模式**：交互式 REPL（默认的 `claude` 命令）、一次性 SDK 执行（`claude -p "task"`），或 MCP 服务器模式（`claude mcp`）。每种模式共享同一个智能体引擎，但接入不同的 I/O 适配器。参见 [Part I.2](https://y-agent.github.io/inside-claude-code/01-end-to-end-workflow.html) 和 [Part V.2](https://y-agent.github.io/inside-claude-code/09-auth-providers-flags.html)。

### 第 2 层：智能体循环——内核

这是系统的核心。智能体循环实现了 **ReAct（Reason + Act，推理 + 行动）模式**——模型在思考下一步该做什么与通过工具采取行动之间循环交替。

核心实现位于两个文件中：

- **`src/query.ts`** —— `queryLoop()` 函数（第 241 行）是内部的 `while(true)` 循环。每次迭代都会调用 Claude API，检查响应是否包含 `tool_use` 块（第 829 行），依次执行请求的工具，并决定继续（`needsFollowUp = true`，第 834 行）还是退出（`if (!needsFollowUp)`，第 1062 行）。
- **`src/QueryEngine.ts`** —— `submitMessage()` 方法（第 209 行）将 `queryLoop()` 包装为异步生成器，在每个事件产生时将其 yield 给调用方。

基于生成器的设计是关键架构选择。下图比较了两种方式：阻塞循环会一直运行到完成，之后一次性返回全部结果；生成器模式则在每个事件产生时立即 yield。

![](https://y-agent.github.io/inside-claude-code/00-birds-eye-architecture_files/mediabag/blocking-vs-generator.svg)

**图 2：阻塞循环与基于生成器的循环。生成器以增量方式 yield 事件，使 UI 能够实时渲染并施加背压。**

在阻塞模型（a）中，智能体一直运行到完成——调用 API、执行工具、再次调用 API——而 UI 在全部结果以单个批次抵达前始终空闲。在生成器模型（b）中，智能体在每个事件（模型 token、工具结果或错误）产生时将其 **yield**。UI 会实时增量渲染：用户能看到 token 随模型生成而流式出现，也能看到工具完成后立即展示的输出。这就是**生产者—消费者模式**——智能体生产事件；UI 消费并渲染事件；生成器协议提供自然的流量控制（背压），无需显式管理缓冲区。

同一个生成器也支持上文所述的三种入口模式：CLI 订阅事件并渲染到终端，SDK 订阅事件并发出结构化 JSON，桥接层则订阅事件并通过 WebSocket 转发——三者消费的是同一条事件流。

### 第 3 层：工具执行——系统调用接口

LLM 只能生成文本。要成为智能体，它需要在推理（“我应该检查这个文件”）与行动（实际读取该文件）之间建立桥梁。Claude Code 实现了约 40 个这样的桥梁——称为**工具**——并将它们置于统一接口之后（定义于 `src/Tool.ts` 第 362 行）：每个工具都有用于分发的 `name`、模型必须满足的 `inputSchema`（JSON Schema），以及执行操作的 `execute()` 函数。智能体循环按名称分发，并依据 schema 验证，因此添加新工具不需要改动循环。

这些工具分为六类：

| 类别 | 示例 | 用途 |
|---|---|---|
| 文件 I/O | Read、Edit、Write、Glob、Grep | 浏览和修改代码库 |
| 执行 | BashTool（12K LOC）、NotebookEdit | 运行命令、脚本和 notebook |
| 智能体 | AgentTool、SendMessage | 生成子智能体、进行智能体间通信 |
| 外部 | WebFetch、WebSearch、MCPTool | 访问互联网和 MCP 服务器 |
| 知识 | LSPTool、SkillTool、TodoWrite | 语言服务器、技能和任务跟踪 |
| 元工具 | TaskCreate、ToolSearch | 管理智能体自身的工作流 |

**关键设计选择：串行执行。** `src/services/tools/toolOrchestration.ts` 中的 `runToolsSerially()` 函数（第 118 行）逐个处理工具调用。当模型编辑某个文件后再读取它时，读取操作必须看到编辑后的内容。并行执行会引入竞态条件，进而造成 token 浪费并破坏信任。唯一的例外是流式工具执行，它会让网络 I/O 与计算重叠进行。

**延迟加载**可保持较低的上下文成本：不会一次性将全部 40 个工具 schema 都发送给模型。系统使用 BM25 相关性排序，只加载当前任务最可能需要的 schema，其作用类似工具定义的虚拟内存——schema 按需“换入”，而非始终驻留，每轮可节省数千个 token。参见 [Part IV.1](https://y-agent.github.io/inside-claude-code/05-tool-system.html)。

### 第 4 层：权限与安全——纵深防御

一个能够运行 `rm -rf /`、向 `main` 提交代码或使用 `curl` 将敏感数据发送到外部服务器的 AI 智能体，天然具有危险性。传统软件中的所有操作由开发者控制；而在这里，是由_模型_决定执行什么——模型可能出错、产生幻觉，也可能被提示词注入操纵。Claude Code 通过**四层防御**应对这一问题：

![](https://y-agent.github.io/inside-claude-code/00-birds-eye-architecture_files/mediabag/permission-tiers.svg)

**图 3：三级权限系统，并以操作系统级沙箱作为遏制风险的最后保障。**

举个具体例子：当模型请求 `BashTool` 执行命令 `git push --force origin main` 时，系统首先检查静态规则（第 1 级：项目配置是否允许 force-push？）。与此同时，ML 分类器（第 2 级）通过 tree-sitter 将命令解析为 AST 并评估其风险。如果任一级将命令标记为危险，交互式审批对话框（第 3 级）就会向用户展示完整命令及其上下文。即使用户批准，操作系统沙箱（macOS 上的 Seatbelt、Linux 上的 Bubblewrap）仍会限制影响范围——进程无法访问项目目录之外的文件。

仅 `src/tools/BashTool/` 就有 12,411 行代码——比许多完整的 CLI 工具还要多。三级权限检查实现在 `src/utils/permissions/permissions.ts` 中（`hasPermissionsToUseTool()`，第 473 行）。参见 [Part IV.2](https://y-agent.github.io/inside-claude-code/06-safety-sandbox.html)。

### 第 5 层：服务——基础设施

智能体循环（第 2 层）和工具（第 3 层）都依赖共享基础设施：API 通信、上下文窗口管理、记忆持久化、遥测和扩展协议。服务层（`src/services/`，54K LOC）将这些能力集中为五个子系统：

1. **API 客户端**（`src/services/api/claude.ts`，3,419 行）—— 管理与 Claude API 的流式连接。处理提示词缓存（复用已缓存前缀，最多可降低 90% 的成本与延迟）、自动模型回退（某个模型过载时切换到其他模型）、采用指数退避的重试逻辑，以及服务器发送事件（SSE）解析。参见 [Part II.1](https://y-agent.github.io/inside-claude-code/02-agent-loop-query-engine.html)。

2. **上下文压缩**（`src/services/compact/`）—— 架构上最有趣的服务。200K-token 的上下文窗口听起来很大，但繁忙的编程会话在两小时内就会产生 400K+ token。压缩系统会采用逐渐激进的摘要策略：`autoCompactIfNeeded()` 在容量约达 75% 时触发，`microcompactMessages()` 保留提示词缓存前缀，而当 API 返回“prompt too long”错误时则触发反应式压缩。这与**缓存淘汰**直接类似——多种策略具有不同的质量/延迟权衡，并由内存压力触发。参见 [Part III.2](https://y-agent.github.io/inside-claude-code/04-context-compaction.html)。

3. **记忆层次结构**（`src/services/SessionMemory/`、`src/services/extractMemories/`、`src/services/teamMemorySync/`、`src/memdir/`）—— 五层持久记忆：项目级 `CLAUDE.md` 文件、重启后仍保留的会话记忆、从对话中自动提取的记忆、后台“梦境”整合，以及团队共享记忆。参见 [Part III.3](https://y-agent.github.io/inside-claude-code/17-memory-hierarchy.html)。

4. **MCP 服务器管理**（`src/services/mcp/`）—— 发现、启动并管理通过外部工具扩展智能体的模型上下文协议服务器。每个 MCP 服务器都作为独立进程运行，拥有自己的生命周期。参见 [Part VI.1](https://y-agent.github.io/inside-claude-code/10-model-context-protocol.html)。

5. **遥测与分析**（`src/services/analytics/`）—— Segment + Datadog 遥测，跟踪 token 用量、工具调用模式、错误率和会话指标。这些数据会反馈到 Claude Code 的开发中——了解真实用户如何与智能体互动，有助于判断哪些工具需要优化，以及哪些安全检查过严或过松。参见 [Part IX.1](https://y-agent.github.io/inside-claude-code/14-hidden-costs-context-manipulation.html)。

### 第 6 层：终端 UI——应用层

智能体生成一条事件流——模型 token、工具调用、工具结果、错误和权限请求——用户则需要实时看到它们，批准或拒绝操作、提供输入并监控进度。Claude Code 构建了一套完整的交互式 UI，包含 389 个组件（`src/components/`）、104 个自定义状态管理 hook（`src/hooks/`），以及一套 fork 后的终端渲染引擎（`src/ink/`，20K LOC）。关键能力包括：

- **流式 Markdown** —— 模型输出以格式化 Markdown（语法高亮、标题、列表）逐 token 实时渲染。
- **权限对话框** —— 智能体请求危险操作时，模态对话框会展示完整命令、风险级别和相关上下文。用户可通过键盘快捷键批准或拒绝。
- **斜杠命令** —— 80 多个命令（`/compact`、`/branch`、`/advisor` 等），供用户在会话中控制智能体、管理上下文或触发工作流。
- **双缓冲** —— 屏幕渲染器写入离屏缓冲区，计算它与当前显示内容的差异，只更新发生变化的字符——避免快速输出时出现闪烁。
- **Vim 模式** —— 完整的 Vim 风格输入，支持移动、操作符和文本对象，适合偏好模态编辑的用户。

完整的终端 UI 架构——组件层次、渲染流水线、斜杠命令系统和键盘导航——详见 [Part V.1：CLI、命令与 UI](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。

---

## 4. Claude Code 的差异化之处

大多数 AI 编程智能体都有共同骨架：一个 LLM、十来个工具和一个 REPL。Claude Code 的独特之处，在于它沿每个维度都投入得极深——不只是工具更多，而是拥有一整条组装 65+ 个提示词片段的中间件流水线；不只是系统提示词，而是每轮注入实时状态的 50+ 条自适应通知；不只是基础命令，而是按分类组织的 80+ 个斜杠命令，其丰富程度足以媲美完整 IDE。

![](https://y-agent.github.io/inside-claude-code/00-birds-eye-architecture_files/mediabag/feature-surface.svg)

**图 4：Claude Code 与典型 AI 编程智能体的功能面比较。计数来自 v2.1.88 源代码；“典型智能体”数值反映 Aider、Continue 和 Cline 等开源工具的情况。**

其中三个子系统与所有已公开的竞争者相比，不仅在数量上，而且在性质上都存在差异。下面先逐一研究它们，再讨论进一步放大这些优势的横切主题（上下文管理、记忆和功能标志）。

### 提示词组装：由 65 个片段构成的中间件流水线

在模型看到用户输入的第一个 token 之前，一条中间件流水线会将 65+ 个片段组装到上下文窗口中。这些片段经过_有序_排列，使前约 55K token 形成一个符合 Anthropic 提示词缓存条件的**稳定前缀**（缓存命中时最多可降低 90% 成本）。每次添加、删除或重新排序片段，都可能使缓存失效——因此，流水线顺序是承载系统的重要架构约束，而不是一种便利设计。

![](https://y-agent.github.io/inside-claude-code/00-birds-eye-architecture_files/mediabag/prompt-pipeline.svg)

**图 5：提示词组装流水线。片段经过排序，使顶部约 55K token 形成符合提示词缓存条件的稳定前缀。缓存边界将稳定前缀与易变的消息流分开。完整分析见 [Part III.1](https://y-agent.github.io/inside-claude-code/03-prompt-assembly.html)。**

### 系统提醒：实时通知架构

大多数智能体在轮次之间都是“盲”的——它们知道用户说了什么、自己做了什么，却不了解周围环境发生的变化。Claude Code 会在每条用户消息后注入 **50+ 条系统提醒**，向模型传递易变状态（git 状态、文件变更、任务进度、权限决定），同时不扰动已缓存的提示词前缀。正是这套通知系统让智能体持续感知环境。

![](https://y-agent.github.io/inside-claude-code/00-birds-eye-architecture_files/mediabag/reminder-timeline.svg)

**图 6：系统提醒注入时间线。提醒在每条用户消息之后附加到消息流中，将实时状态传递给模型，而不会使已缓存的系统提示词前缀失效。参见 [Part III.4](https://y-agent.github.io/inside-claude-code/11-hooks-lifecycle.html)。**

提醒类别包括环境状态（git 分支、未提交变更、工作目录）、任务跟踪（进行中的步骤、待处理操作）、工具反馈（近期结果、权限决定）、用户偏好（当前模式、输出样式）和上下文提示（最近查看的文件、会话摘要）。

### 命令面：80+ 个斜杠命令

大多数智能体只提供 5–10 个用于基本会话控制的命令，而 Claude Code 暴露了横跨八个类别的 **80+ 个斜杠命令**——其命令面更像 IDE，而非聊天机器人。

| 类别 | 示例 | 用途 |
|---|---|---|
| 上下文 | `/compact`、`/add-dir`、`/memory` | 管理上下文窗口 |
| 智能体 | `/agents`、`/advisor`、`/autofix-pr` | 分派智能体工作流 |
| 模式 | `/plan`、`/fast`、`/vim`、`/diff` | 切换交互模式 |
| 会话 | `/resume`、`/clear`、`/save` | 控制会话生命周期 |
| Git | `/branch`、`/commit`、`/pr` | 直接集成 Git |
| 扩展 | `/mcp`、`/skills`、`/plugin` | 管理扩展 |
| 配置 | `/settings`、`/model`、`/permissions` | 配置行为 |
| 诊断 | `/help`、`/doctor`、`/cost` | 检查智能体状态 |

其实现横跨 `src/commands/` 中 189 个文件、共 26K LOC。每个命令都通过统一接口注册——与工具所用的 Strategy 模式相同——从而实现一致的发现机制、Tab 补全和帮助文本。完整命令系统架构见 [Part V.1：CLI、命令与 UI](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html)。

### 将上下文视为受管理资源

200K-token 的上下文窗口听起来很大，直到你看到它被填满。单个大型源文件会消耗 8K–12K token。在 monorepo 上执行一次 `grep` 会返回 30K token。两小时的活跃编程会产生 400K+ token 的原始对话——是窗口容量的两倍。Claude Code 像操作系统管理 RAM 一样对待上下文：它是一种稀缺资源，需要显式管理。

约束始终为：

\[|S_{\text{system}}| + |H_{\text{history}}| + |T_{\text{tools}}| + |R_{\text{reminders}}| \;\leq\; W\]

其中 \(W = 200\text{K}\) token。四个子系统协同满足这一约束：

1. **提示词组装**（[Part III.1](https://y-agent.github.io/inside-claude-code/03-prompt-assembly.html)）—— 一条中间件流水线，从 12+ 个来源构建系统提示词：基础指令、项目 `CLAUDE.md` 文件、活跃技能、工具 schema 和缓存片段。流水线经过排序，使前约 15K token 形成符合提示词缓存条件的稳定前缀（缓存命中时最多降低 90% 成本）。

2. **上下文压缩**（[Part III.2](https://y-agent.github.io/inside-claude-code/04-context-compaction.html)）—— 当会话历史接近预算上限时，逐步采用更激进的摘要策略：容量达到约 75% 时自动压缩、保留缓存前缀的微压缩，以及 API 报错时的反应式压缩。这与缓存淘汰策略直接类似——多种策略具有不同的质量/延迟权衡，并由内存压力触发。

3. **系统提醒**（[Part III.4](https://y-agent.github.io/inside-claude-code/11-hooks-lifecycle.html)）—— 在会话过程中自适应注入 50+ 条消息，将易变状态（git 状态、文件变更、任务进度、用户偏好）传递给模型，且_不扰动已缓存的提示词前缀_。提醒附加在用户消息之后，因此不会使缓存失效，却仍能引起模型注意。智能体正是通过这一机制，在轮次之间持续感知环境。

4. **延迟工具加载**（[Part IV.1](https://y-agent.github.io/inside-claude-code/05-tool-system.html)）—— 不会一次性将约 40 个工具 schema 全部发送给模型。系统使用 BM25 相关性排序，只加载当前任务最可能需要的 schema——这相当于工具定义的虚拟内存，按需换入 schema，而不是让它们全部驻留。

这四个子系统共同实现了可称为**上下文操作系统**的机制：分配、淘汰、缓存和按需分页——只不过它们处理的是 token 预算，而不是 RAM 字节。

### 跨会话存续的记忆

大多数智能体是无状态的——会话结束后，它们会忘记一切。Claude Code 实现了一套**五层记忆层次结构**，让知识跨会话、跨项目乃至跨团队持续存在：

| 层级 | 范围 | 机制 |
|---|---|---|
| 项目记忆 | 每个代码库 | 提交到代码库的 `CLAUDE.md` 文件 |
| 会话记忆 | 每次会话 | 由 SQLite 支持的会话历史 |
| 提取记忆 | 跨会话 | 自动提取用户偏好和项目事实 |
| 梦境整合 | 后台 | 离线摘要过去的会话（名称源自神经科学中的睡眠整合） |
| 团队同步 | 跨用户 | 通过 `teamMemorySync` 在团队成员之间共享记忆 |

智能体会将习得的项目知识、编程偏好和团队惯例延续下去。当用户说“记住，一律使用 pytest，不要使用 unittest”时，这一偏好会被提取、存储，并注入未来会话。参见 [Part III.3](https://y-agent.github.io/inside-claude-code/17-memory-hierarchy.html)。

### 作为部分求值的功能标志

发布的二进制文件并不是单一程序——它是由 88 个编译时标志和 50+ 个运行时开关选择出来的一族程序。这套双层系统控制哪些功能存在于二进制文件中，以及哪些功能对特定用户启用。

**编译时标志**由 Bun 打包器在构建期间解析。当某个标志求值为 `false` 时，打包器会从 bundle 中删除整个条件代码块——包括全部导入、字符串字面量和副作用。这就是部分求值：在编译时解析参数，将通用程序特化为具体程序，其原理与 C 中的 `#ifdef` 或 C++ 中的模板特化相同。结果是，未发布功能不只是被禁用——它们会从二进制文件中_消失_，逆向工程也看不到。受构建时开关控制最严密的功能包括：

| 标志 | 引用次数 | 所控制的功能 |
|---|---:|---|
| `KAIROS` | ~154 | 后台异步智能体工作（涉及智能体循环、UI、会话和 SDK） |
| `TRANSCRIPT_CLASSIFIER` | ~107 | 基于 ML 的自动模式选择 |
| `TEAMMATE` | ~51 | 团队记忆同步 |
| `VOICE_MODE` | ~46 | 语音转文本的流式输入 |
| `PROACTIVE` | ~37 | 智能体主动建议操作 |
| `COORDINATOR_MODE` | ~32 | 多智能体群体编排 |

像 `KAIROS` 这样拥有 154 处代码引用的标志，代表着一个完整子系统——后台智能体执行——它贯穿智能体循环、UI 渲染、会话管理和 SDK。只需翻转一个构建标志，就能独立编译、测试和回滚该系统。

**运行时标志**构成第二层。Claude Code 启动时会从远程功能标志服务 GrowthBook（`cdn.growthbook.io`）获取标志值。这些标志支持渐进式发布（5% → 25% → 100%）、按组织定向和 A/B 测试——全都不需要发布新的二进制文件。标志 API 通过一个刻意冗长的函数访问：`getFeatureValue_CACHED_MAY_BE_STALE()`，其名称警告调用者，该值缓存在本地，可能比服务器滞后数分钟。这是在严格一致性与低延迟之间做出的取舍——智能体永远不会为了检查标志而阻塞等待网络调用。

运行时标志以细粒度控制智能体行为：`tengu_ultrathink` 启用扩展推理，`tengu_tight_weave` 改变子智能体响应格式，`tengu_disable_bypass_permissions_mode` 可以远程禁用不受限制的执行模式。`tengu_marble_anvil` 和 `tengu_cobalt_lantern` 等经过模糊处理的代号暗示着正在进行的 A/B 实验。总计 757 个不同的 `tengu_*` 事件与标志名称，定义了远程控制面。

一个功能可以同时位于_两个_层级之后：构建时标志确保代码存在于二进制文件中，运行时标志则控制在拥有该代码的用户群体中如何发布。这种分层开关机制使重大功能（语音输入、协调器模式、后台智能体）能够安全试验，而不危及核心产品稳定性。参见 [Part V.2](https://y-agent.github.io/inside-claude-code/09-auth-providers-flags.html) 和 [Part IX.1](https://y-agent.github.io/inside-claude-code/14-hidden-costs-context-manipulation.html)。

---

## 5. 系列路线图

**后续每一篇都会深入一个特定子系统，并将其设计与本文建立的基础联系起来。**

| 章节 | 篇目 | 标题 | 核心洞见 |
|---|---|---|---|
| **I. 概览** | **I.1** | **鸟瞰架构**（本文） | 共享引擎、六层架构、上下文工程 |
|  | I.2 | [端到端工作流](https://y-agent.github.io/inside-claude-code/01-end-to-end-workflow.html) | 追踪一条提示词从按键输入到响应渲染的全过程 |
| **II. 智能体框架** | II.1 | [智能体循环与查询引擎](https://y-agent.github.io/inside-claude-code/02-agent-loop-query-engine.html) | 异步生成器是关键抽象 |
|  | II.2 | [智能体 SDK 与结构化 I/O](https://y-agent.github.io/inside-claude-code/15-agent-sdk-structured-io.html) | 基于同一引擎的无头编程接口 |
|  | II.3 | [多智能体编排](https://y-agent.github.io/inside-claude-code/07-multi-agent-orchestration.html) | AI 智能体的 fork() |
| **III. 上下文** | III.1 | [提示词组装](https://y-agent.github.io/inside-claude-code/03-prompt-assembly.html) | 在模型看到输入前，由中间件流水线组装上下文 |
|  | III.2 | [上下文压缩](https://y-agent.github.io/inside-claude-code/04-context-compaction.html) | 会话历史的缓存淘汰策略 |
|  | III.3 | [记忆层次结构](https://y-agent.github.io/inside-claude-code/17-memory-hierarchy.html) | 跨会话存续的五层记忆 |
|  | III.4 | [Hook 与生命周期](https://y-agent.github.io/inside-claude-code/11-hooks-lifecycle.html) | 事件驱动的扩展与系统提醒 |
| **IV. 工具** | IV.1 | [工具系统与注册表](https://y-agent.github.io/inside-claude-code/05-tool-system.html) | 大规模统一接口——智能体的“双手” |
|  | IV.2 | [安全与沙箱](https://y-agent.github.io/inside-claude-code/06-safety-sandbox.html) | 面向 AI 智能体的纵深防御 |
| **V. 调用** | V.1 | [CLI、命令与 UI](https://y-agent.github.io/inside-claude-code/08-cli-commands-ui.html) | 渲染到 TTY 的桌面级 UI |
|  | V.2 | [身份验证、提供商与标志](https://y-agent.github.io/inside-claude-code/09-auth-providers-flags.html) | 终端应用的 OAuth 与 88 个构建时标志 |
| **VI. 扩展** | VI.1 | [模型上下文协议](https://y-agent.github.io/inside-claude-code/10-model-context-protocol.html) | AI 智能体的 LSP——通用工具协议 |
|  | VI.2 | [技能系统](https://y-agent.github.io/inside-claude-code/12-skills-system.html) | 注入专长，而非扩展能力 |
|  | VI.3 | [插件架构](https://y-agent.github.io/inside-claude-code/13-plugin-architecture.html) | 将扩展点组合成插件平台 |
| **VII. 远程** | VII.1 | [远程运行时与桥接](https://y-agent.github.io/inside-claude-code/16-remote-runtime-bridge.html) | 通过 WebSocket 集成 IDE |
| **VIII. 原生** | VIII.1 | [原生运行时与 Vendor](https://y-agent.github.io/inside-claude-code/18-native-runtime-voice-portability.html) | N-API 模块、语音与跨平台能力 |
| **IX. 透明度** | IX.1 | [隐藏成本与遥测](https://y-agent.github.io/inside-claude-code/14-hidden-costs-context-manipulation.html) | 智能体向 Anthropic 回传了什么 |

_下一篇：[Part I.2——端到端工作流](https://y-agent.github.io/inside-claude-code/01-end-to-end-workflow.html)，追踪一条提示词从按键输入、经过完整流水线，直至渲染出响应的全过程。_

---

_本分析基于 Claude Code v2.1.88 的 source map，出于教育目的对其进行提取和研究。所有代码片段均由 source map 重建，可能与实际实现有所不同。Claude Code 是 Anthropic, PBC 的产品。_
