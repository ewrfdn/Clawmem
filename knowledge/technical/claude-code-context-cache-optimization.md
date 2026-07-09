# Claude Code 的 Context 与 Prompt Cache 优化机制

> 记录时间：2026-07-09  
> 来源：对 Claude Code 源码与会话讨论的整理  
> 目标读者：没有 Claude API / Transformer KV cache 背景的人，也能顺着“为什么要做缓存、压缩、cache edit”的思路理解。

## 0. 这篇文档想回答什么

在使用 Claude Code 这类长上下文 coding agent 时，会遇到几个现象：

1. 对话越长，输入 token 越多，API 变慢、变贵，也更容易撞上下文窗口上限。
2. Claude Code 会动态组装 system prompt，不是一个固定字符串。
3. Claude API 有 `cache_control`，但它不是“随便缓存任意块”，本质仍然是 prefix cache。
4. 发生 compact / memory 压缩后，缓存命中会明显下降。
5. Claude Code 有一个更精细的机制：Cached Microcompact / cache editing，可以局部删除旧工具输出的 KV cache，而不是重写整段历史。

这篇文档顺着 Sakana 的思路来解释：

> prompt cache 可以理解成：输入 prefix 对应一段已经 prefill 好的 Transformer KV cache。cache edit 后，cache 的 lineage 不变，但指定 tool_result 对应的 KV pages 被删除，模型后续实际能 attend 的历史 token 变少。

---

## 1. 先理解：模型为什么需要缓存

### 1.1 普通 LLM 请求发生了什么

假设我们向 Claude 发送：

```text
system: 你是一个 coding assistant
messages:
  user: 请分析这个项目
  assistant: 好的，我先读文件
  user/tool_result: 这里是 20000 tokens 的文件内容
  user: 接下来请修改 bug
```

模型生成回答时，大概分两步：

1. **Prefill 阶段**：把输入 prompt 的所有 token 跑一遍 Transformer。
2. **Decode 阶段**：一个 token 一个 token 地生成回答。

在 Transformer 里，每一层 attention 都会为历史 token 计算 Key / Value states。后续生成新 token 时，可以直接 attend 这些 K/V states，而不必每次重新计算完整历史。

所以可以粗略理解为：

```text
输入 tokens
  ↓ prefill
每层 Transformer 的 KV cache
  ↓ decode 时复用
生成新 tokens
```

### 1.2 Prompt cache 缓存的是什么

Prompt cache 缓存的不是“最终回答”，也不是一个单独的“语义向量”。

更准确地说，它缓存的是：

```text
某段稳定 prompt prefix 对应的 Transformer KV cache pages
```

可以简化理解成：

```text
cache_key   = hash(system + tools + messages 的稳定 prefix)
cache_value = 这段 prefix prefill 后产生的每层 K/V states
```

注意：`cache_value` 不是 decode 后的最终向量，而是每个历史 token 在每层 attention 里的 Key / Value 激活。

### 1.3 为什么 prefix 稳定非常重要

Prompt cache 是 prefix-based 的。

也就是说，如果你第一次请求是：

```text
A B C D E
```

第二次请求是：

```text
A B C D E F
```

那么 `A B C D E` 这段 prefix 可以命中缓存。

但如果第二次变成：

```text
A B X D E F
```

从 `X` 开始，prefix 就断了。即使 `D E` 内容一样，也不能作为同一段连续 prefix 复用。

这就是 Claude Code 所有 context cache 优化的底层约束。

---

## 2. Claude Code 的 system prompt 为什么是动态组装的

Claude Code 不是把 system prompt 写成一个固定大字符串，而是在运行时动态组装。

相关源码路径包括：

- `src/constants/prompts.ts`
- `src/utils/systemPrompt.ts`
- `src/constants/systemPromptSections.ts`
- `src/services/api/claude.ts`
- `src/utils/api.ts`
- `src/context.ts`
- `src/query.ts`

核心原因：Claude Code 的运行上下文是动态变化的。

### 2.1 动态原因

常见动态因素包括：

1. 当前可用工具不同：有无 MCP、是否启用 deferred tools、是否启用 tool search。
2. 当前环境不同：工作目录、git 状态、系统信息、沙箱模式。
3. 模式不同：plan mode、auto mode、non-interactive session、SDK 等。
4. 用户自定义不同：`CLAUDE.md`、`--system-prompt`、`--append-system-prompt`。
5. Agent / subagent 不同：不同 agent 有不同 coordinator / tool / prompt。
6. 缓存优化需要：稳定内容尽量放前面，动态内容放后面。

### 2.2 动态组装与缓存的矛盾

动态组装有必要，但它会带来缓存问题。

如果 system prompt 每一轮都变化，那么：

```text
system_v1 + messages
system_v2 + messages
```

即使 messages 完全一样，因为 system 是整个请求 prefix 的最前面，后面的 messages cache 也会受影响。

所以 Claude Code 要尽量把 system prompt 分成：

```text
稳定前缀 + 动态尾部
```

稳定前缀可以 cache；动态尾部尽量短，减少 cache churn。

---

## 3. Claude API 的 `cache_control` 是什么

Anthropic API 支持在 content block 上加：

```json
{
  "type": "text",
  "text": "很长的稳定内容...",
  "cache_control": { "type": "ephemeral" }
}
```

这告诉 Claude：

> 请在这里建立一个 prompt cache breakpoint。

但它不是“任意块缓存”。它仍然是 prefix cache。

### 3.1 一个简单例子

第一次请求：

```json
{
  "system": [
    {
      "type": "text",
      "text": "稳定 system prompt ...",
      "cache_control": { "type": "ephemeral" }
    }
  ],
  "messages": [
    {
      "role": "user",
      "content": "请分析 A"
    }
  ]
}
```

第一次通常会有较高：

```text
cache_creation_input_tokens
```

第二次请求：

```json
{
  "system": [
    {
      "type": "text",
      "text": "稳定 system prompt ...",
      "cache_control": { "type": "ephemeral" }
    }
  ],
  "messages": [
    {
      "role": "user",
      "content": "请分析 B"
    }
  ]
}
```

如果 prefix 足够稳定，就会看到：

```text
cache_read_input_tokens
```

### 3.2 system 变化会不会影响 messages cache？

会。

虽然 Anthropic API 里 `system` 是顶层字段，`messages` 是另一个顶层字段，但缓存计算时可以理解成：

```text
完整 prefix = serialize(system) + serialize(tools) + serialize(messages)
```

所以如果：

```text
system A + messages X
```

变成：

```text
system B + messages X
```

那么 messages X 虽然字面没变，但它前面的 prefix 已经变了，messages 级别的 cache breakpoint 通常也不能命中。

### 3.3 多 block system 的细节

如果 system 是：

```json
"system": [
  {
    "type": "text",
    "text": "稳定 system block",
    "cache_control": { "type": "ephemeral" }
  },
  {
    "type": "text",
    "text": "动态 system block"
  }
]
```

那么动态 block 改变时：

- 稳定 system block 的 cache 仍可能命中。
- 但 dynamic block 后面的 messages prefix 可能 miss。

这也是 Claude Code 要把稳定内容放前、动态内容放后的原因。

---

## 4. Claude Code 的 cache preservation 策略

Claude Code 的基本策略是：

```text
稳定内容尽量靠前
动态内容尽量靠后
cache_control breakpoint 放在稳定 prefix 后
```

可以理解成：

```text
[static system sections]  ← 尽量缓存
[dynamic system sections] ← 尽量短
[tools]
[messages]
```

Claude Code 里还有类似 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` 的设计，将 system prompt 切成静态前缀和动态尾部。

结果是：

1. 多数不变的系统规则可以持续命中 cache。
2. 环境变化、MCP 变化、用户配置变化只影响较小尾部。
3. 长会话里大部分成本来自 messages 和 tool outputs，因此还需要进一步处理 messages。

---

## 5. 为什么 full compact 会让 messages cache 失效

Claude Code 对话变长后会 compact。

压缩后的 messages 排列由 `buildPostCompactMessages()` 决定：

```ts
// src/services/compact/compact.ts
export function buildPostCompactMessages(result: CompactionResult): Message[] {
  return [
    result.boundaryMarker,
    ...result.summaryMessages,
    ...(result.messagesToKeep ?? []),
    ...result.attachments,
    ...result.hookResults,
  ]
}
```

也就是压缩后大致变成：

```text
compact boundary
summary message: "This session is being continued..."
recent messages, if any
attachments
hook results
```

### 5.1 压缩前后对比

压缩前：

```text
user msg 1
assistant msg 1
user msg 2
assistant msg 2
...
user msg 100
assistant msg 100
```

压缩后：

```text
summary of msg 1-100
recent messages preserved, maybe
post-compact attachments
```

messages[0] 已经完全不同了。

所以：

```text
messages 级别 prefix cache 基本必然失效
```

Claude Code 源码里也知道这点，所以 compact 后会通知 cache break detection：这是预期的 cache drop，不是 bug。

### 5.2 传统 compact 和 Session Memory Compact

Claude Code 有不同 compact 路径：

| 机制 | 行为 | cache 影响 |
|---|---|---|
| 传统 compact | 把旧对话总结成 summary，替换原始 messages | messages cache 大幅失效 |
| Session Memory Compact | 使用 session memory + 保留最近若干消息 | 仍会重排 messages，cache 仍会失效 |

Session Memory Compact 会尽量保留近期消息，默认配置大致是：

```ts
minTokens: 10_000
minTextBlockMessages: 5
maxTokens: 40_000
```

也就是至少保留最近约 10K tokens、至少 5 条有文本的消息，最多保留 40K tokens。

这能减少信息损失，但仍然改变了 messages prefix。

---

## 6. Microcompact：比 full compact 更小的手术

Full compact 是大手术：把整段历史变 summary。

Microcompact 是小手术：只处理旧工具输出。

为什么工具输出值得特殊处理？因为 coding agent 的上下文经常被这些内容撑爆：

```text
Read 一个大文件：10000 tokens
Bash 跑测试日志：20000 tokens
Grep 全仓库结果：15000 tokens
WebFetch 页面：12000 tokens
```

这些 tool result 刚出现时很重要，但几轮后模型通常只需要：

- assistant 已经读过它
- assistant 已经总结出结论
- 必要时可以重新读文件或查看 transcript

不一定需要每轮都让模型 attend 全部原始输出。

---

## 7. 普通 Microcompact 的问题

普通 microcompact 会把旧工具输出替换成：

```text
[Old tool result content cleared]
```

也就是本地消息从：

```json
{
  "type": "tool_result",
  "tool_use_id": "T1",
  "content": "20000 tokens 的日志..."
}
```

变成：

```json
{
  "type": "tool_result",
  "tool_use_id": "T1",
  "content": "[Old tool result content cleared]"
}
```

这能减少上下文，但有两个问题：

1. 本地 transcript 也失去原始细节。
2. 历史 prompt 被改写，prefix cache 从这个位置开始失效。

所以 Claude Code 引入了更高级的 Cached Microcompact。

---

## 8. Cached Microcompact：不改本地消息，只编辑服务端 cache

Cached Microcompact 的核心注释在 `src/services/compact/microCompact.ts`：

```ts
/**
 * Cached microcompact path - uses cache editing API to remove tool results
 * without invalidating the cached prefix.
 *
 * Key differences from regular microcompact:
 * - Does NOT modify local message content (cache_reference and cache_edits are added at API layer)
 * - Uses count-based trigger/keep thresholds from GrowthBook config
 * - Takes precedence over regular microcompact (no disk persistence)
 * - Tracks tool results and queues cache edits for the API layer
 */
```

重点是：

```text
本地 messages 不变
API payload 临时加 cache_reference / cache_edits
服务端删除指定 KV cache
```

---

## 9. Cached Microcompact 的执行流程

### 9.1 找到可删除的 tool_result

Claude Code 先扫描 assistant 消息里的 `tool_use`，只收集可压缩工具的 id。

可压缩工具包括：

- Read
- Bash / shell
- Grep
- Glob
- WebSearch
- WebFetch
- Edit
- Write

伪代码：

```ts
for message in messages:
  if message is assistant:
    for block in message.content:
      if block.type == "tool_use" and block.name in COMPACTABLE_TOOLS:
        ids.push(block.id)
```

然后再扫描 user 消息里的 `tool_result`：

```ts
for message in messages:
  if message is user:
    for block in message.content:
      if block.type == "tool_result" and block.tool_use_id in compactableIds:
        registerToolResult(block.tool_use_id)
```

### 9.2 给 tool_result 打 cache_reference

发送 API 前，Claude Code 会给 cached prefix 里的 tool_result 增加：

```json
"cache_reference": "toolu_xxx"
```

源码在 `src/services/api/claude.ts` 的 `addCacheBreakpoints()`：

```ts
msg.content[j] = Object.assign({}, block, {
  cache_reference: block.tool_use_id,
})
```

原始 block：

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01ABC",
  "content": "很长的文件内容..."
}
```

API payload 中变成：

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01ABC",
  "cache_reference": "toolu_01ABC",
  "content": "很长的文件内容..."
}
```

意思是：

> 服务端，请把这块缓存内容命名为 `toolu_01ABC`，之后我可能要引用它。

### 9.3 后续发送 cache_edits 删除指定引用

当 Claude Code 决定旧 tool result 可以删除时，会创建：

```json
{
  "type": "cache_edits",
  "edits": [
    {
      "type": "delete",
      "cache_reference": "toolu_01ABC"
    }
  ]
}
```

源码里类型定义是：

```ts
type CachedMCEditsBlock = {
  type: 'cache_edits'
  edits: { type: 'delete'; cache_reference: string }[]
}
```

这个 block 会被插到 user message 内容里。

### 9.4 cache_edits 会被 pin 并重复发送

Claude Code 会把 `cache_edits` pin 在原位置，后续请求重复插入。

原因是：`cache_edits` 自己也成为 prompt cache lineage 的一部分。

第一次：

```text
A B C [cache_edits delete B] D
```

下一次必须还是：

```text
A B C [cache_edits delete B] D E
```

如果下一次不带 `cache_edits`：

```text
A B C D E
```

prefix 又不同，cache lineage 会断掉。

所以源码里有：

```ts
// Re-insert all previously-pinned cache_edits at their original positions
```

以及：

```ts
// Pin so this block is re-sent at the same position in future calls
pinCacheEdits(i, newCacheEdits)
```

---

## 10. cache edit 后，token 还算上下文吗？

这个问题要非常精确。

### 10.1 tools schema 仍然算

顶层 `tools` schema 仍然存在。

模型仍然需要知道：

```text
Read 怎么调用
Bash 怎么调用
Edit 参数是什么
```

这些不是 Cached Microcompact 的删除对象。

### 10.2 被删除的是旧 tool_result 的 KV

被 `cache_edits delete` 指定的是某个 `tool_result` 的 `cache_reference`。

这意味着：

```text
旧工具输出对应的 KV cache pages 被删除或从 active context 中排除
```

Claude Code 读取 API 返回的：

```text
cache_deleted_input_tokens
```

并把它当作本次节省的 token 数。

源码里：

```ts
const deletedTokens = Math.max(
  0,
  cumulativeDeleted - pendingCacheEdits.baselineCacheDeletedTokens,
)
```

然后创建 microcompact boundary：

```ts
createMicrocompactBoundaryMessage(
  pendingCacheEdits.trigger,
  0,
  deletedTokens,
  pendingCacheEdits.deletedToolIds,
  [],
)
```

这说明 Claude Code 认为这些 token 已经从有效缓存上下文里节省掉。

### 10.3 用 KV cache 的角度理解

原始 cached context：

```text
KV(system)
KV(tools schema)
KV(normal messages)
KV(tool_result T1, 30k tokens)
KV(tool_result T2, 20k tokens)
KV(recent messages)
```

cache edit 删除 T1 后：

```text
KV(system)
KV(tools schema)
KV(normal messages)
[KV(tool_result T1) deleted]
KV(tool_result T2)
KV(recent messages)
```

所以后续 decode 时，新 token 的 attention 不再 attend T1 的 K/V。

因此：

```text
模型实际能利用的 active historical tokens 变少
上下文压力降低
```

---

## 11. 为什么局部删除 KV cache 有价值

### 11.1 避免 full compact

Full compact 的代价很大：

1. 要额外调用模型生成 summary。
2. summary 可能漏掉细节。
3. messages 顺序被重排。
4. messages prefix cache 基本失效一次。

Cached Microcompact 只删除旧工具输出，可以延迟 full compact。

### 11.2 不破坏 prompt cache

直接改历史消息会造成：

```text
prefix bytes 变化 → cache miss
```

cache edit 则更像：

```text
保留历史 lineage
追加一个服务端 cache patch
```

这保留了 system/tools/普通对话的大部分缓存价值。

### 11.3 保留本地可追溯性

本地 transcript 仍保留完整 tool result。

这很重要：

- 之后可以 debug。
- resume 时可以看历史。
- 如果需要精确信息，可以重新读取 transcript 或文件。
- 不会因为 microcompact 永久丢掉原始输出。

### 11.4 长任务更稳定

Coding agent 经常有这种长流程：

```text
读文件 → 跑测试 → 看日志 → 改代码 → 再跑测试 → 再看日志 → 提交 PR
```

如果每次 Bash/Grep/Read 输出都永久占上下文，长任务很快爆。

Cached Microcompact 可以让旧工具输出逐步退出 active context，但保留最近输出和对话结论。

---

## 12. 一个完整例子

假设某次 Claude Code 会话：

```text
system prompt: 20k tokens
工具 schema: 15k tokens
普通对话: 20k tokens
Read result T1: 30k tokens
Bash result T2: 25k tokens
Grep result T3: 10k tokens
最近消息: 15k tokens
```

总计大约：

```text
135k tokens
```

其中旧工具输出 T1/T2 占了：

```text
55k tokens
```

### 12.1 不做处理

后续每轮上下文都很大：

```text
135k + 新消息
```

很快触发 full compact。

### 12.2 普通 microcompact

本地改成：

```text
T1 = [Old tool result content cleared]
T2 = [Old tool result content cleared]
```

上下文变小，但 prefix 被改写，cache miss，而且原始输出从当前消息视图丢失。

### 12.3 Cached Microcompact

先给 T1/T2 打引用：

```json
{
  "type": "tool_result",
  "tool_use_id": "T1",
  "cache_reference": "T1",
  "content": "30k tokens..."
}
```

后续插入：

```json
{
  "type": "cache_edits",
  "edits": [
    { "type": "delete", "cache_reference": "T1" },
    { "type": "delete", "cache_reference": "T2" }
  ]
}
```

服务端 active KV 变成：

```text
system prompt: 20k
工具 schema: 15k
普通对话: 20k
T1: deleted
T2: deleted
T3: 10k
最近消息: 15k
cache_edits metadata: 很小
```

有效 context 可能从 135k 降到约 80k。

本地 transcript 仍然完整，cache lineage 也尽量保持稳定。

---

## 13. 为什么 cache edit 需要“热缓存”

源码里有一段注释很关键：

```ts
// Time-based trigger runs first and short-circuits. If the gap since the
// last assistant message exceeds the threshold, the server cache has expired
// and the full prefix will be rewritten regardless — so content-clear old
// tool results now, before the request, to shrink what gets rewritten.
// Cached MC (cache-editing) is skipped when this fires: editing assumes a
// warm cache, and we just established it's cold.
```

意思是：

```text
cache editing 的前提是服务端已有可编辑的 cached KV
```

如果太久没请求，服务端 cache 已过期，那么没有热 KV 可以编辑。此时直接做普通清理更合理，因为下一次反正要重建 prefix cache。

---

## 14. 和 OpenAI / GPT-5 prefix cache 的对比

OpenAI/GPT-5 的 prompt caching 通常是自动 prefix caching：

- 没有 Anthropic 这种显式 `cache_control`。
- 一般依赖稳定 prefix 达到一定长度，例如 1024 tokens 以上。
- 用户无法显式给某个 block 标记 cache breakpoint。

Claude / Anthropic 的优势是：

1. 可以用 `cache_control` 明确指定 breakpoint。
2. 可以拆 system blocks。
3. 新 beta 下可以用 cache editing 删除指定 `cache_reference`。

但两者都有共同点：

```text
稳定 prefix 很重要
顺序变化会破坏缓存
```

---

## 15. 最终 mental model

可以把 Claude Code 的 context cache 优化理解为四层：

### 第一层：System prompt 稳定化

```text
静态规则放前面
动态环境放后面
cache_control 放在稳定 prefix 后
```

### 第二层：Messages prefix cache

```text
对话按顺序增长
只要历史 prefix 不变，后续请求可复用缓存
```

### 第三层：Microcompact

```text
旧工具输出太大 → 清理它们
```

普通清理会改历史，破坏 cache。

### 第四层：Cached Microcompact / cache editing

```text
不改本地历史
给 tool_result 标 cache_reference
用 cache_edits delete 局部删除服务端 KV
pin edits 保持 lineage
```

---

## 16. 一句话总结

Claude Code 的 context 缓存优化目标不是简单地“少发 tokens”，而是：

> 在长时间 coding 会话里，让稳定 prefix 尽可能复用，让动态变化尽量靠后，让巨大但过时的 tool_result 退出 active KV context，同时不重写本地历史、不破坏 prompt cache lineage，并尽量推迟 full compact 的发生。

更形象地说：

```text
full compact 是把旧书撕掉后写摘要；
ordinary microcompact 是把旧书某几页涂黑；
cached microcompact 是本地旧书不动，只告诉服务端阅读时跳过这些旧页。
```

这就是局部删除 KV cache 的意义。
