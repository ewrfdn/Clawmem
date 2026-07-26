# Claude Code 如何执行长任务与 Stop Hook 运行机制

> **资料性质**：基于 Claude Code 源码的机制分析
>
> **源码目录**：`/home/azureuser/.openclaw/workspace/claude-code`
>
> **整理日期**：2026-07-26
>
> **相关源码**：`src/query.ts`、`src/query/stopHooks.ts`、`src/query/tokenBudget.ts`、`src/utils/hooks.ts`、`src/utils/hooks/hooksConfigManager.ts`、`src/services/compact/`、`src/services/contextCollapse/`、`src/QueryEngine.ts`、`src/Task.ts`、`src/tasks/`、`src/skills/bundled/loop.ts`

## 结论先行

Claude Code 不是一个保证永不停止的无限执行器。它采用的是：

```text
默认继续执行
  + tool_use 驱动的 Agent Loop
  + Stop Hook 扩展点
  + token budget continuation
  + 自动压缩与上下文恢复
  + 明确的预算、轮数、中断和错误终止条件
```

最重要的区别是：

> **Stop Hook 默认不是一个内置的“检查任务是否完成”的通用审查器。**
> 如果用户、插件或 Agent 没有配置 Stop Hook，Claude Code 不会自动运行测试、检查 TODO 或验证业务目标。默认情况下，模型是否产生新的 `tool_use`、预算和执行状态才是主要控制因素。

---

## 1. 主 Agent Loop：长任务如何一轮一轮继续

主循环位于：

```text
src/query.ts
```

简化流程如下：

```text
准备上下文
    ↓
必要时执行 microcompact / context collapse / auto compact
    ↓
请求模型
    ↓
流式收集 assistant 内容和 tool_use
    ↓
执行工具
    ↓
检查 Stop Hook
    ↓
检查 token budget 和其他终止条件
    ↓
继续下一轮，或者返回终态
```

Claude Code 不完全依赖 API 返回的 `stop_reason`。源码中记录了类似这样的设计：

```ts
// stop_reason === 'tool_use' is unreliable -- it's not always set correctly.
// Set during streaming whenever a tool_use block arrives — the sole
// loop-exit signal.
```

只要流式响应中收到了 `tool_use` block，就把它视为需要后续执行：

```ts
if (msgToolUseBlocks.length > 0) {
  toolUseBlocks.push(...msgToolUseBlocks)
  needsFollowUp = true
}
```

执行工具后，状态会进入下一轮：

```ts
const nextTurnCount = turnCount + 1

state = {
  messages: [
    ...messagesForQuery,
    ...assistantMessages,
    ...toolResults,
  ],
  turnCount: nextTurnCount,
  transition: { reason: 'next_turn' },
}
```

因此最基本的继续条件是：

```text
模型产生 tool_use
    ↓
Claude Code 执行工具
    ↓
把工具结果加入消息
    ↓
再次请求模型
```

如果模型只输出普通文本，不产生 `tool_use`，当前轮就进入可能停止的路径。

---

## 2. 防止过早结束的机制

### 2.1 用户配置的 Stop Hook 可以阻止停止

Stop Hook 的执行逻辑主要位于：

```text
src/query/stopHooks.ts
src/utils/hooks.ts
```

主循环会调用：

```ts
const stopHookResult = yield* handleStopHooks(
  messagesForQuery,
  assistantMessages,
  systemPrompt,
  userContext,
  systemContext,
  toolUseContext,
  querySource,
  stopHookActive,
)
```

如果 Hook 返回阻塞错误，Claude Code 会把错误包装成 meta user message，再进入下一轮：

```ts
if (stopHookResult.blockingErrors.length > 0) {
  state = {
    messages: [
      ...messagesForQuery,
      ...assistantMessages,
      ...stopHookResult.blockingErrors,
    ],
    stopHookActive: true,
    transition: { reason: 'stop_hook_blocking' },
  }

  continue
}
```

这构成了：

```text
模型说“完成了”
    ↓
Stop Hook 检查
    ↓
发现未完成 → 返回反馈
    ↓
反馈被注入模型上下文
    ↓
模型继续工作
```

但是这个检查逻辑不是默认存在的。Claude Code 只提供扩展点，具体检查什么由用户、插件或 Agent 定义。

### 2.2 Token budget continuation

源码：

```text
src/query/tokenBudget.ts
```

关键常量：

```ts
const COMPLETION_THRESHOLD = 0.9
const DIMINISHING_THRESHOLD = 500
```

当任务还没有消耗到预算的 90%，并且没有明显收益递减时，`checkTokenBudget()` 可以返回 continuation：

```ts
return {
  action: 'continue',
  nudgeMessage: getBudgetContinuationMessage(
    pct,
    turnTokens,
    budget,
  ),
}
```

`src/query.ts` 随后将 continuation nudge 作为 meta user message 加入上下文，要求模型继续检查和处理任务。

为了防止无意义地续命，源码还会检测收益递减。连续多次 continuation、但新增 token 很少时，会返回：

```ts
return {
  action: 'stop',
  completionEvent: {
    diminishingReturns: true,
  },
}
```

因此 token budget 的策略是：

```text
预算充足且仍有进展 → 继续
多次继续但新增内容很少 → 停止
```

需要注意：`agentId` 存在时，子 Agent 不走主线程的这套 continuation 逻辑；子 Agent 还可能受到自己的 `maxTurns` 或 Hook 限制。

### 2.3 交互式 token target 的完整生效链路

交互式写法（例如 `+500k` 或 `use 2M tokens`）不是模型本身的特殊模式，也不是 API 收到一个字符串后自动保证输出指定数量。它是 Claude Code 客户端实现的一套控制流程：

```text
用户输入 Prompt
    ↓
本地正则解析 token target
    ↓
保存为当前 turn 的预算状态
    ↓
加入 token budget 系统提示
    ↓
请求模型并统计 output token
    ↓
模型提前结束时，客户端检查预算
    ↓
注入 continuation nudge 并再次请求模型
```

#### 第一步：本地解析 Prompt

`src/utils/tokenBudget.ts` 中使用正则解析：

```ts
const SHORTHAND_START_RE =
  /^\s*\+(\d+(?:\.\d+)?)\s*(k|m|b)\b/i

const SHORTHAND_END_RE =
  /\s\+(\d+(?:\.\d+)?)\s*(k|m|b)\s*[.!?]?\s*$/i

const VERBOSE_RE =
  /\b(?:use|spend)\s+(\d+(?:\.\d+)?)\s*(k|m|b)\s*tokens?\b/i
```

支持：

```text
+500k
use 2M tokens
spend 1B tokens
```

单位转换为：

```ts
const MULTIPLIERS = {
  k: 1_000,
  m: 1_000_000,
  b: 1_000_000_000,
}
```

这一步完全在客户端完成，不依赖模型理解 `+500k` 的含义。

#### 第二步：保存当前 turn 的状态

`src/screens/REPL.tsx` 会调用：

```ts
const parsedBudget = input
  ? parseTokenBudget(input)
  : null

snapshotOutputTokensForTurn(
  parsedBudget ?? getCurrentTurnTokenBudget(),
)
```

状态定义在 `src/bootstrap/state.ts`：

```ts
let outputTokensAtTurnStart = 0
let currentTurnTokenBudget: number | null = null

export function snapshotOutputTokensForTurn(
  budget: number | null,
): void {
  outputTokensAtTurnStart = getTotalOutputTokens()
  currentTurnTokenBudget = budget
  budgetContinuationCount = 0
}
```

没有指定 target 时，状态是：

```ts
currentTurnTokenBudget === null
```

因此不存在默认的 `500k` 目标。`+500k` 只是示例和用户主动指定的目标。

#### 第三步：加入系统提示

当 `TOKEN_BUDGET` feature 开启时，`src/constants/prompts.ts` 会追加类似规则：

```text
When the user specifies a token target, your output token count
will be shown each turn. Keep working until you approach the target.
The target is a hard minimum, not a suggestion.
If you stop early, the system will automatically continue you.
```

这段提示指导模型不要过早总结，但真正的自动续接仍由客户端运行时负责。

#### 第四步：统计 output token

当前 turn 的输出 token 通过差值计算：

```ts
export function getTurnOutputTokens(): number {
  return getTotalOutputTokens() - outputTokensAtTurnStart
}
```

因此这里主要统计的是 **output token**，不是输入上下文 token，也不是 thinking budget。

#### 第五步：提前停止时注入 continuation

每轮结束时，`src/query.ts` 调用：

```ts
const decision = checkTokenBudget(
  budgetTracker!,
  toolUseContext.agentId,
  getCurrentTurnTokenBudget(),
  getTurnOutputTokens(),
)
```

如果判断应该继续，就创建 meta user message：

```ts
createUserMessage({
  content: decision.nudgeMessage,
  isMeta: true,
})
```

消息内容类似：

```text
Stopped at 42% of token target (210,000 / 500,000).
Keep working — do not summarize.
```

然后进入：

```ts
transition: {
  reason: 'token_budget_continuation',
}
```

再次请求模型。也就是说真正的机制是：

```text
模型提前结束
    ↓
客户端发现 token target 尚未达到
    ↓
客户端主动生成 continuation 消息
    ↓
模型看到新消息并继续工作
```

#### 第六步：仍然受终止条件约束

token target 不是无条件保证。以下情况仍然可以让任务停止：

```text
达到目标附近
    → 不再自动 continuation

连续多次 continuation，但新增 token 很少
    → diminishing returns，停止

达到 maxTurns、发生 API 错误或用户中断
    → 停止
```

因此它应该理解为：

```text
客户端实现的“提前停止检测 + 自动续接”机制
```

而不是：

```text
模型拥有一个永远运行的长任务模式
```

---

## 3. 上下文维护：为什么长任务可以运行很多轮

长任务的主要风险之一是上下文窗口耗尽。Claude Code 在 `src/query.ts` 和 `src/services/compact/` 中提供多层维护机制。

### 3.1 Microcompact

```text
src/services/compact/microCompact.ts
```

用于清理或压缩旧的工具输出，减少工具结果对上下文的长期占用。

### 3.2 Context Collapse

```text
src/services/contextCollapse/
```

将较早的局部上下文折叠成摘要，同时保留近期和关键内容：

```text
完整历史
    ↓
折叠较早的上下文
    ↓
保留关键状态和近期消息
    ↓
继续当前任务
```

### 3.3 Auto Compact

```text
src/services/compact/autoCompact.ts
src/services/compact/compact.ts
```

当上下文接近阈值时，自动生成摘要并替换旧消息。compact 后不会自动结束当前 query，而是继续使用新的上下文执行。

同时，`taskBudgetRemaining` 会跨 compact 边界追踪已经消耗的任务预算，避免压缩后错误地把任务预算重置。

### 3.4 Reactive Compact

如果请求已经发出，服务端返回 prompt too long，Claude Code 会尝试：

```text
context collapse drain
    ↓ 失败
reactive compact
    ↓ 失败
返回 prompt-too-long 错误
```

这使得长任务不会因为一次上下文超限就立即终止。

---

## 4. 输出截断恢复

如果模型达到 `max_output_tokens`，`src/query.ts` 会使用 continuation 消息恢复，例如：

```text
Output token limit hit. Resume directly —
no apology, no recap of what you were doing.
Pick up mid-thought if that is where the cut happened.
Break remaining work into smaller pieces.
```

恢复时会带有类似的 transition：

```ts
transition: {
  reason: 'max_output_tokens_recovery',
  attempt: maxOutputTokensRecoveryCount + 1,
}
```

但恢复次数有限。达到恢复上限后，错误会被暴露，任务终止。

---

## 5. 真正会让任务停止的条件

常见终止条件包括：

1. 模型没有产生 `tool_use`，且停止检查通过；
2. 用户配置的 Stop Hook 返回允许停止的结果；
3. 达到 `maxTurns`；
4. `taskBudget` 或 token budget 用尽；
5. continuation 多次没有实质进展，触发 diminishing returns；
6. 用户中断或 `AbortController` 被触发；
7. API 错误，例如认证、限流、服务端错误；
8. context collapse、auto compact、reactive compact 全部失败；
9. 输出 token 恢复次数耗尽；
10. 后台任务被 `killAsyncAgent()` 终止；
11. 远程 session 完成或 archived。

### `maxTurns`

`maxTurns` 在：

```text
src/query.ts
src/QueryEngine.ts
```

中传递和检查。达到限制时会生成 max-turns 事件并返回终态。

子 Agent 可能还有单独的轮数上限，例如 Agent Tool 或 Hook Agent 中的限制。

### AbortController

后台任务被终止时，典型逻辑是：

```ts
task.abortController?.abort()
```

然后任务状态进入 `killed` 或失败终态。后台运行只代表 UI 不阻塞，不代表任务永远运行。

---

## 6. Stop Hook 的默认行为

### 6.1 默认没有通用完成检查器

Stop Hook 的定义在：

```text
src/utils/hooks/hooksConfigManager.ts
```

其语义是：

```ts
Stop: {
  summary: 'Right before Claude concludes its response',
  description:
    'Exit code 0 - stdout/stderr not shown\n' +
    'Exit code 2 - show stderr to model and continue conversation\n' +
    'Other exit codes - show stderr to user only',
}
```

这只是事件定义，并不表示默认已经注册了一个检查测试或 TODO 的 Hook。

`src/utils/hooks.ts` 中，`executeStopHooks()` 会先检查当前事件是否存在 Hook：

```ts
if (!hasHookForEvent('Stop', appState, sessionId)) {
  return
}
```

如果没有配置 Stop Hook，就直接返回。

所以普通主会话的默认流程更接近：

```text
模型没有 tool_use
    ↓
没有用户 Stop Hook
    ↓
检查预算和其他内部状态
    ↓
允许返回
```

### 6.2 Stop Hook 接收什么输入

Command Hook 通过 stdin 接收 JSON，而不是通过命令行参数接收。主会话输入大致包含：

```json
{
  "hook_event_name": "Stop",
  "stop_hook_active": false,
  "last_assistant_message": "最后一条 assistant 输出",
  "session_id": "...",
  "transcript_path": "...",
  "cwd": "/path/to/project",
  "permission_mode": "default"
}
```

源码构造的核心对象类似：

```ts
{
  ...createBaseHookInput(permissionMode),
  hook_event_name: 'Stop',
  stop_hook_active: stopHookActive,
  last_assistant_message: lastAssistantText,
}
```

### 6.3 Stop Hook 的退出码

```text
exit 0 → 检查通过，允许停止
exit 2 → 阻止停止，把 stderr 反馈给模型
其他退出码 → Hook 错误，通常只提示用户
```

退出码 2 的反馈会被包装成：

```text
Stop hook feedback:
<stderr 内容>
```

然后进入下一轮。

---

## 7. 最简 Stop Hook 案例

这个例子要求任务完成后删除 `.claude/incomplete` 文件。如果文件还存在，就阻止 Claude 停止。

### Hook 脚本

`.claude/hooks/check-stop.sh`：

```bash
#!/usr/bin/env bash

# Stop Hook 的 JSON 输入通过 stdin 传入；本例暂时不需要读取
cat >/dev/null

if [ -f .claude/incomplete ]; then
  echo "任务尚未完成，请继续处理；完成后删除 .claude/incomplete。" >&2
  exit 2
fi

exit 0
```

赋予权限：

```bash
chmod +x .claude/hooks/check-stop.sh
```

### `.claude/settings.json`

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/check-stop.sh"
          }
        ]
      }
    ]
  }
}
```

执行效果：

```text
.claude/incomplete 存在
    ↓
脚本输出反馈并 exit 2
    ↓
Claude 收到“任务尚未完成”
    ↓
继续工作
```

删除文件后：

```text
.claude/incomplete 不存在
    ↓
脚本 exit 0
    ↓
允许停止
```

### 读取 Hook 输入的例子

如果需要读取输入 JSON，可以使用 `jq`：

```bash
#!/usr/bin/env bash

input=$(cat)
last_message=$(printf '%s' "$input" | jq -r '.last_assistant_message // ""')
stop_hook_active=$(printf '%s' "$input" | jq -r '.stop_hook_active // false')

if [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

if [ -f .claude/incomplete ]; then
  echo "最后输出为：$last_message" >&2
  echo "还有未完成工作，请继续。" >&2
  exit 2
fi

exit 0
```

`stop_hook_active` 可用于避免 Hook 自己造成无限阻塞：

```bash
if [ "$stop_hook_active" = "true" ]; then
  exit 0
fi
```

实际使用时应确保检查条件最终可以变成成功，否则 Hook 会不断要求 continuation，直到其他硬限制介入。

---

## 8. 多个 Stop Hook 如何聚合

Claude Code 不是从多个 Stop Hook 中选择一个，而是执行当前作用域内所有匹配的 Hook。

例如：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/check-tests.sh"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/check-todo.sh"
          }
        ]
      }
    ]
  }
}
```

聚合规则：

```text
所有 Hook exit 0
    → 允许停止

任意一个 Hook exit 2
    → 阻止停止
    → 收集 blocking error
    → 把反馈注入模型

多个 Hook exit 2
    → 收集多个反馈，一起要求模型继续
```

Hook 通常并行执行，因此不要让多个 Hook 修改同一个临时文件，除非自己处理并发。

Stop 事件没有像 `PreToolUse` 那样按工具名选择的标准 matcher。源码中 Stop Hook 的 matcher 通常使用空查询，因此不应把 Stop matcher 当成可靠的任务路由器。

---

## 9. 如何让不同任务使用不同 Stop Hook

### 9.1 推荐：一个入口脚本，按任务状态路由

配置只注册一个入口：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/stop-router.sh"
          }
        ]
      }
    ]
  }
}
```

使用 `.claude/current-task` 记录当前任务类型：

```bash
printf '%s\n' tests > .claude/current-task
```

`.claude/hooks/stop-router.sh`：

```bash
#!/usr/bin/env bash

cat >/dev/null

task=$(cat .claude/current-task 2>/dev/null || echo none)

case "$task" in
  tests)
    exec bash .claude/hooks/check-tests.sh
    ;;
  docs)
    exec bash .claude/hooks/check-docs.sh
    ;;
  build)
    exec bash .claude/hooks/check-build.sh
    ;;
  *)
    exit 0
    ;;
esac
```

例如测试检查：

```bash
#!/usr/bin/env bash

if npm test; then
  exit 0
else
  echo "测试未通过，请修复失败的测试后继续。" >&2
  exit 2
fi
```

这种方式比根据模型最后一句话判断任务类型更可靠。

### 9.2 不同 Agent 使用不同 Stop Hook

Agent/Skill frontmatter 可以注册 Hook，注册逻辑位于：

```text
src/utils/hooks/registerFrontmatterHooks.ts
```

对于子 Agent，源码会把：

```ts
Stop
```

转换成：

```ts
SubagentStop
```

示例：

```markdown
---
name: test-agent
description: Run tests and verify the project
hooks:
  Stop:
    - hooks:
        - type: command
          command: bash .claude/hooks/check-tests.sh
---
```

另一个文档 Agent：

```markdown
---
name: docs-agent
description: Verify documentation
hooks:
  Stop:
    - hooks:
        - type: command
          command: bash .claude/hooks/check-docs.sh
---
```

这样可以实现：

```text
test-agent → check-tests.sh
docs-agent  → check-docs.sh
```

这是区分不同 Agent 任务最清晰的方式。

### 9.3 按项目配置范围区分

不同项目可以使用不同的配置：

```text
~/.claude/settings.json
→ 全局通用检查

project-a/.claude/settings.json
→ 前端测试检查

project-b/.claude/settings.json
→ 后端测试检查
```

它适合“一套项目一套规则”，但不适合同一项目内同时运行许多不同任务。同一项目内的任务路由更适合使用状态文件或独立 Agent。

---

## 10. `/loop` 与长任务的区别

`/loop` 的实现位于：

```text
src/skills/bundled/loop.ts
```

它使用 cron 周期性重新发送 prompt，默认间隔为 `10m`：

```text
本次 query 结束
    ↓
等待 interval
    ↓
创建下一次 query
```

因此 `/loop` 是“外层周期调度”，不是让单个 query 永远不退出。

适合：

- 定时检查 CI；
- 轮询远程状态；
- 周期性维护；
- 每隔一段时间重新执行检查。

真正可靠的长期执行架构应当是：

```text
持久化任务状态
    +
单次有限 Agent 执行
    +
自动压缩
    +
失败重试
    +
外部 watchdog / cron
    +
可恢复进度
```

不要只依赖“一个永远不返回的 Agent Loop”。

---

## 11. 实践建议

如果要求“没有完成全部工作就不能停止”，建议同时具备：

1. 持久化任务清单，而不是只依赖模型记忆；
2. Stop Hook 检查可验证的外部状态；
3. 未完成时返回 `exit 2`，并在 stderr 写出具体反馈；
4. 保持 auto compact 开启；
5. 设置足够大的 `maxTurns` 和任务预算；
6. 为不同任务使用独立 Agent 或路由脚本；
7. 对长时间任务增加外部 watchdog 和恢复机制；
8. 确保 Hook 的条件最终可以变为成功，避免无限阻塞。

最终可以把 Claude Code 理解为：

```text
可恢复的有限执行器
```

而不是：

```text
保证永远运行的无限执行器
```
