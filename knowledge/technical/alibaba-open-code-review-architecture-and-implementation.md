# Alibaba OpenCodeReview：运行机制、实现细节与工程优化

> 项目：[`alibaba/open-code-review`](https://github.com/alibaba/open-code-review)  
> 分析版本：`3355baea0e83`（`main`）  
> 分析日期：2026-07-24  
> 本地源码：`/home/azureuser/.openclaw/workspace/open-code-review`

## 1. 摘要

OpenCodeReview（以下简称 OCR）不是简单地将整个 Git Diff 提交给大模型并要求生成一段审查文本，而是一套以“单文件”为并发和会话边界的 Agentic Code Review 流水线。

它首先从工作区、单个 Commit 或两个 Git Ref 之间获取 Unified Diff，解析出文件级变更；随后根据路径、扩展名、规则文件和 Token 预算过滤文件。对于每个待审文件，OCR 可先调用 LLM 生成审查计划，再进入允许读取源码、搜索代码、查看关联 Diff 和提交结构化评论的工具调用循环。模型生成评论后，系统使用确定性算法将 `existing_code` 映射到实际行号；定位失败时再调用独立的 LLM 重定位任务。主审结束后，还会通过一个保守的事实核查任务删除能够仅凭 Diff 证明错误的评论。最终结果可以输出为文本或 JSON，并由 GitHub Action 发布为 PR Inline Review Comments 和汇总评论。

核心链路：

```text
CLI / GitHub Action
        ↓
获取 Git Diff（Workspace / Commit / Range）
        ↓
解析为文件级 Diff + 加载新文件完整内容
        ↓
过滤目录、二进制、扩展名、用户规则、超大 Diff
        ↓
为每个文件匹配 Review Rule
        ↓
按文件并发
  ┌──────────────────────────────────────┐
  │ 可选 Plan LLM：风险识别与工具规划   │
  │              ↓                       │
  │ Main LLM Tool Loop                   │
  │ ├─ file_read                         │
  │ ├─ file_find                         │
  │ ├─ code_search                       │
  │ ├─ file_read_diff                    │
  │ ├─ code_comment                      │
  │ └─ task_done                         │
  │              ↓                       │
  │ 评论行号解析 → 必要时 LLM 重定位     │
  │              ↓                       │
  │ Review Filter：保守删除明确误报       │
  └──────────────────────────────────────┘
        ↓
评论聚合、Session 记录、Token/Telemetry 统计
        ↓
Text / JSON / GitHub PR Review
```

---

## 2. 程序入口与运行模式

CLI 分发入口位于：

- `cmd/opencodereview/main.go`
- `cmd/opencodereview/review_cmd.go:21`：`runReview()`

`runReview()` 主要完成：

1. 解析命令行参数；
2. 确认 Git 仓库根目录；
3. 加载系统、全局、项目及 CLI 指定的 Review Rule；
4. 校验 Git Ref，防止参数注入；
5. 加载 LLM Runtime 和 Tool 配置；
6. 注册内置工具及 MCP 动态工具；
7. 构建 `agent.Agent`；
8. 调用 `Agent.Run()`；
9. 输出文本或 JSON 结果。

### 2.1 三种 Diff 模式

OCR 支持三种审查模式：

| 模式 | 输入 | 用途 |
|---|---|---|
| Workspace | 无 Commit/Range 参数 | 审查 staged、unstaged 和 untracked 文件 |
| Commit | `--commit <ref>` | 审查单个 Commit 相对于父提交引入的变化 |
| Range | `--from <ref> --to <ref>` | 审查分支或 PR 范围 |

实现位于 `internal/diff/git.go:36-43`。

Range 模式先执行：

```bash
git merge-base <from> <to>
```

再执行：

```bash
git diff <merge-base> <to>
```

这比直接比较 `<from>..<to>` 更符合 PR Review 语义，因为它只关注来源分支从共同祖先开始引入的变化。

Commit 模式对 Merge Commit 使用 `--diff-merges=first-parent`，避免普通 `git show` 产生解析器不支持的 combined diff（`diff --cc`）。

Workspace 模式优先使用：

```bash
git diff HEAD
```

如果仓库尚无第一个 Commit，则回退到：

```bash
git diff --staged
```

未跟踪文件不在普通 `git diff` 中，OCR 会单独获取并人为构造 Unified Diff。

---

## 3. Diff 获取、解析与完整文件上下文

### 3.1 安全、稳定的 Git 调用

Git 命令统一使用以下约束：

- `--no-ext-diff`：禁止外部 Diff Driver；
- `--no-textconv`：禁止 TextConv；
- `--no-color`：保证解析输入稳定；
- `--end-of-options`：防止恶意 Ref 被解释为 Git 参数；
- `core.quotepath=false`：保留非 ASCII 文件名；
- `--find-renames`：识别重命名；
- 默认 `-U3`：每个 Hunk 保留三行上下文。

默认三行上下文定义于：

```go
const DiffContextLines = 3
```

位置：`internal/diff/git.go:17-18`。

### 3.2 文件级 Diff 解析

`internal/diff/parser.go:25` 的 `ParseDiffText()` 将 Unified Diff 转换为 `model.Diff`，主要记录：

- 旧路径和新路径；
- 原始 Diff；
- 新增和删除行数；
- 新建、删除、重命名、二进制状态；
- 变更后完整文件内容。

解析器通过 `@@` 标记维护 `inHunk` 状态，仅在 Hunk 内统计 `+` 和 `-`，避免把 `--- a/file`、`+++ b/file` 误判为删除和新增代码。

对于 Commit/Range 模式，变更后的完整文件内容通过以下命令读取：

```bash
git show <ref>:<path>
```

而不是读取当前工作区，因此审查内容始终与目标 Ref 一致。Workspace 模式则读取磁盘上的当前文件。

这项设计很重要：三行 Diff 上下文适合控制 Token，却不足以理解完整函数；完整文件内容可供 `file_read` 和评论行号回退定位使用。

---

## 4. 多层文件过滤

OCR 使用多层过滤降低噪声、开销与失败概率。

### 4.1 Provider 层目录过滤

`internal/diff/git.go:20-34` 默认过滤：

```text
.git/  .idea/  .vscode/  .svn/
vendor/  node_modules/  target/
.cachefile/  _packages/  rpm/  pkgs/ ...
```

同时读取项目根目录 `.gitignore`。这里的 `.gitignore` 匹配是轻量实现，并非完整复刻 Git 的所有语义。

### 4.2 Agent 层过滤

`internal/agent/agent.go:837` 再根据以下条件过滤：

- 二进制文件；
- 默认路径/扩展名规则；
- 用户 `include`/`exclude`；
- CLI 追加的 excludes。

纯删除文件不会进入正常逐文件审查，因为 Prompt 主要关注新加入或修改后的代码。

### 4.3 Token 预算过滤

`internal/agent/agent.go:791` 会预估每个 Diff 的 Token 数。若单个文件的 Diff 已超过 `max_tokens` 的 80%，该文件会被跳过，防止初始 Prompt 直接超过模型上下文。

这是稳定性优化，但也带来取舍：超大文件目前主要是“跳过”，而不是进一步按 Hunk 切分审查。

### 4.4 过滤前构建完整 DiffMap

`Agent.Run()` 在 Review 过滤之前，用所有解析出的 Diff 构建只读 `DiffMap`：

```text
internal/agent/agent.go:202-205
```

因此某个文件即使不直接进入 Review，模型仍可通过 `file_read_diff` 查看其变化，以确认跨文件修改是否配套。

---

## 5. Review Rule 系统

规则实现位于 `internal/config/rules/system_rules.go`。

规则优先级为：

```text
CLI --rule 指定的规则
    > 项目 .opencodereview/rule.json
    > ~/.opencodereview/rule.json
    > 内置 System Rule
```

项目规则示例：

```json
{
  "rules": [
    {
      "path": "**/*.go",
      "rule": "重点检查 goroutine 泄漏、锁顺序和错误处理",
      "merge_system_rule": true
    }
  ],
  "include": ["internal/**"],
  "exclude": ["**/*_generated.go"]
}
```

规则匹配支持：

- `**` 递归 Glob；
- `{go,py,js}` Brace Expansion；
- Include/Exclude；
- 按文件路径选择不同审查清单；
- `merge_system_rule` 合并用户规则与系统规则。

默认情况下，用户规则会替换系统规则；设置 `merge_system_rule: true` 后，两类规则会带清晰标题一起注入 Prompt。

这一机制让 Review 从“通用大模型判断”变成“按语言、目录、业务模块定制的审查”。

---

## 6. 按文件并发的 Agent 架构

主流水线位于：

```text
internal/agent/agent.go:189
Agent.Run()
```

主要顺序：

```go
loadDiffs()
injectDiffMap()
filterDiffs()
dispatchSubtasks()
```

`dispatchSubtasks()` 位于 `internal/agent/agent.go:350`。它以单文件为并发单位，默认并发数为 8，并使用 Semaphore 限流。

每个文件拥有：

- 独立 Prompt；
- 独立 Plan 结果；
- 独立 LLM Tool Loop；
- 独立文件 Session；
- 独立超时；
- 独立成功、失败或复用状态。

单个文件 Panic 或失败会被隔离，其他文件继续执行。只有全部已调度文件都失败时，整体 Review 才返回错误。

### 6.1 为什么按文件拆分

优点：

- 控制单次上下文大小；
- 文件间可并行；
- 一个文件失败不拖垮整个 PR；
- 评论天然绑定当前文件；
- 便于做单文件超时、断点恢复和指标统计。

限制：

- 对架构级、全局不变量和复杂跨文件问题的发现能力弱于“整个变更集统一推理”；
- 其他文件主要作为按需读取的上下文，而不是与当前文件完全联合推理。

---

## 7. Plan 阶段：先识别风险，再正式审查

每个文件可先执行 Plan Task：

```text
internal/agent/agent.go:876
executePlanPhase()
```

Plan Prompt 要求输出结构化 JSON，包括：

- 变更摘要；
- 潜在风险；
- 风险等级；
- 建议调用的工具；
- 工具调用目的和参数。

示意：

```json
{
  "change_summary": "为缓存读取增加快速路径",
  "issues": [
    {
      "severity": "high",
      "description": "缓存未命中路径可能返回 nil，调用方解引用后崩溃",
      "tool_guidance": [
        {
          "name": "code_search",
          "reason": "确认所有调用方是否检查 nil",
          "arguments": "搜索新函数的调用点"
        }
      ]
    }
  ]
}
```

Plan 阶段只制定计划，不真正执行工具。结果作为 `{{plan_guidance}}` 注入 Main Task。

当改动行数低于配置的 `plan_mode_line_threshold` 时可跳过 Plan，以节省一次 LLM 请求。Plan 调用失败也不会中止 Review，而是记录警告并继续 Main Task。

---

## 8. Main Task：LLM 工具调用循环

主循环实现于：

```text
internal/llmloop/loop.go:143
RunPerFile()
```

每次 LLM 请求包含：

- 当前文件路径；
- 当前文件 Diff；
- 其他已变更文件列表；
- 当前时间；
- Requirement Background；
- 当前文件匹配到的 Review Checklist；
- 可选 Plan Guidance；
- 当前会话历史和前几轮工具结果；
- 可用工具定义。

循环过程：

```text
发送消息和工具定义给 LLM
        ↓
解析 Tool Calls
        ↓
执行每个工具并把结果加入会话
        ↓
模型继续分析或生成评论
        ↓
模型显式调用 task_done 后结束
```

如果模型没有产生工具调用，OCR 会追加纠正提示，要求模型重试或调用 `task_done`。连续三轮没有有效工具结果，或达到最大工具请求次数后停止，避免死循环。

### 8.1 内置工具

工具定义主要位于 `internal/config/toolsconfig/tools.json`。

#### `file_read`

读取变更后版本的完整文件或指定行范围，单次最多返回 500 行。用于补充三行 Diff 上下文之外的函数、类和模块语义。

#### `file_find`

按路径或文件名查找仓库文件。适合模型知道组件名称但不知道准确路径时使用。

#### `code_search`

支持普通字符串、大小写控制、Git Pathspec 和 Perl 正则搜索，最多返回 100 个结果。用于寻找定义、调用点、配置字段和关联实现。

#### `file_read_diff`

读取其他变更文件的 Diff。典型用途：

- 接口变更后确认调用方是否同步修改；
- 新增字段后确认序列化逻辑是否更新；
- 配置变化后确认加载和默认值是否配套；
- 测试与实现是否一起修改。

#### `code_comment`

提交结构化 Review Comment：

```json
{
  "content": "问题及影响说明",
  "existing_code": "用于定位的新增代码片段",
  "suggestion_code": "可选建议代码",
  "category": "bug",
  "severity": "high"
}
```

#### `task_done`

模型显式声明当前文件审查完成。

### 8.2 MCP 扩展

CLI 会初始化配置中的 MCP Client，将 MCP Tool Definitions 追加到 Plan 和 Main 阶段。因此 OCR 的 Agent 能力并不局限于内置源码工具，可按配置接入额外静态分析、知识库或组织内部服务。

---

## 9. Prompt 约束与幻觉防护

Main System Prompt 明确要求：

- 只评论当前文件；
- 只关注新增或修改代码；
- 不评论已删除代码；
- 不对正确代码进行无意义点评；
- 其他文件只能用于理解上下文；
- 若上下文不足，应先使用工具而不是猜测；
- 只有确认存在问题后才调用 `code_comment`。

另外，程序不会信任模型在 `code_comment` 参数中提供的路径：

```go
if t == tool.CodeComment && newPath != "" {
    args["path"] = newPath
}
```

位置：`internal/llmloop/loop.go:325-329`。

这意味着即使模型生成了错误或幻觉文件名，评论仍会被强制绑定到当前文件。

---

## 10. 评论行号解析与 LLM 重定位

模型不直接负责给出最终 GitHub 行号，而是通过 `existing_code` 提供评论对应的源码片段。

确定性定位实现位于：

```text
internal/diff/resolver.go
```

### 10.1 Diff Hunk 匹配

`resolveFromHunk()` 首先解析 Hunk 起始行号，分别建立：

- 新文件侧：Context + Added Lines；
- 旧文件侧：Context + Deleted Lines。

随后对归一化后的 `existing_code` 做连续滑动窗口匹配，得到 `StartLine` 和 `EndLine`。新文件侧优先，旧文件侧作为回退。

### 10.2 完整文件匹配

若 Diff Hunk 中没有找到，则扫描 `NewFileContent`。匹配前会：

- Trim 首尾空白；
- 去掉开头 `+` 或 `-`；
- 忽略空行；
- 保留原始文件行号映射。

这样可以容忍模型返回代码片段时的部分格式差异。

### 10.3 LLM Re-location

如果确定性匹配仍失败，且配置了 `ReLocationTask`，OCR 会进行一次独立 LLM 请求：

- 输入当前 Diff；
- 输入评论内容；
- 输入原始 `existing_code`；
- 要求模型只从 Diff 中提取准确代码片段。

调用位置：`internal/llmloop/loop.go:353-372`。

重定位请求会独立记录 Session 和 Token 使用量。

完整链路：

```text
模型提供 existing_code
       ↓
Diff Hunk 连续匹配
       ↓ 失败
完整新文件连续匹配
       ↓ 失败
LLM Re-location 提取精确代码
       ↓
重新获得可发布的代码位置
```

这是“确定性算法优先、LLM 兜底”的典型设计：尽量不用模型做本可准确计算的工作，只在模糊场景调用模型。

---

## 11. 评论异步后处理

`code_comment` 的解析、行号定位和必要的 LLM 重定位可以提交给独立 `CommentWorkerPool`：

```text
internal/llmloop/loop.go:378-396
```

主 LLM Tool Loop 提交评论后即可继续，不需要同步等待后处理完成。单文件 Main Task 结束后，程序只调用：

```go
CommentWorkerPool.AwaitKey(newPath)
```

等待当前文件对应的评论任务，而不是全局等待其他文件，避免错误使用 `sync.WaitGroup`，也减少文件之间的无谓阻塞。

---

## 12. Review Filter：保守的第二轮事实核查

主审完成后，OCR 会运行 `REVIEW_FILTER_TASK`：

```text
internal/agent/agent.go:639
executeReviewFilter()
```

输入包括：

- 当前文件 Diff；
- 当前文件刚生成的评论；
- 每条评论的临时 ID，如 `c-0`、`c-1`。

过滤 Prompt 的原则非常保守：

> 只删除那些能够仅根据当前 Diff 明确证明错误的评论；如果仅凭 Diff 无法判断，则必须保留，因为主 Agent 可能通过工具看过完整代码上下文。

模型只返回需要删除的 ID：

```json
["c-0", "c-3"]
```

解析失败、请求失败或超时不会影响已有评论，过滤错误会被静默降级为“全部保留”。

这一步主要降低明显误报，而不是让第二个模型随意重写第一个模型的判断。

---

## 13. 上下文和 Token 管理

多轮工具调用会不断扩大消息历史。OCR 在 `internal/llmloop/compression.go` 和 `internal/llmloop/loop.go:432` 实现分区上下文压缩。

总体策略：

- 约 60% 上下文占用时，尝试异步压缩旧消息；
- 接近 80% 时，强制同步压缩；
- 若压缩后仍超过警戒线，停止当前文件循环；
- 初始 Diff 本身超过 80% 时，在进入循环前跳过该文件。

压缩状态归属于单文件会话，文件结束时会取消仍在运行的压缩任务，避免跨文件污染。

---

## 14. Session、断点恢复与可观测性

OCR 会保存文件级任务记录，包括：

- Plan Task 请求和响应；
- Main Task 每轮消息和 Tool Result；
- Re-location Task；
- Review Filter Task；
- 文件完成、失败或复用状态；
- 评论结果；
- Token 使用量和耗时。

### 14.1 Resume

每个文件的 Fingerprint 由以下内容计算 SHA-256：

```text
Review Mode + Old Path + New Path + Diff
```

实现位于 `internal/agent/agent.go:509-511`。

恢复执行时，Fingerprint 未变化的文件可直接复用此前评论；只有变化过的文件重新审查。这能显著降低大型 Review 在部分失败、超时或重试时的成本。

### 14.2 Telemetry

代码中为以下阶段建立了 Span 或指标：

- Diff 解析；
- 文件调度；
- Plan；
- Main Loop；
- LLM Request；
- Tool Call；
- Re-location；
- Review Filter；
- 评论数量；
- Token 和 Cache Token；
- 文件级失败与警告。

这些数据可用于定位慢请求、模型故障、工具错误和成本异常。

---

## 15. GitHub Action 发布流程

GitHub Action 定义于 `action.yml`。

PR 场景下，它不会直接 Checkout 不可信的 PR Head，而是：

1. Checkout 可信 Base；
2. 单独 Fetch PR Head 的 Git Objects；
3. 计算 Merge Base；
4. 执行 JSON 格式 Review：

```bash
ocr review \
  --from "${MERGE_BASE}" \
  --to "${HEAD_SHA}" \
  --format json
```

5. 保存 `/tmp/ocr-result.json` 和 stderr；
6. 可选上传 Artifact；
7. 使用 `actions/github-script` 发布结果。

发布逻辑位于：

```text
scripts/github-actions/post-review-comments.js
```

有合法代码位置的评论通过：

```js
github.rest.pulls.createReview(...)
```

发布为 Inline Review Comments；无法安全定位的内容进入 Summary，而不是强行贴到可能错误的代码行。

发布层还实现了：

- 批量创建 Review；
- 批量失败后的逐条降级；
- 5xx、限流和网络错误重试；
- 指数退避与 `Retry-After`；
- 请求超时后的幂等检查；
- Sticky Summary 更新；
- Incremental 模式；
- 与历史评论按代码行范围重叠度去重；
- 发布统计和失败汇总。

---

## 16. 关键工程优化汇总

### 16.1 成本与性能

1. **按文件并发**：默认最多八个文件并行；
2. **小改动跳过 Plan**：减少一次 LLM 调用；
3. **Comment Worker Pool**：评论定位和重定位异步执行；
4. **按文件等待**：不阻塞其他文件任务；
5. **工具按需补上下文**：初始 Diff 只保留三行上下文；
6. **上下文异步压缩**：提前处理会话膨胀；
7. **Resume Fingerprint**：复用未变化文件的结果；
8. **Token 预过滤**：避免注定失败的超大请求。

### 16.2 准确性

1. **Plan + Main 两阶段**：先梳理风险，再执行审查；
2. **完整源码读取和搜索**：不只依赖局部 Diff；
3. **查看其他变更文件**：确认跨文件改动是否配套；
4. **结构化 `code_comment`**：避免解析自然语言输出；
5. **路径强制绑定当前文件**：防止模型评论错文件；
6. **确定性行号解析**：不让模型直接猜行号；
7. **LLM Re-location 兜底**：提高复杂片段定位率；
8. **保守 Review Filter**：仅删除可由 Diff 明确证伪的评论；
9. **无法定位则进入 Summary**：避免错误 Inline Comment。

### 16.3 稳定性

1. **单文件 Panic/错误隔离**；
2. **单文件超时**；
3. **最大工具请求次数**；
4. **连续空结果熔断**；
5. **Plan/Filter 失败可降级继续**；
6. **GitHub 发布重试、退避和幂等检查**；
7. **Merge Commit 使用 First Parent Diff**；
8. **无初始 Commit 时兼容 staged diff**。

### 16.4 安全性

1. Git Ref 预校验；
2. Git 命令使用 `--end-of-options`；
3. 禁用 External Diff 和 TextConv；
4. GitHub Action Checkout 可信 Base，不执行不可信 PR 工作区代码；
5. Tool Registry 在并发使用前 Freeze；
6. 模型不能自行指定评论目标文件。

---

## 17. 设计取舍与潜在改进

### 17.1 多阶段 LLM 调用成本较高

一个文件可能经历：

```text
Plan 1 次
+ Main 多轮
+ 0~N 次 Re-location
+ Review Filter 1 次
+ 上下文压缩调用
```

准确性和可解释性提高，但延迟、Token 和模型调用费用也明显增加。

可考虑：

- 按文件风险等级决定是否启用 Plan/Filter；
- 低风险文件使用更小模型；
- Re-location 批处理；
- 对稳定规则引入 AST 或静态分析器，减少 LLM 判断。

### 17.2 超大 Diff 主要采用跳过策略

当前单文件 Diff 超过阈值会被过滤。更完整的方案可以：

- 按 Hunk 分块；
- 按函数/类边界分块；
- 先生成文件级摘要，再分块审查；
- 最后进行跨块合并和去重。

### 17.3 跨文件推理仍受单文件边界限制

虽然能读取其他 Diff 和源码，但主评论目标始终是当前文件。对于协议变更、状态机不变量、数据库迁移和调用链问题，可能需要增加：

- 变更集级 Plan；
- 跨文件依赖图；
- 项目级终审阶段；
- 基于 Symbol/Call Graph 的上下文召回。

### 17.4 文本定位可能遇到重复代码

`existing_code` 使用连续文本匹配，遇到重复代码片段时可能定位到第一个匹配位置。可增强为：

- 同时要求模型给出函数/类名；
- 使用 Hunk ID 和上下文 Hash；
- 基于 AST Node 定位；
- 对多个匹配候选再进行确定性消歧。

### 17.5 `.gitignore` 不是完整 Git 语义

当前实现是轻量匹配器，对复杂 Negation、嵌套 `.gitignore` 等行为可能与 Git 本身不同。可以直接复用成熟 GitIgnore 库或查询 `git check-ignore`。

---

## 18. 总结

OpenCodeReview 的核心价值不只是“用 LLM 看 Diff”，而是用工程化流水线约束 LLM：

- Git 提供精确变更边界；
- Rule 提供审查标准；
- Plan 提供风险导向；
- Tools 提供真实代码上下文；
- Tool Loop 支持逐步验证；
- `code_comment` 提供结构化输出；
- Resolver 提供确定性代码定位；
- Re-location 处理模糊定位；
- Filter 抑制明确误报；
- Session/Resume 控制失败恢复与成本；
- GitHub 发布层处理幂等、降级和评论去重。

它体现了一个值得复用的 Agent 系统设计原则：

> **让 LLM 负责理解、规划和判断；让程序负责边界、安全、状态、定位、并发和可靠交付。**

这也是该工具相较于“一次 Prompt 完成 Code Review”的主要优势。

---

## 19. 关键源码索引

| 模块 | 文件/位置 |
|---|---|
| CLI Review 入口 | `cmd/opencodereview/review_cmd.go:21` |
| 工具注册 | `cmd/opencodereview/review_cmd.go:315` |
| Agent 主流程 | `internal/agent/agent.go:189` |
| Diff 加载 | `internal/agent/agent.go:302` |
| 文件并发调度 | `internal/agent/agent.go:350` |
| 单文件 Plan + Main | `internal/agent/agent.go:521` |
| Review Filter | `internal/agent/agent.go:639` |
| Token 大文件过滤 | `internal/agent/agent.go:791` |
| 文件 Review 过滤 | `internal/agent/agent.go:837` |
| Plan 执行 | `internal/agent/agent.go:876` |
| Git Diff Provider | `internal/diff/git.go:109` |
| Unified Diff 解析 | `internal/diff/parser.go:25` |
| 评论行号定位 | `internal/diff/resolver.go:57` |
| LLM Tool Loop | `internal/llmloop/loop.go:143` |
| Tool Call 分发 | `internal/llmloop/loop.go:270` |
| Comment 异步定位 | `internal/llmloop/loop.go:333` |
| 上下文压缩 | `internal/llmloop/compression.go` |
| 工具 Schema | `internal/config/toolsconfig/tools.json` |
| Prompt | `internal/config/template/prompts/` |
| Rule Resolver | `internal/config/rules/system_rules.go:252` |
| GitHub Action | `action.yml` |
| PR 评论发布 | `scripts/github-actions/post-review-comments.js` |

## 20. 验证说明

本报告基于 Commit `3355baea0e83` 的实际源码调用链整理，不仅依据 README。分析时仓库状态干净、Remote 正确。当前分析环境未安装 Go，无法执行 `go test ./...`，命令报错为 `go: command not found`；因此本文完成了源码级交叉核对，但没有在该 Azure VPS 上完成 Go 测试套件验证。
