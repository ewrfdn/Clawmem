# Claude Code 上下文 Summary 与 Session 恢复机制

> **资料性质**：基于 Claude Code 源码的机制分析
>
> **整理日期**：2026-07-27
>
> **源码目录**：`/home/azureuser/.openclaw/workspace/claude-code`
>
> **相关源码**：`src/services/compact/compact.ts`、`src/services/compact/prompt.ts`、`src/query.ts`、`src/utils/messages.ts`、`src/utils/sessionStorage.ts`、`src/utils/sessionStoragePortable.ts`、`src/utils/sessionRestore.ts`、`src/screens/REPL.tsx`、`src/hooks/useLogMessages.ts`

## 结论先行

Claude Code 的上下文 compact 可以概括为：

```text
上下文接近上限
    ↓
调用模型生成 compact summary
    ↓
创建 compact_boundary + summary user message
    ↓
把新上下文消息追加到原 session JSONL
    ↓
下一次 query 从最近的 boundary 开始切片
    ↓
将 summary + 保留消息 + 新消息发送给模型
```

最重要的结论：

1. **summary 会持久化保存**，它是 session transcript 中的一条特殊 `user` 消息，不是单独的 summary 文件。
2. **普通 compact 通常不会生成新的 JSONL 文件**，而是在原来的 `<session-id>.jsonl` 后面追加 boundary、summary 和后续消息。
3. **summary 不是 `system message`**。它的内部类型是 `user`，并带有 `isCompactSummary: true`。
4. `compact_boundary` 是内部 system marker，用于标记新的上下文段；它通常不会作为普通文本发送给模型。
5. summary 在普通 UI 中通常不可见，是因为 `isVisibleInTranscriptOnly: true` 被显示层过滤；这不代表它没有保存，也不代表它不会发送给模型。
6. `/resume` 不会重新生成 summary。它从 transcript 读取已经持久化的 summary，然后在下一次 query 时使用它。
7. compact 前的原始消息通常仍然存在于磁盘 transcript 中，但默认不再进入 active model context；需要精确旧内容时，可以按 summary 中的 transcript 路径读取原始日志。

---

## 1. 一个完整的示例

假设 compact 前的对话是：

```text
[system, user1, ai1, user2, ai2, user3, ai3, user4, ai4]
```

这次 compact 总结了：

```text
[user1, ai1, user2, ai2]
```

并保留了：

```text
[user3, ai3, user4, ai4]
```

compact 后，Claude Code 内部的逻辑消息可以近似表示为：

```text
[
  system,
  compact_boundary,
  compact_summary,
  user3,
  ai3,
  user4,
  ai4
]
```

随后用户又输入 `user5`，模型回答 `ai5`，当前消息数组可能变成：

```text
[
  system,
  compact_boundary,
  compact_summary,
  user3,
  ai3,
  user4,
  ai4,
  user5,
  ai5
]
```

但是，这里的 `compact_summary` 不是 system role，而是特殊的 user message：

```ts
{
  type: 'user',
  isCompactSummary: true,
  isVisibleInTranscriptOnly: true,
  message: {
    role: 'user',
    content: 'This session is being continued from a previous conversation that ran out of context.\n\nSummary: ...'
  }
}
```

---

## 2. Summary 在哪里生成？

生成逻辑位于：

```text
src/services/compact/compact.ts
src/services/compact/prompt.ts
```

compact 过程会先调用 summary prompt，让模型总结被压缩的对话。summary 返回后，`formatCompactSummary()` 会：

1. 去掉 `<analysis>...</analysis>` 草稿区；
2. 将 `<summary>...</summary>` 转换成可读的 `Summary:` 章节；
3. 清理多余空行。

随后使用 `getCompactUserSummaryMessage()` 构造上下文说明：

```text
This session is being continued from a previous conversation that ran out of context.

Summary:
<模型生成的摘要>

If you need specific details from before compaction ... read the full transcript at: <transcriptPath>
```

然后创建 summary 消息：

```ts
const summaryMessages: UserMessage[] = [
  createUserMessage({
    content: getCompactUserSummaryMessage(
      summary,
      suppressFollowUpQuestions,
      transcriptPath,
    ),
    isCompactSummary: true,
    isVisibleInTranscriptOnly: true,
  }),
]
```

因此它从一开始就被定义为 `UserMessage`，不是 `SystemMessage`。

---

## 3. Summary 如何写入本地 JSONL？

Claude Code 的 session transcript 是 JSONL，而不是一个 JSON 数组：

```text
一行 = 一个 JSON entry
整个 session = 多行 JSON 拼接
```

通常文件类似：

```text
~/.claude/projects/<project-hash>/<session-id>.jsonl
```

下面是一个简化的示意。真实字段会更多，且不同版本可能有差异。

### 3.1 compact 前的消息

```json
{"type":"system","subtype":"init","session_id":"sess-123","uuid":"sys-001","timestamp":"2026-07-27T00:00:01.000Z","cwd":"/project"}
{"type":"user","session_id":"sess-123","uuid":"u-001","parentUuid":"sys-001","timestamp":"2026-07-27T00:00:10.000Z","message":{"role":"user","content":"user1"}}
{"type":"assistant","session_id":"sess-123","uuid":"a-001","parentUuid":"u-001","timestamp":"2026-07-27T00:00:12.000Z","message":{"role":"assistant","content":[{"type":"text","text":"ai1"}]}}
{"type":"user","session_id":"sess-123","uuid":"u-002","parentUuid":"a-001","timestamp":"2026-07-27T00:01:00.000Z","message":{"role":"user","content":"user2"}}
{"type":"assistant","session_id":"sess-123","uuid":"a-002","parentUuid":"u-002","timestamp":"2026-07-27T00:01:02.000Z","message":{"role":"assistant","content":[{"type":"text","text":"ai2"}]}}
```

### 3.2 compact boundary

compact 会创建一个新的 system boundary：

```json
{"type":"system","subtype":"compact_boundary","session_id":"sess-123","uuid":"cb-001","timestamp":"2026-07-27T00:02:00.000Z","content":"Conversation compacted","compactMetadata":{"trigger":"auto","preTokens":180000,"messagesSummarized":4},"logicalParentUuid":"a-002"}
```

`logicalParentUuid` 表示 compact 前逻辑上的最后一条消息。它是消息关系信息，不是文件指针，也不是对另一个 JSONL 文件的引用。

需要区分：

- `logicalParentUuid`：记录 compact 前的逻辑位置；
- `parentUuid`：用于消息树/链构造的父消息 UUID；
- session 文件路径：仍然是当前 session 自己的 JSONL 路径。

compact boundary 还可能携带 preserved-segment 等 metadata，用于在保留部分消息时修复消息链。不能把所有版本和所有 compact 路径都简化成一个固定的 `parentUuid` 关系。

### 3.3 summary 消息

接着追加 summary user message：

```json
{"type":"user","session_id":"sess-123","uuid":"sum-001","parentUuid":"cb-001","timestamp":"2026-07-27T00:02:01.000Z","isCompactSummary":true,"isVisibleInTranscriptOnly":true,"message":{"role":"user","content":"This session is being continued from a previous conversation that ran out of context.\n\nSummary:\n用户要求完成某项任务。此前已经处理了 user1、ai1、user2 和 ai2，完成了初步分析，当前需要继续处理后续步骤。\n\nIf you need specific details from before compaction, read the full transcript at: /home/.../sess-123.jsonl"}}
```

这里最关键的是：

```json
"type":"user"
"isCompactSummary":true
"isVisibleInTranscriptOnly":true
```

内容内部也仍然是：

```json
"role":"user"
```

### 3.4 后续消息

```json
{"type":"user","session_id":"sess-123","uuid":"u-003","parentUuid":"sum-001","timestamp":"2026-07-27T00:03:00.000Z","message":{"role":"user","content":"user3"}}
{"type":"assistant","session_id":"sess-123","uuid":"a-003","parentUuid":"u-003","timestamp":"2026-07-27T00:03:02.000Z","message":{"role":"assistant","content":[{"type":"text","text":"ai3"}]}}
{"type":"user","session_id":"sess-123","uuid":"u-004","parentUuid":"a-003","timestamp":"2026-07-27T00:04:00.000Z","message":{"role":"user","content":"user4"}}
{"type":"assistant","session_id":"sess-123","uuid":"a-004","parentUuid":"u-004","timestamp":"2026-07-27T00:04:02.000Z","message":{"role":"assistant","content":[{"type":"text","text":"ai4"}]}}
```

这只是帮助理解的代表性示例。实际 transcript 中还可能包含 `requestId`、模型信息、tool_use、tool_result、权限模式、agent 信息和其他内部字段。

---

## 4. 为什么不是新建一个 JSONL？

普通主会话 compact 的存储方式是：

```text
同一个 session-id.jsonl
    ├── 旧消息
    ├── compact_boundary
    ├── compact_summary
    ├── messagesToKeep
    └── compact 后的新消息
```

通常不会变成：

```text
session-id.jsonl
session-id-compact-001.jsonl
```

也不会是：

```text
新 JSONL → 指向旧 JSONL
```

`parentUuid` 和 `logicalParentUuid` 描述的是同一个 transcript 内的消息图关系，不是文件之间的关系。

一个例外是 sidechain 或子 Agent 可能使用独立的 agent transcript。这属于 Agent/sidechain 的日志隔离，不是普通 compact 为主会话生成了一个新 JSONL。

---

## 5. 原始 compact 前消息还存在吗？

通常还存在于磁盘 transcript 中：

```text
system
user1
ai1
user2
ai2
compact_boundary
summary
user3
ai3
user4
ai4
```

但 compact 后，它们不再默认属于 active model context。

需要区分三个概念：

| 层次 | compact 前原始消息的状态 |
|---|---|
| 磁盘 transcript | 通常仍然存在 |
| 恢复后的 active conversation chain | 通常从最近 compact boundary 开始 |
| 下一次发送给模型的消息 | 默认不包含 boundary 之前的原始消息 |

大型 session 加载时，`readTranscriptForLoad()` 可能识别最近的 boundary，并跳过 boundary 前的大量旧内容，以减少内存占用。这是加载优化，不代表旧内容已经从磁盘删除。

summary 中附带 transcript 路径，就是为了在 summary 不足以恢复精确细节时，让模型主动读取旧日志。

---

## 6. `/resume` 时 summary 如何重新进入上下文？

`/resume` 不会重新生成 summary，也不会再次调用 summary API。

恢复流程可以表示为：

```text
/resume
    ↓
loadTranscriptFile()
    ↓
解析 JSONL entries
    ↓
按 parentUuid 构造消息树
    ↓
找到当前 leaf / 最新分支
    ↓
buildConversationChain()
    ↓
deserializeMessages()
    ↓
恢复到 REPL messages
    ↓
下一次 query 从最近 compact_boundary 切片
```

相关源码：

```text
src/utils/sessionStorage.ts:loadTranscriptFile()
src/utils/sessionStorage.ts:getLastSessionLog()
src/utils/sessionStorage.ts:buildConversationChain()
src/utils/sessionRestore.ts
src/screens/REPL.tsx
```

`loadTranscriptFile()` 会读取已经写入 JSONL 的 summary；`getLastSessionLog()` 会从最新的非 sidechain leaf 沿消息关系构造当前 transcript；交互式 `/resume` 随后执行：

```ts
const messages = deserializeMessages(log.messages)
```

然后额外恢复：

- TodoWrite 状态；
- file history；
- commit attribution；
- agent setting；
- plan；
- worktree；
- SessionStart hooks；
- 其他会话状态。

这里没有新的 summary 生成过程。只有当恢复后的新上下文再次接近上限时，才会触发下一次 compact，并生成新的 summary。

---

## 7. 真正发送给模型时的消息结构

下一轮 query 会先执行：

```ts
let messagesForQuery = [
  ...getMessagesAfterCompactBoundary(messages),
]
```

对于示例，内部切片结果大致是：

```text
[
  compact_boundary,
  compact_summary,
  user3,
  ai3,
  user4,
  ai4
]
```

随后 API normalization 会把内部 boundary 从普通对话消息中移除。真正发送给模型的结构大致是：

```json
{
  "system": "Claude Code system prompt ...",
  "messages": [
    {
      "role": "user",
      "content": "This session is being continued from a previous conversation that ran out of context.\n\nSummary:\n..."
    },
    {
      "role": "user",
      "content": "user3"
    },
    {
      "role": "assistant",
      "content": "ai3"
    },
    {
      "role": "user",
      "content": "user4"
    },
    {
      "role": "assistant",
      "content": "ai4"
    }
  ]
}
```

因此不能写成：

```text
[system, system-summary, user3, ai3, user4, ai4]
```

更准确的是：

```text
API system 参数：Claude Code 的系统提示词

API messages：
[user(summary), user3, ai3, user4, ai4]
```

`compact_boundary` 是 Claude Code 的内部 system marker；summary 才是代替旧历史发送给模型的实际内容。

---

## 8. Summary 为什么不显示在普通 UI？

是的，summary 不出现在普通 UI 中，主要是因为显示层识别并过滤了：

```ts
isVisibleInTranscriptOnly: true
```

它不是在写入 JSONL 时被删除，也不是因为模型上下文中不存在。

普通显示逻辑可以简化为：

```ts
if (message.isMeta) {
  return false
}

if (message.isVisibleInTranscriptOnly && !isTranscriptMode) {
  return false
}
```

`VirtualMessageList` 等组件也会对这些消息直接跳过渲染：

```ts
if (msg.isMeta || msg.isVisibleInTranscriptOnly) {
  return null
}
```

因此普通 UI 可能显示：

```text
user3
ai3
user4
ai4
```

而不显示：

```text
compact_summary
```

如果进入完整 transcript、调试或历史查看模式，`isVisibleInTranscriptOnly` 不再阻止它显示，summary 可能出现。

这个字段的准确含义是：

```text
只在 transcript 视图中可见
```

不是：

```text
只保存、不参与模型上下文
```

---

## 9. UI 过滤和模型过滤是两套逻辑

这是理解 Claude Code compact 的关键。

### UI 过滤

目标：

```text
不要让 summary 作为普通用户消息出现在聊天界面
```

主要依据：

```text
isMeta
isVisibleInTranscriptOnly
```

### 模型上下文选择

目标：

```text
让 summary 替代 compact 前的原始历史
```

主要依据：

```ts
getMessagesAfterCompactBoundary(messages)
```

它找到最近的 `compact_boundary`，并保留 boundary 之后的消息。之后 API normalization 移除内部 boundary，但不会因为 `isVisibleInTranscriptOnly` 就移除 compact summary。

所以三层行为是：

```text
磁盘：保存 summary

UI：普通模式隐藏 summary

模型：保留 summary，并以 user role 发送
```

---

## 10. `isCompactSummary` 和 `isVisibleInTranscriptOnly` 的区别

| 字段 | 作用 |
|---|---|
| `isCompactSummary` | 标记这是一条上下文 compact 摘要 |
| `isVisibleInTranscriptOnly` | 普通 UI 隐藏，完整 transcript 视图可显示 |
| `isMeta` | 标记内部/合成消息，通常不作为普通用户输入显示 |
| `compact_boundary` | 标记 active context 的新起点 |

summary 通常同时拥有：

```ts
isCompactSummary: true
isVisibleInTranscriptOnly: true
```

`isCompactSummary` 还会影响其他逻辑，例如：

- 不把它当作 session 的第一条真实用户 prompt；
- 在某些恢复/统计路径中识别它是自动生成内容；
- SDK/回放路径中将它标记为 synthetic；
- UI 消息选择和普通操作菜单中跳过它。

---

## 11. Summary 和 session list 的 summary metadata 不是一回事

源码中还存在一种独立的 transcript entry：

```text
entry.type === 'summary'
```

它可能用于 session 列表、搜索、标题或展示信息。

这和 compact 生成的：

```ts
isCompactSummary: true
```

不是同一个概念。

因此不能只检查 `LogOption.summary` 或 transcript 中的 summary metadata，就判断模型是否拥有 compact summary。模型真正使用的是一条已经进入消息链的特殊 user message。

---

## 12. 从 compact 到 resume 的完整链路

```mermaid
flowchart TD
    A[上下文接近上限] --> B[compact 生成摘要]
    B --> C[创建 compact_boundary]
    B --> D[创建 isCompactSummary=true 的 user message]
    C --> E[构造 post-compact messages]
    D --> E
    E --> F[useLogMessages]
    F --> G[recordTranscript]
    G --> H[追加到原 session JSONL]
    H --> I[/resume 读取 transcript]
    I --> J[按 parentUuid 恢复当前 leaf 链]
    J --> K[deserializeMessages]
    K --> L[恢复 REPL messages]
    L --> M[getMessagesAfterCompactBoundary]
    M --> N[移除内部 boundary]
    N --> O[summary + 保留消息 + 新消息]
    O --> P[发送给模型]
```

---

## 13. 常见误解

### 误解一：summary 是 system message

不准确。内部结构是：

```text
compact_boundary：system marker
compact_summary：特殊 user message
```

### 误解二：compact 会创建新的 session JSONL

普通主 session 通常不会。它会继续追加到原来的：

```text
<session-id>.jsonl
```

### 误解三：UI 看不到 summary，说明 summary 没保存

不对。UI 隐藏是 `isVisibleInTranscriptOnly` 的显示层行为。

### 误解四：resume 时会再次调用 summary API

不对。summary 在 compact 时生成并写入；resume 只读取已有结果。

### 误解五：compact 后旧消息一定被物理删除

不一定。通常 transcript 仍保留旧记录，只是 active context 从 boundary 后开始。大型文件加载器可能为了性能跳过旧内容。

### 误解六：parentUuid 是 JSONL 文件之间的引用

不对。它是同一个 transcript 内消息树的父子关系。文件之间一般没有这种“新文件指向旧文件”的 compact 关系。

---

## 14. 最终心智模型

可以把 compact 后的 session 想成同一个日志文件中的两个逻辑时代：

```text
同一个 session JSONL

旧上下文时代：
[system, user1, ai1, user2, ai2]

新上下文时代：
[compact_boundary, summary(user), user3, ai3, user4, ai4]
```

summary 是连接两个时代的“压缩后的上下文入口”：

```text
旧历史：保存在 transcript 中，但默认不发送
summary：代替旧历史发送给模型
后续消息：继续正常追加
```

最简公式：

```text
磁盘：old history + boundary + summary + new history

恢复：从 transcript 恢复当前消息链

模型：system prompt + summary(user) + post-compact messages

UI：隐藏 summary，显示普通对话消息
```

这就是 Claude Code 如何在不把整个旧对话重新塞回上下文的情况下，恢复长任务并继续执行。
