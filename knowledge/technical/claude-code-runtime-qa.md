# Claude Code / Agent Runtime 机制问答

> 来源：2026-07-07 与 Sakana 的代码阅读讨论。目标是把当时围绕 `claude-code`、OpenClaw、agent memory、tool calling、skills、subagent、上下文压缩等问题形成的知识，整理成一问一答的长期知识卡。
>
> 主要源码参照：`/home/azureuser/.openclaw/workspace/claude-code`。

---

## 1. Claude Code 里的 tool/function calling 到底是什么？

**问：模型调用工具时，真正传给 LLM 的是什么？**

答：传给 LLM 的不是本地函数本身，而是工具的 **schema + prompt 描述**。

`claude-code` 本地有一组 TypeScript `Tool` 对象，每个工具包含：

- `name`
- `description` / `prompt()`
- `inputSchema` 或 `inputJSONSchema`
- `call()` 执行函数
- 权限、结果大小限制、展示逻辑等 metadata

这些 `Tool` 对象会被转换成 Anthropic Messages API 的 `tools` 参数。也就是说，LLM 看到的是类似：

```json
{
  "name": "Read",
  "description": "Reads a file from the local filesystem...",
  "input_schema": {
    "type": "object",
    "properties": {
      "file_path": { "type": "string" }
    },
    "required": ["file_path"]
  }
}
```

模型并不知道本地 `call()` 函数实现，只知道“有这么个工具、需要什么参数、什么时候该用”。

关键源码：

- `src/Tool.ts`
- `src/tools.ts`
- `src/utils/api.ts`
- `src/services/api/claude.ts`

---

## 2. 模型返回工具调用时，返回的是什么？

**问：LLM 决定用工具后，它返回什么？**

答：它返回 Anthropic Messages API 的 `tool_use` content block，而不是直接执行结果。

大概长这样：

```json
{
  "type": "tool_use",
  "id": "toolu_xxx",
  "name": "Read",
  "input": {
    "file_path": "/path/to/file"
  }
}
```

这只是模型的“请求执行工具”的声明。真正执行在本地 CLI/runtime 里发生。

---

## 3. 工具是怎么被真正执行的？

**问：模型返回 `tool_use` 后，谁来执行工具？**

答：`claude-code` 的本地 runtime 执行。

流程是：

```text
LLM 输出 tool_use
  → 本地 runtime 找到对应 Tool 对象
  → 校验 input schema
  → 检查权限 / hooks / policy
  → 调用 tool.call(input, context)
  → 得到本地执行结果
  → 包装成 tool_result
  → 下一轮作为 user message 发回模型
```

关键源码：

- `src/services/tools/toolExecution.ts`
- `src/services/tools/toolOrchestration.ts`
- `src/services/tools/StreamingToolExecutor.ts`
- `src/query.ts`

---

## 4. 工具结果如何回到模型上下文？

**问：工具执行完后，模型怎么知道结果？**

答：本地 runtime 会生成 `tool_result` block，作为下一轮 `user` message 发给模型。

形式类似：

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_xxx",
      "content": "file content here..."
    }
  ]
}
```

所以一次工具调用至少跨两个模型回合：

```text
Round 1:
  assistant → tool_use

本地执行工具

Round 2:
  user → tool_result
  assistant → 根据结果继续推理/回答/再调用工具
```

重点：**function calling 不是模型真的执行函数，而是模型输出结构化调用请求，本地 runtime 执行后再把结果喂回去。**

---

## 5. 默认有多少 built-in tools？

**问：`claude-code` 默认给模型多少工具？**

答：源码里 `getAllBaseTools()` 原始 base tools 约 21 个；`getTools()` 会过滤掉一些内部/特殊工具，例如：

- `ListMcpResourcesTool`
- `ReadMcpResourceTool`
- `SYNTHETIC_OUTPUT_TOOL_NAME`

所以默认传给 LLM 的 built-in tools 大约 19 个。

实际数量会变，因为还受这些因素影响：

- feature flag
- MCP tools
- deny rules
- simple mode
- embedded search tools
- deferred tool schema / tool search

结论：默认核心工具数量不是固定死的，但通常是十几个到二十个左右。

---

## 6. Skills 会不会让 tools 数量暴涨？

**问：如果有很多 skills，模型是不是会看到很多 `PdfSkillTool`、`CommitSkillTool` 之类的新工具？**

答：不会。通常模型只看到一个统一的 `Skill` tool。

多个 skill 不是多个 Anthropic tool，而是 `Skill` tool 的可调用目标变多。

也就是说：

```text
不是：
  PdfSkillTool
  CommitSkillTool
  ReviewSkillTool

而是：
  Skill({ skill: "pdf", args: ... })
  Skill({ skill: "commit", args: ... })
  Skill({ skill: "review", args: ... })
```

这样做的好处：

- 不让 tool schema 数量爆炸。
- skill 列表可以按需发现/注入。
- skill 本质是 prompt/workflow 包，而不是每个都变成 runtime primitive。

关键源码：

- `src/tools/SkillTool/SkillTool.ts`
- `src/tools/SkillTool/prompt.ts`
- `src/skills/loadSkillsDir.ts`
- `src/skills/bundledSkills.ts`

---

## 7. Skill 到底是什么？

**问：Skill 是函数、脚本，还是 prompt？**

答：Skill 本质上是 **prompt/workflow 包**。

一个 skill 通常是一个目录：

```text
.claude/skills/<skill-name>/
  SKILL.md
  scripts/
  assets/
  references/
```

`SKILL.md` 里有 frontmatter，例如：

```yaml
---
description: xxx
when_to_use: xxx
allowed-tools: Read, Bash, Grep
model: sonnet
context: fork
---
```

runtime 会扫描这些 skill，并解析成内部 `Command(type: prompt)`。

Skill 可以包含脚本，但脚本不会天然自动执行。它只是告诉模型“这个工作流应该怎么做、有哪些资源、可以调用哪些工具”。真正执行仍然要通过 Bash/PowerShell/Read/Grep 等已有 tools。

---

## 8. Skill 调用后，LLM 看到什么？

**问：模型调用 `Skill` 后，返回值是什么？完整 SKILL.md 会作为 tool_result 返回吗？**

答：通常不是。

inline skill 的表现是：

- `tool_result` 里只给短消息，例如：`Launching skill: <name>`。
- 真正的 `SKILL.md` 展开内容通过 `newMessages` 注入上下文。
- 也可以附带 `contextModifier` 改变后续上下文。

所以 LLM 看到的不是“工具结果里塞一整篇 skill 文档”，而是 runtime 把 skill 内容作为新的上下文消息插进去。

如果 skill 标记了 `context: fork`，则会开一个子 agent，由子 agent 执行 skill workflow，最后把子 agent 的结果作为 tool result 返回。

---

## 9. Skill 里的 shell 什么时候执行？

**问：`SKILL.md` 里的脚本会自动执行吗？**

答：分情况。

会在 prompt 展开时自动执行的是 inline shell expansion：

```md
!`cmd`
```

或 fenced code block 形式的 shell expansion。

这类内容会在 prompt 展开阶段通过 `executeShellCommandsInPrompt()` 调 `BashTool` 或 `PowerShellTool` 执行，并把输出替换进 prompt。

但普通 `scripts/` 目录里的脚本不会自动执行。它们只是可用资源；模型后续需要显式调用 Bash/PowerShell 才会执行。

另外 MCP skills 禁止 inline shell expansion。

关键源码：

- `src/utils/promptShellExecution.ts`

---

## 10. AgentTool 是不是也是 function calling？

**问：`AgentTool` 跟普通工具一样吗？**

答：从 LLM 协议层看，是一样的：它也是一个 tool/function call。

模型会输出：

```json
{
  "type": "tool_use",
  "name": "Agent",
  "input": {
    "prompt": "...",
    "agent_type": "..."
  }
}
```

本地 runtime 接到后启动子 agent。

区别在于：普通工具通常是一次本地函数执行；`AgentTool` 会开启一个新的 agent loop，里面也可能继续调用模型和工具。

关键源码：

- `src/tools/AgentTool/AgentTool.tsx`
- `src/tools/AgentTool/runAgent.ts`
- `src/tools/AgentTool/agentToolUtils.ts`

---

## 11. 同步 subagent 的结果如何返回？

**问：普通同步 `AgentTool` 调用会怎么返回？**

答：父 agent 会阻塞等待子 agent 完成。

流程：

```text
父模型输出 Agent tool_use
  → 本地启动 runAgent()
  → 子 agent 独立跑模型/工具循环
  → 子 agent 完成
  → finalizeAgentTool()
  → 父 agent 收到 tool_result
```

返回的 `tool_result` 里通常包含：

- 子 agent 最终文本
- metadata
- usage 信息
- 有时还有 output file 路径等

所以同步 subagent 是“父等待子完成，然后一次性拿结果”。

---

## 12. 异步 subagent 是怎么工作的？

**问：async subagent 的原始 function call 会返回最终结果吗？**

答：不会。异步 subagent 的原始 `AgentTool` 调用只返回“已启动”。

大概返回：

```text
async_launched
agentId: xxx
outputFile: xxx
```

后台实际执行路径：

```text
AgentTool 原始调用返回 async_launched
  → runAsyncAgentLifecycle() 在后台跑 runAgent()
  → 子 agent 独立执行
  → 完成后 finalizeAgentTool()
  → completeAsyncAgent()
  → enqueueAgentNotification()
  → 主 agent 后续上下文收到 <task-notification>
```

重点：主 agent 不从原始 function call 等最终结果，而是之后通过 notification queue + output file/transcript 收到。

---

## 13. 异步 subagent 是独立 OS 进程吗？

**问：async subagent 是不是 fork 了一个系统进程？**

答：普通 local async subagent 不是独立 OS 进程。

它是在同一个 Node/Bun JavaScript runtime 里的 detached async task / async generator loop。

所以它跟主 agent 的通信很多时候是进程内共享内存结构，不是 socket、Redis、数据库或系统 IPC。

---

## 14. `enqueuePendingNotification` 的本质是什么？

**问：async subagent 完成后通知主 agent 的 queue 是什么？**

答：本质是同进程内的 module-level memory queue。

关键源码：

- `src/utils/messageQueueManager.ts`

里面有类似：

```ts
const commandQueue: QueuedCommand[] = []
```

`enqueuePendingNotification()` 做的事情可以理解为：

```text
commandQueue.push(notification)
  → notifySubscribers()
  → queueChanged.emit()
```

所以普通 async agent completion notification 不是外部消息队列，而是当前 runtime 内存队列。

---

## 15. async subagent 怎么继续收消息？

**问：主 agent 可以继续给 async subagent 发消息吗？**

答：可以，通过 `SendMessage(to: agentId)`。

如果子 agent 还在运行：

```text
SendMessage
  → queuePendingMessage()
  → 写入该 task 的 pendingMessages
  → 子 agent 下一轮 tool round 调 getAgentPendingMessageAttachments()
  → drain 成 attachment 注入子 agent 上下文
```

如果子 agent 已停止，runtime 会尝试：

```text
resumeAgentBackground()
```

从 transcript 恢复该 agent。

关键文件：

- `src/tools/SendMessageTool/SendMessageTool.ts`
- `src/utils/attachments.ts`
- `src/tools/AgentTool/resumeAgent.ts`

---

## 16. subagent 之间能互相聊天吗？

**问：两个普通 async subagent 能不能直接来回调用/通信？**

答：默认不是真正 peer-to-peer。

普通 async subagent 通常是由主 agent/coordinator 通过 `SendMessage(agentId)` 续聊。普通子 agent 默认不一定拥有 `SendMessage` 或 `Agent` 等工具，不能天然互相派生/互发。

真正 peer-to-peer 更接近 `teammate/swarm` 模式。

---

## 17. teammate/swarm 通信怎么实现？

**问：teammate/swarm 里 agent 之间如何通信？**

答：通过 `SendMessage` + mailbox JSON 文件。

关键路径：

```text
~/.claude/teams/{team_name}/inboxes/{agent_name}.json
```

发送端：

```text
SendMessageTool
  → 写入目标 teammate 的 inbox json
  → lockfile 防并发写冲突
```

接收端：

```text
useInboxPoller / inProcessRunner
  → 定期读取 inbox
  → 找 unread messages
  → 标记 read
  → 包装成 teammate-message 注入上下文
```

注入形式类似：

```xml
<teammate-message teammate_id="..." summary="...">
  ...message content...
</teammate-message>
```

重点：普通模型输出不会自动广播给别人。必须显式调用 `SendMessage`。

关键源码：

- `src/tools/SendMessageTool/SendMessageTool.ts`
- `src/utils/teammateMailbox.ts`
- `src/hooks/useInboxPoller.ts`
- `src/utils/swarm/inProcessRunner.ts`

---

## 18. teammate 会不会 ping-pong 死循环？

**问：两个 teammate 如果一直互相 `SendMessage`，有没有循环检测？**

答：源码里没有看到专门的“ping-pong 循环检测器”。

主要依赖这些约束降低风险：

- 必须显式 `SendMessage`，普通输出不会自动转发。
- mailbox 是 read-once 语义，读过会标记 read。
- agent 有 abort/shutdown/max turns/context limit 等自然限制。
- 某些模式禁止 nested teammate 或 fork 再 fork。
- 最后仍依赖模型自控和任务设计。

所以它不是消息总线式自动转发，而是“显式发信 + 收信触发上下文注入”。

---

## 19. claude-code 的上下文压缩分几层？

**问：agent 是如何压缩上下文的？**

答：它不是单一压缩函数，而是多层降 token 机制。

主路径在 `src/query.ts`：

```text
每轮 query 开始
  → getMessagesAfterCompactBoundary(messages)
  → applyToolResultBudget(...)
  → HISTORY_SNIP，可选
  → microcompactMessages(...)
  → context collapse，可选
  → autoCompactIfNeeded(...)
  → callModel(...)
```

可以分成三档：

1. **轻量裁剪**：工具结果预算、history snip、microcompact。
2. **完整压缩**：autoCompact 触发 `compactConversation()`，调用模型生成 summary。
3. **恢复压缩**：主调用已经 prompt-too-long 后，reactive compact 补救并重试。

关键源码：

- `src/query.ts`
- `src/services/compact/autoCompact.ts`
- `src/services/compact/compact.ts`
- `src/services/compact/microCompact.ts`
- `src/services/compact/sessionMemoryCompact.ts`
- `src/utils/messages.ts`

---

## 20. compact boundary 是什么？

**问：压缩后历史消息真的被删了吗？**

答：不一定。本地 transcript 可以继续保留完整历史；模型上下文通过 `compact_boundary` 做投影。

`getMessagesAfterCompactBoundary(messages)` 会找到最后一个 `compact_boundary`，只把它之后的消息送给模型。

`compact_boundary` 是 system message：

```ts
{
  type: 'system',
  subtype: 'compact_boundary',
  content: 'Conversation compacted',
  compactMetadata: {
    trigger,
    preTokens,
    userContext,
    messagesSummarized,
  }
}
```

所以可以理解成：

```text
完整 transcript：还在本地
模型可见上下文：最后一次 compact boundary 之后
```

---

## 21. microcompact 做什么？

**问：microcompact 是总结对话吗？**

答：不是。microcompact 主要清理旧工具结果。

可清理工具包括：

- FileRead
- Shell/Bash/PowerShell
- Grep
- Glob
- WebSearch
- WebFetch
- FileEdit
- FileWrite

旧工具结果会被替换成：

```text
[Old tool result content cleared]
```

它的目标是删掉 token-heavy 的旧工具输出，而不是保留完整语义。

---

## 22. cached microcompact 和 time-based microcompact 有什么区别？

**问：microcompact 有哪些路径？**

答：主要两种。

### time-based microcompact

如果距离上次 assistant message 时间太久，prompt cache 大概率冷了，就直接改本地 messages，把旧 tool result 内容清掉，只保留最近 N 个。

### cached microcompact

如果 `CACHED_MICROCOMPACT` feature 开启，并且模型支持 cache editing，它不改本地 message 内容，而是在 API 层通过 `cache_edits` 删除服务端缓存里的部分 tool result。

区别：

```text
time-based：改本地上下文内容
cached：本地 transcript 不变，API 层编辑缓存
```

---

## 23. autoCompact 什么时候触发？

**问：自动压缩阈值怎么计算？**

答：核心在 `src/services/compact/autoCompact.ts`。

源码常量：

```ts
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
AUTOCOMPACT_BUFFER_TOKENS = 13_000
```

计算方式：

```text
effectiveContextWindow = model context window - reserved summary output
autoCompactThreshold = effectiveContextWindow - 13_000
```

也就是说，它不会等真正爆上下文才压，而是预留：

- 最多 20k token 给 summary 输出。
- 额外 13k token buffer。

相关环境变量：

- `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`
- `DISABLE_COMPACT`
- `DISABLE_AUTO_COMPACT`

---

## 24. 完整压缩 `compactConversation()` 怎么做？

**问：真正生成 summary 的过程是什么？**

答：核心函数是：

```ts
compactConversation(...)
```

文件：

```text
src/services/compact/compact.ts
```

流程：

```text
1. 计算压缩前 token
2. 执行 PreCompact hooks
3. 合并 custom instructions
4. 构造 compact prompt
5. 调 streamCompactSummary()
6. 模型生成 <analysis> + <summary>
7. 清理 readFileState / memory state
8. 生成 post-compact attachments
9. 执行 SessionStart hooks / PostCompact hooks
10. 返回 CompactionResult
```

compact prompt 要求模型输出结构化总结：

- Primary Request and Intent
- Key Technical Concepts
- Files and Code Sections
- Errors and fixes
- Problem Solving
- All user messages
- Pending Tasks
- Current Work
- Optional Next Step

---

## 25. compact agent 可以调用工具吗？

**问：压缩时模型能不能 Read/Bash/Grep？**

答：不能。

源码有：

```ts
createCompactCanUseTool()
```

它会 deny 所有工具调用：

```text
Tool use is not allowed during compaction
```

compact prompt 也强制提示：

```text
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.
```

原因：压缩 agent 的任务只是基于已有上下文写 summary，不能再引入新工具调用和新状态。

---

## 26. compact 本身也是一次模型调用吗？

**问：压缩 summary 是规则生成还是模型生成？**

答：是模型生成。

`streamCompactSummary()` 优先通过 `runForkedAgent(...)` 开一个 forked compact agent：

```ts
runForkedAgent({
  promptMessages: [summaryRequest],
  cacheSafeParams,
  canUseTool: createCompactCanUseTool(),
  querySource: 'compact',
  forkLabel: 'compact',
  maxTurns: 1,
  skipCacheWrite: true,
})
```

重点：

- 它复用主线程 prompt cache，减少成本。
- `maxTurns: 1`，只允许一轮。
- 工具全部 deny。
- 如果 fork cache-sharing 失败，会 fallback 到普通 streaming path。

---

## 27. 如果 compact 请求自己也太长怎么办？

**问：压缩请求本身 prompt-too-long 会怎样？**

答：会截掉最老的 API round 后重试。

相关函数：

```ts
truncateHeadForPTLRetry(...)
```

也就是说，如果“用来总结的上下文”本身已经大到 API 不接受，runtime 会丢掉更旧的一些消息，尽量生成一个可用 summary，而不是直接卡死。

---

## 28. 压缩后的上下文是什么样？

**问：压缩后模型只看到 summary 吗？**

答：不是。压缩后上下文由 `buildPostCompactMessages(result)` 构造，顺序是：

```ts
[
  boundaryMarker,
  ...summaryMessages,
  ...(messagesToKeep ?? []),
  ...attachments,
  ...hookResults,
]
```

也就是：

```text
compact_boundary
+ compact summary
+ 可选保留的 recent messages
+ post-compact attachments
+ hook results
```

---

## 29. 压缩后会补回哪些关键上下文？

**问：压缩不会把刚读过的文件、plan、skill 都忘了吗？**

答：runtime 会主动重新注入一些关键上下文。

包括：

- 最近读过的最多 5 个文件。
- 每个文件默认最多 5000 token。
- 文件恢复总预算 50000 token。
- async agent 状态，避免主 agent 忘记后台任务。
- plan file / plan mode。
- invoked skills，每个 skill 最多 5000 token，总预算 25000 token。
- tool / agent / MCP instructions delta。
- SessionStart hooks 的结果。

所以完整压缩不是“只剩 summary”，而是“summary + 工作现场恢复包”。

---

## 30. session memory compaction 是什么？

**问：为什么 autoCompact 优先尝试 session memory compaction？**

答：session memory compaction 是实验性路径。它不重新总结整段历史，而是使用已经抽取好的 session memory 作为 summary。

默认保留配置：

```ts
minTokens: 10_000
minTextBlockMessages: 5
maxTokens: 40_000
```

它会：

```text
读取 session memory
  → 找到 lastSummarizedMessageId
  → 保留这之后的一段 recent messages
  → 用 session memory 作为 compact summary
  → 返回 CompactionResult
```

它还会通过 `adjustIndexToPreserveAPIInvariants(...)` 避免把 `tool_use` / `tool_result` 配对切断。

---

## 31. 为什么压缩时不能切断 tool_use/tool_result？

**问：保留 recent messages 时为什么要调整边界？**

答：Anthropic Messages API 要求工具调用配对完整。

不能出现：

```text
user tool_result 存在
但前面的 assistant tool_use 被压掉了
```

也不能出现：

```text
assistant tool_use 存在
但后续 user tool_result 不存在
```

否则 API 会报错。`sessionMemoryCompact.ts` 里的 `adjustIndexToPreserveAPIInvariants(...)` 就是为了避免这种 orphan tool_use/tool_result。

---

## 32. 手动 `/compact` 和自动 compact 有什么区别？

**问：用户手动 `/compact` 和 autoCompact 是同一套吗？**

答：底层大多复用，但触发和行为不同。

手动入口：

```text
src/commands/compact/compact.ts
```

手动 `/compact`：

- 用户显式触发。
- 支持 custom instructions，例如 `/compact 重点保留测试结果`。
- 出错会显示给用户。
- 无 custom instructions 时优先 session memory compact。
- 否则 microcompact 后走 `compactConversation()`。

自动 compact：

- 在每轮 `query.ts` 里根据 token 阈值触发。
- 不支持用户当场写 custom instructions。
- 失败通常静默，下轮继续尝试。
- 有 consecutive failure circuit breaker，避免无限重试浪费 API。

---

## 33. reactive compact 是什么？

**问：如果已经 prompt-too-long，autoCompact 还来得及吗？**

答：这时走 reactive compact。

`query.ts` 里会先 withhold recoverable prompt-too-long/media-too-large errors，不立刻吐给用户，然后尝试：

```text
context collapse drain
  → reactiveCompact.tryReactiveCompact(...)
  → 成功后 buildPostCompactMessages(...)
  → 用压缩后的上下文重试当前 query
```

如果 recovery 失败，才把 prompt-too-long 错误显示出来。

所以：

```text
autoCompact = 提前压
reactive compact = 爆了以后补救
```

---

## 34. function calling 是不是已经“过时”了？

**问：现在大家还讲 function calling 吗？**

答：function calling 没消失，而是被吸收到更大的 agent runtime 体系里了。

早期大家直接说 function calling，因为重点是“模型能输出结构化函数调用”。

现在更常见的说法是：

- Tool Calling
- Structured Outputs
- MCP
- Agent Runtime
- Computer Use
- Workflow / Graph Runtime

但底层机制仍然类似：

```text
模型输出结构化调用请求
  → runtime 执行外部能力
  → 结果作为上下文返回模型
```

所以 function calling 更像底层 ABI，而不是完整 agent 架构。

完整 agent 还需要：

- memory
- runtime loop
- sandbox
- permissions
- audit logs
- tool registry
- MCP/resource discovery
- async task management
- context compaction

---

## 35. Agent memory 应该怎么设计？

**问：agent memory 更适合数据库优先，还是文件优先？**

答：这次讨论形成的偏好是 **Markdown-first + JSONL source of truth，SQLite/vector/graph 作为可重建索引**。

推荐设计：

```text
memory/
  daily/YYYY-MM-DD.md       # 日志/原始事件
  episodes/YYYY-MM/*.md     # 重要会话/事件沉淀
  knowledge/**/*.md         # 可复用知识
  identity/*.md             # 信念、偏好、身份
  relationships/*.md        # 人和 agent 关系
  goals/*.md                # active/completed/blocked
  raw/*.jsonl               # 原始事件流，可选
  index.sqlite              # 可重建索引
  vector/                   # 可重建向量索引
  graph/                    # 可重建关系图
```

理由：

- Markdown 易读、易审计、易 Git diff。
- JSONL 适合保留原始事件。
- SQLite/vector/graph 适合检索，但不应成为唯一 source of truth。
- 索引坏了可以重建，文本记忆仍然在。

一句话：**长期记忆的真相放在人能读的文本里，机器索引用来加速，不负责承载唯一事实。**

---

## 36. OpenClaw 和 Hermes Agent 的区别怎么理解？

**问：OpenClaw 与 Hermes Agent 有什么差异？**

答：这次讨论中的理解是：

- OpenClaw 更像个人 AI runtime / personal agent OS。
- 它强调多 channel、多工具、设备节点、浏览器、消息、cron、subagent、skills、memory 等运行时能力。
- Hermes Agent 的方向更偏具体 agent framework/产品化路线，和 OpenClaw 的定位不完全一样。

如果类比：

```text
OpenClaw：更像个人 agent 的操作系统 / runtime substrate
Hermes：更像某类 agent 框架或应用层产品
```

---

