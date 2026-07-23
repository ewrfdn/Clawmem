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

本文将 OpenCodeReview 的可执行文件简称为 `ocr`。程序入口是
`cmd/opencodereview/main.go:15-28` 的 `main()`：它先设置版本和内嵌资源加载器，
再初始化 Telemetry，最后调用 `dispatch()`；任一子命令返回错误时，统一向标准错误输出
`Error: ...` 并以状态码 1 退出。`dispatch()` 并不会把“无参数”偷偷解释为一次 Review，
而是打印总帮助；只有显式执行 `ocr review`（或别名 `ocr r`）才进入本报告讨论的
Diff Review 流程。其他顶层命令还包括 `scan`、`config`、`llm`、`rules`、`viewer`、
`delegate` 和 `session`（`cmd/opencodereview/main.go:30-68`）。

> **初学者可能会问：`review` 与 `scan` 有什么根本区别？**
> `review` 的输入是 Git 变化，因此必须位于带工作树的 Git 仓库；`scan` 可以检查完整文件，
> 也允许非 Git 目录。`review` 通过 `loadCommonContext(..., requireGit=true)` 明确实施这一约束，
> 并把从仓库子目录启动时的路径提升到 Git 顶层，保证 Diff 中的仓库根相对路径、规则路径和
> 文件读取基准一致；裸仓库因没有工作树会直接报错（`cmd/opencodereview/shared.go:40-78,81-123`；
> 对应测试见 `cmd/opencodereview/shared_test.go:80-217`）。

`cmd/opencodereview/review_cmd.go:21-155` 的 `runReview()` 是 Review 编排层。按实际执行顺序，
它完成以下数据变换：

1. `parseReviewFlags()` 把字符串参数变为 `reviewOptions`，并在访问仓库前排除冲突模式、
   缺失的 `--from/--to` 配对、非法 audience，以及 `--preview` 与 `--resume` 同用等错误
   （`cmd/opencodereview/flags.go:95-193`）。
2. `loadCommonContext()` 加载并校验内嵌 Prompt 模板，解析 Git 顶层目录，建立 Review Rule
   解析器、文件过滤器和共享的 Git 子进程并发限制器；随后把 CLI 的 `--exclude` 追加到
   规则层给出的排除项（`cmd/opencodereview/shared.go:24-78,183-194`）。
3. `validateReviewRefs()` 拒绝以 `-` 开头或不能由 `git rev-parse --verify` 解析为 Commit 的
   `--from`、`--to`、`--commit`，然后才允许这些值流入后续 Git 命令
   （`cmd/opencodereview/review_cmd.go:39-47,215-241`）。
4. 组装背景信息：Commit 模式在未显式提供 `--background` 时使用 Commit Message；
   `--background-file` 则相对 Git 顶层读取并与内联背景合并
   （`cmd/opencodereview/review_cmd.go:44-62`）。
5. 若为 `--preview`，只构建一个最小 `Agent` 获取并过滤 Diff，输出待审文件后返回；这条分支
   位于 `loadLLMRuntime()` 之前，所以**预览不要求 API Key，也不会调用 LLM 或启动 MCP Server**
   （`cmd/opencodereview/review_cmd.go:64-66,244-260`；`internal/agent/preview.go:61-108`）。
6. 正式 Review 才加载可恢复 Session、LLM 与 Tool 配置，按 Review 模式创建 `FileReader`，
   注册内置工具和可用的 MCP 工具，再把所有依赖注入 `agent.New()`。
7. `Agent.Run()` 获取并解析 Diff、过滤文件、并发启动逐文件 Agent，最终把评论、Token/Tool
   统计和 Session 信息交给 `emitRunResult()` 输出；失败时保留 Session ID 供 `--resume`
   重试（`cmd/opencodereview/review_cmd.go:68-154`；`internal/agent/agent.go:189-235`）。

最小运行时序可概括为：

```text
argv
  -> dispatch("review")
  -> 参数校验 + 仓库/规则/模板初始化
  -> [preview: Diff -> 过滤 -> 文件清单 -> 返回]
  -> LLM/工具/MCP 初始化
  -> Agent.Run(): Diff -> model.Diff[] -> 文件过滤 -> 逐文件 LLM Tool Loop
  -> model.LlmComment[] -> 文本或 JSON
```

### 2.1 “配置”不是一个文件：四类配置及加载时机

初次阅读容易把 Prompt、工具、规则和模型凭据都理解成同一份配置。源码实际上把它们分成
四条独立输入链：

| 配置类别 | 默认来源 | CLI 覆盖/补充 | 何时加载、产生什么结果 |
|---|---|---|---|
| Review Prompt 与预算 | 编译进二进制的 `task_template.json` 和 `prompts/*` | `--max-tools` 只在高于模板值时提高上限 | `loadCommonContext()` 最先加载并 `Validate()`，得到 `template.Template`；`--max-tools` 的非零值低于 10 时先被钳制到 10（`internal/config/template/template.go:45-130,188-199`；`cmd/opencodereview/shared.go:49-59`；`cmd/opencodereview/flags.go:179-186`） |
| Review Rule 与文件过滤 | 内嵌系统规则；可选全局 `~/.opencodereview/rule.json` 和仓库根 `.opencodereview/rule.json` | `--rule <file>` 的优先级最高；`--exclude` 再追加排除模式 | `rules.NewResolver()` 返回“按文件选择规则”的 `Resolver` 和独立的 `FileFilter`。规则匹配优先级为 CLI > 项目 > 全局 > 系统；文件 include/exclude 则取首个实际配置了过滤项的高优先级层，并非四层合并（`internal/config/rules/system_rules.go:237-311,313-381`） |
| LLM Endpoint、语言和 MCP | `~/.opencodereview/config.json` | `--model` 覆盖本次模型；部分 LLM 字段可来自环境变量 | 正式 Review 的 `loadLLMRuntime()` 读取用户配置，将 `language` 指令写入 Prompt，解析 Endpoint，创建 LLM Client；配置文件不存在本身不是错误，但若所有 Endpoint 来源都不完整，随后解析会失败（`cmd/opencodereview/shared.go:126-180`；`cmd/opencodereview/config_cmd.go:14-30,211-271`） |
| LLM 可见的 Tool 定义 | 编译进二进制的 `internal/config/toolsconfig/tools.json` | `--tools <file>` 可整体换成外部 JSON；用户配置中的 `mcp_servers` 可增加动态工具 | `toolsconfig.Load()` 按 `plan_task` / `main_task` 生成两组工具定义；`buildToolRegistry()` 注册真实执行器，MCP 启动成功后再把其定义追加到两阶段（`internal/config/toolsconfig/toolsconfig.go:19-53`；`cmd/opencodereview/review_cmd.go:86-100,263-322`） |

> **初学者可能会问：参数、工具定义和工具执行器为什么分开？**
> Tool 定义是发给 LLM 的 JSON Schema，说明“工具叫什么、参数是什么”；Registry 中的 Provider
> 才是在本机真正读取文件、搜索代码或收集评论的实现。只有两边同名配对，LLM 返回的 Tool Call
> 才能被执行。`agent.BuildToolDefs()` 负责前者，`buildToolRegistry()` 负责后者
> （`internal/agent/agent.go:978-996`；`cmd/opencodereview/review_cmd.go:315-322`）。

LLM Endpoint 的优先级尤其容易误读。`ResolveEndpointWithModelOverride()` 依次尝试：

1. `~/.opencodereview/config.json`（新 provider 结构或旧 `llm` 结构）；
2. `OCR_LLM_URL` / `OCR_LLM_TOKEN` / `OCR_LLM_MODEL`；
3. Claude Code 的 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_MODEL`；
4. Shell RC 文件。

每个来源必须同时解析出 URL、Token、Model 才算可用，先成功者获胜；`--model` 会在每种策略内
覆盖模型，provider 声明了可选模型列表时还会校验该值。`OCR_LLM_TIMEOUT` 和
`OCR_LLM_EXTRA_HEADERS` 是在选中来源后再施加的全局覆盖
（`internal/llm/resolver.go:58-121,243-403`）。值得注意的是，`review` 固定读取默认用户配置路径，
不会采用 `OCR_CONFIG_PATH`；该变量只供诸如 `ocr llm test` 的只读命令使用，以免泄漏的环境变量
把配置写入或常规 Review 重定向到意外位置（`cmd/opencodereview/config_cmd.go:14-30`；
`cmd/opencodereview/shared.go:152-169`）。

配置失败的处理也分为“关键依赖”和“可选扩展”：模板、规则文件、工具 JSON、用户配置 JSON、
Endpoint 或 Resume 校验失败都会中止 Review；单个 MCP Server 缺少命令、Setup 失败或启动失败时
只输出警告并跳过该 Server，Review 继续使用其余工具。已启动的 MCP Client 在 `runReview()`
返回时统一关闭（`cmd/opencodereview/review_cmd.go:88-100,263-312`）。

### 2.2 三种 Review / Diff 模式

这里的 **Diff** 是 Git 用统一文本格式表达的“旧版本到新版本有哪些行发生变化”；Review 模式
决定“旧/新版本从哪里取”，同时也决定 LLM 调用 `file_read` 等工具时应该读取哪个版本的完整文件。

| 模式 | CLI 输入 | Diff 的比较对象 | 工具读取完整文件的来源 |
|---|---|---|---|
| Workspace | 不传 Commit/Range 参数 | `HEAD` 对工作区（涵盖已暂存和未暂存），再补未跟踪文件 | 当前磁盘文件 |
| Commit | `--commit <ref>` | 指定 Commit 对其第一父提交引入的变化 | `git show <commit>:<path>` |
| Range | `--from <ref> --to <ref>` | `merge-base(from,to)` 对 `to` | `git show <to>:<path>` |

Diff Provider 的模式选择位于 `internal/agent/agent.go:302-329`，具体 Git 调用位于
`internal/diff/git.go:36-88,109-165`；完整文件读取模式则是另一组对应枚举，位于
`internal/tool/filereader.go:18-77`。两者必须同步：例如 Range Review 的 Diff 右侧是 `to`，
若工具错误地读取当前磁盘文件，LLM 看到的行号和代码内容就可能与待审版本不一致。

Range 模式先执行：

```bash
git merge-base <from> <to>
```

再执行：

```bash
git diff <merge-base> <to>
```

这比直接比较 `<from>..<to>` 更符合 PR Review 语义，因为它只关注来源分支从共同祖先开始引入的变化。

> **初学者可能会问：merge-base 到底解决了什么问题？** 设主分支和功能分支都从提交 `B`
> 分叉：主分支后来到 `M`（`from`），功能分支后来到 `F`（`to`）。`merge-base M F` 得到双方最近的
> 共同祖先 `B`，再比较 `B → F`，结果只包含功能分支自己的改动。若直接比较 `M → F`，主分支
> `B → M` 的变化也会以“反向差异”混进审查。实现会缓存 merge-base；找不到共同祖先时明确报错，
> 不会退化成含义不确定的比较（`internal/diff/git.go:100-123,259-265`）。

Commit 模式对 Merge Commit 使用 `--diff-merges=first-parent`，即把 Merge Commit 与第一父提交比较，
避免普通 `git show` 产生解析器不支持的 combined diff（`diff --cc`）。这回答了“一个 Merge Commit
有两个父提交时以谁为旧版本”：OCR 明确采用第一父提交，而不是把两个方向揉成一份 Diff
（`internal/diff/git.go:125-134`；`internal/diff/git_test.go:477`）。

Workspace 模式优先使用：

```bash
git diff HEAD
```

如果仓库尚无第一个 Commit，则回退到：

```bash
git diff --staged
```

未跟踪文件不在普通 `git diff` 中，OCR 会单独获取并人为构造 Unified Diff。

> **初学者可能会问：工作区模式为何不直接运行三条 Git Diff 再拼接？**
> `git diff HEAD` 已同时覆盖索引区（staged）和工作树（unstaged）相对 `HEAD` 的净变化，重复拼接
> staged/unstaged Diff 反而可能造成重复。只有无首个 Commit、`HEAD` 不存在时才回退
> `git diff --staged`；未跟踪文件通过 `git ls-files --others --exclude-standard` 单列并构造
> “从 `/dev/null` 新增文件”的 Unified Diff（`internal/diff/git.go:267-337`）。若读取某个未跟踪文件
> 失败，当前实现会跳过该文件而不是中止整次 Review（`internal/diff/git.go:289-294`）。

三个模式的参数互斥在访问 Git 前就会校验：`--commit` 不能与 Range 同用，`--from` 与 `--to`
必须成对出现；无二者即 Workspace。`--resume` 又只支持 Commit 或 Range，因为工作区内容会持续
变化，源码明确拒绝 Workspace Resume（`cmd/opencodereview/flags.go:152-171`；
`cmd/opencodereview/review_cmd.go:157-180`）。

---

## 3. Diff 获取、解析与完整文件上下文

**Unified Diff（统一差异格式）** 是把文件变化编码为普通文本的约定。最小例子如下：

```diff
--- a/app.go
+++ b/app.go
@@ -10,3 +10,3 @@
 keep()
-oldCall()
+newCall()
 return
```

`---`/`+++` 指向旧文件和新文件；`-` 是删除行，`+` 是新增行，行首空格是未改动的上下文。
`@@ -10,3 +10,3 @@` 开始一个 **Hunk（变更块）**：旧侧从第 10 行取 3 行，新侧也从第 10 行
取 3 行。一个文件可有多个相距很远的 Hunk。OCR 另有 `ParseHunks()` 将 Hunk 头解析成
`OldStart/OldCount/NewStart/NewCount`，并把内容行分类为 Context/Added/Deleted；文件头和
`\ No newline at end of file` 元数据不当作代码（`internal/diff/hunk.go:9-37,42-109`；
`internal/diff/hunk_test.go:7-108`）。

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

这里的“上下文三行”不是只允许审查变更前后三行，而是 Git 在每个变更块两侧各附带最多三行
未改代码，帮助解析器和模型定位；相邻变化足够近时会合并成一个 Hunk。限制 Diff 体积可以节省
Prompt Token，但局部片段未必能说明函数、类型或调用链，因此 OCR 还保留变更后完整文件内容，
两者用途不同。

### 3.2 文件级 Diff 解析

`internal/diff/parser.go:25` 的 `ParseDiffText()` 将 Unified Diff 转换为 `model.Diff`，主要记录：

- 旧路径和新路径；
- 原始 Diff；
- 新增和删除行数；
- 新建、删除、重命名、二进制状态；
- 变更后完整文件内容。

解析器通过 `@@` 标记维护 `inHunk` 状态，仅在 Hunk 内统计 `+` 和 `-`，避免把 `--- a/file`、`+++ b/file` 误判为删除和新增代码。

特殊文件状态的处理不是依赖扩展名猜测，而是读取 Git Diff 元数据：

- 新文件的旧路径是 `/dev/null`，删除文件的新路径是 `/dev/null`；删除文件不再读取不存在的
  新版本，也不会派发逐文件 LLM 子任务（`internal/diff/parser.go:65-103,112-115`；
  `internal/agent/agent.go:350-378`；`internal/diff/parser_test.go:70-131`）。
- `--find-renames` 让 Git 发出 `rename from` / `rename to`；解析器保留旧、新路径并设置
  `IsRenamed`，后续以**新路径**读取内容、应用过滤和命中 Rule。即使 100% 相似的纯重命名没有
  Hunk，也仍可识别（`internal/diff/parser.go:82-95`；`internal/diff/parser_test.go:8-68`；
  `internal/diff/git_test.go:381-443`）。
- Git 对二进制变更发出行首为 `Binary files ... differ` 的标记；解析器设置 `IsBinary`，Agent
  随后首先排除它。正则锚定行首，所以文本 Hunk 中新增一句 `Binary files ...` 不会误伤
  （`internal/diff/parser.go:17-23,74-76`；`internal/agent/preview.go:31-34`；
  `internal/diff/parser_test.go:133-170`）。
- Workspace 的未跟踪文件被合成为“`/dev/null → 新路径`”的新文件 Diff，全部内容都以 `+`
  开头，而不是仅保留 `-U3`；空文件的 Hunk 行数为 0。文件读取失败会跳过，且读取函数会阻止
  绝对路径、目录、路径穿越和指向仓库外的父级符号链接（`internal/diff/git.go:283-318`；
  `internal/diff/workspace_file.go:11-59`；`internal/diff/workspace_file_test.go:10-134`）。

对于 Commit/Range 模式，变更后的完整文件内容通过以下命令读取：

```bash
git show <ref>:<path>
```

而不是读取当前工作区，因此审查内容始终与目标 Ref 一致。Workspace 模式则读取磁盘上的当前文件。

这里有两条相互独立但保持同一版本的完整上下文通道：Parser 把目标版本内容写入
`Diff.NewFileContent`，而 `file_read` 工具按需读取整个文件或指定行窗口；Commit 使用 commit，Range
使用 `to`，Workspace 使用磁盘。删除文件没有新内容；读取失败只打印警告并留下空内容，而不是让
整份 Diff 解析失败（`internal/model/diff.go:3-15`；`internal/diff/parser.go:105-141`；
`internal/tool/filereader.go:18-77,115-146`）。这项设计很重要：三行上下文适合控制 Token，却不足以
理解完整函数；完整内容还能供评论行号从 Hunk 定位失败时回退搜索（`internal/diff/resolver_test.go:92-229`）。

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

这些是**仓库根相对路径前缀**；Provider 解析 Diff 后以新路径过滤，删除文件则改用旧路径
（`internal/diff/git.go:241-255`）。同时读取项目根目录 `.gitignore`，忽略空行和注释。这里的
`.gitignore` 匹配是轻量实现，并非完整复刻 Git 的所有语义：尾随 `/` 按任意同名路径段匹配，
不含 `/` 的模式匹配 basename，含 `/` 的模式用 `filepath.Match` 匹配完整相对路径并尝试字面后缀；
`!` 否定规则被直接忽略，因此不能用它重新纳入先前排除的文件（`internal/diff/git.go:168-239`；
`internal/diff/gitignore_test.go:32-109`）。Workspace 枚举未跟踪文件时，Git 自己先通过
`git ls-files --others --exclude-standard` 应用标准忽略规则，Provider 再做上述过滤
（`internal/diff/git.go:321-337`）。

> **为什么还需要下一层过滤？** Provider 层处理的是“根本不进入解析结果”的仓库目录和
> `.gitignore` 噪声；它不知道哪些语言值得交给模型，也不负责用户 Review 偏好。职责不同，不能把
> 两层笼统理解为同一份 ignore 列表。

### 4.2 Agent 层过滤

Agent 的判定顺序是：二进制 → 用户 `exclude` → 命中的用户 `include` → 支持的扩展名 → 默认路径
规则（`internal/agent/preview.go:29-56`；`internal/agent/preview_test.go:10-405`）。因此：

- `exclude` 优先于 `include`，同一文件二者都命中时仍排除；
- `include` 是“显式放行”而非“唯一白名单”：命中时可绕过扩展名和默认路径排除，未命中仍继续
  常规检查，并不会仅因存在 include 就被排除；
- 重命名按新路径匹配；删除文件以旧路径作为有效路径；
- 二进制一定先排除。

Rule 配置中的 include/exclude 也不是把所有层简单拼接：只采用第一个实际配置过滤条件的高优先级
层，顺序为 CLI `--rule` 文件、项目规则、全局规则（`internal/config/rules/system_rules.go:237-310`）。
Agent 最终在 `internal/agent/agent.go:832-859` 应用这些结果。

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
这里的“所有”是 **Provider 过滤后、Agent 过滤前** 的全部 Diff：已被固定目录或 `.gitignore`
挡在 Provider 层的文件不会进入 DiffMap；纯删除文件的 `NewPath` 是 `/dev/null`，也不会写入该 Map
（`internal/agent/agent.go:302-345`）。

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

**Rule Resolver（规则解析器）** 的输入是一个文件路径，输出是最终注入该文件 Prompt 的规则文本。
实际逐文件审查把新路径转为小写后调用它；没有 Resolver 时返回空规则
（`internal/agent/agent.go:534-540,782-789`）。命中过程可拆成两级：

1. 按 `--rule` → 项目 → 全局 → 内置系统规则逐层查找；每层内部都按声明顺序查找，**第一个匹配
   即停止**。因此 `internal/**/*.go` 若写在更具体的 `internal/config/**/*.go` 前面，后者永远不会
   命中同一个文件（`internal/config/rules/system_rules.go:237-249,369-447`；
   `internal/config/rules/system_rules_test.go:130-150,273-301`）。
2. 系统规则同样 first-match-wins；没有路径规则命中才回退 `default_rule`。它使用
   `doublestar.Match` 支持 `**`，先把 `*.{go,py}` 展开成两个模式，并做大小写不敏感匹配
   （`internal/config/rules/system_rules.go:123-177`；`internal/config/rules/system_rules_test.go:10-211`）。

内置 `path_rule_map` 是 JSON 对象，而 Go 普通 map 不保证迭代顺序；实现用流式 JSON Decoder 把键
读入有序 `[]PathRule`，否则“第一个匹配”会随机化。默认配置也刻意把更具体的 GitHub Workflow
YAML 规则放在通用 YAML 规则之前（`internal/config/rules/system_rules.go:20-80`；
`internal/config/rules/system_rules.json:3-25`）。例如 `.github/workflows/ci.yml` 先命中
`.github/workflows/**/*.{yaml,yml}`，不会落入后面的 `**/*.{yaml,yml}`。

用户规则的 `rule` 既可直接写文本，也可写 `.md`、`.txt`、`.markdown` 文件路径；相对路径以相应
规则文件所在目录（项目规则以仓库根）解析。读取时限制扩展名和 512 KiB，检查路径穿越并解析
符号链接；不可安全读取时清空该条规则并警告（`internal/config/rules/system_rules.go:334-365,450-557`；
`internal/config/rules/system_rules_test.go:972-1358`）。

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

Plan 阶段只制定计划，不真正执行工具。这里容易产生一个误解：Plan Prompt 虽然会把可用工具的名称、说明和参数格式化为文本，但 `executePlanPhase()` 发出的 `ChatRequest` 并没有携带 `Tools` 字段，所以 Plan 只能建议 Main 稍后调用什么工具，不能在这一阶段读取文件或搜索代码。它的文本结果随后作为 `{{plan_guidance}}` 注入 Main Task；没有结果时，连同空的“Review Plan”标题一起移除。实现见 `internal/agent/agent.go:876-925` 和 `internal/agent/agent.go:568-589`。

默认情况下，改动少于 `PLAN_MODE_LINE_THRESHOLD=50` 行时跳过 Plan，以省下一次 LLM 请求；Plan 调用失败也不会中止 Review，而是记录事件并让 Main 在没有计划的情况下继续（`internal/agent/agent.go:541-560`）。因此两阶段的分工是：

- **Plan（先想路线）**：一次性阅读 Diff，输出结构化风险清单和调查建议；不执行工具、不产出最终评论。
- **Main（沿路线查证）**：拿到 Diff、可选计划和真正可调用的工具，多轮读取真实仓库，确认问题并提交评论。

为什么不把它们合成一次调用？小改动确实可以直接进入 Main；但对较大改动，先规划能让后续有限的工具预算优先查高风险路径。更重要的是，即使有 Plan，Main 仍不能只调用一次 LLM：初始 Prompt 只有 Diff 和元数据，不一定含完整函数、调用方或配置定义；模型需要“先决定读什么，再看到读取结果，再据此决定下一步”，后一个决定依赖前一个结果，天然是串行反馈循环。

---

## 8. Main Task：LLM 工具调用循环

主循环实现于 `internal/llmloop/loop.go:143-268` 的 `RunPerFile()`。这里的 **Tool Call（工具调用）** 是模型返回的一段结构化请求，包含工具名和 JSON 参数；它不是模型自己访问磁盘。OCR 进程收到请求后才在本地执行工具，再把结果作为 `role=tool` 消息交回模型。

首次请求的 System/User 消息由模板渲染而来，包含当前文件路径与 Diff、其他变更文件列表、当前时间、需求背景、匹配到的 Review Checklist，以及可选 Plan Guidance（`internal/agent/agent.go:568-590`）。请求还单独携带 Main 可用工具的 JSON Schema；后续请求则再带上此前完整会话历史和工具结果（`internal/llmloop/loop.go:169-180`）。

### 8.1 为什么模型能读到“真实代码”

模型不会直接打开仓库，也不能仅凭 Tool Schema 读文件。工具链分为两个必须同时存在的部分：

1. **Tool Definition / JSON Schema** 告诉模型“可以调用什么、参数怎么写”，主要来自 `internal/config/toolsconfig/tools.json`；
2. **Provider** 是 OCR 本地进程中的实际执行器，实现 `Execute(ctx, args)`，可以在配置的仓库目录中读文件、搜索代码或收集评论；Provider 保存在 `tool.Registry`（`internal/tool/definitions.go:66-103`）。

Agent 启动时注册内置 Provider，MCP Provider 也在此时动态加入；DiffMap 注入完成后 Registry 被 `Freeze()`，运行期只读，避免并发审查时改变工具映射（`cmd/opencodereview/review_cmd.go:315-322`、`internal/agent/agent.go:202-205`）。循环执行每个 Tool Call 时按名称查 Registry、解析 JSON 参数并调用 Provider；未知名称、参数错误和执行错误都会转换成文本结果返回模型，而不是让模型“假装成功”（`internal/llmloop/loop.go:274-329`、`411-429`）。

### 8.2 一轮最小消息—工具往返

以下示例省略了真实 Prompt 的大段文字，但保留协议角色和因果关系：

```text
第 1 次 LLM 请求
  system: 你是代码审查 Agent；上下文不足时先用工具……
  user:   当前文件 cache.go；这里是 Diff……
  tools:  file_read(file_path, start_line, end_line), code_comment(...), task_done(state)

第 1 次 LLM 响应
  assistant.tool_calls:
    [{id:"call_1", name:"file_read",
      arguments:{"file_path":"cache.go","start_line":80,"end_line":140}}]

OCR 本地执行
  Registry["file_read"].Execute(...) -> 返回第 80～140 行真实文件内容

第 2 次 LLM 请求
  system:  ...原消息...
  user:    ...原 Diff...
  assistant.tool_calls: ...call_1...
  tool (tool_call_id="call_1"): "80: func load(...) ..."
  tools:   ...同一组定义...

第 2 次 LLM 响应
  assistant.tool_calls:
    [{id:"call_2", name:"code_comment", arguments:{...}}]
```

关键点是 `call_1` 的结果会由 `NewToolResultMessage()` 追加到 `messages`，下一次 `CompletionsWithCtx()` 又发送整个 `messages` 列表（`internal/llmloop/loop.go:456-464`）。因此模型第二轮不是凭空记住结果，而是 API 请求显式带回了结果。提交评论后模型还可以继续搜索；确认已充分检查且没有更多问题时，才调用 `task_done`。

### 8.3 内置工具

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

模型显式声明当前文件已经审查完毕。它是 Main 的**正常成功终止协议**，不是普通文本答案：`executeToolCall()` 直接把它转换为 Completed checkpoint，`RunPerFile()` 只有看到该 checkpoint 才返回 `true`（`internal/llmloop/loop.go:309-311`、`218-245`）。可以先调用零到多个 `code_comment`，最后再调用 `task_done`；没有问题时也应直接调用它。

Schema 要求 `state` 为 `DONE` 或 `FAILED`，但当前执行器识别到工具名后，在解析参数之前就直接 `Complete()`，并未读取 `state`。也就是说，从当前实现看，`task_done({"state":"FAILED"})` 仍会被计作成功完成；判断真实终态应以代码路径而非 Schema 文案为准。这是工具契约与执行语义之间值得注意的不一致（`internal/config/toolsconfig/tools.json` 的 `task_done` 定义；`internal/llmloop/loop.go:309-311`）。

### 8.4 正常完成与保护性停止不是一回事

循环还有多层保险，避免模型或外部服务让单文件永远运行：

- **本轮没有 Tool Call**：追加一条 User 纠正消息，请模型重试或在完成时调用 `task_done`，然后进入下一次 LLM 请求（`internal/llmloop/loop.go:205-211`）。这类轮次会消耗工具请求预算，但不计入“连续空工具结果”计数。
- **有 Tool Call，但没有任何非空有效结果**：把错误文本作为 Tool Result 回传；连续 3 轮仍为空则停止（`internal/llmloop/loop.go:214-255`）。注意执行错误通常本身是非空错误文本，因此会让模型有机会纠正参数。
- **达到调用预算**：每次发 LLM 请求前预算减一，默认 `MAX_TOOL_REQUEST_TIMES=30`；耗尽后返回 `false`，不是成功完成（`internal/llmloop/loop.go:150-168`、`264-267`，默认值见 `internal/config/template/task_template.json`）。
- **上下文仍过长**：80% 阈值处同步压缩；压缩后仍超限则停止，详见第 13 节。
- **LLM 请求报错或 Context 被取消**：立即返回 error；单文件调度 Context 默认由 CLI 的 `--timeout 10` 分钟限制，超时只使该文件失败，其他并发文件继续（`internal/agent/agent.go:372-420`、`cmd/opencodereview/flags.go:134`）。底层 LLM Client 还可有独立 HTTP 请求超时。

`task_template.json` 虽然为 Main、Plan、Memory Compression 声明了 120、180、120 秒的 `timeout` 字段，但当前这三条执行路径没有用这些字段创建子 Context；不能把它们误解为当前生效的阶段级硬超时。当前明确使用任务模板 Timeout 的是 Review Filter 和 Re-location，而 Plan/Main/压缩主要受上层单文件 Context 与 LLM Client 请求超时约束（用法对照 `internal/agent/agent.go:668-683`、`internal/diff/relocation.go:33-35`）。

所有“未显式 `task_done`”的停止最终都会让 `executeSubtask()` 得到 `mainCompleted=false`，文件被记录为 `main_task did not complete before stopping`；这能防止被迫截断被伪装为成功（`internal/agent/agent.go:606-635`）。

### 8.5 MCP 扩展

**MCP（Model Context Protocol，模型上下文协议）** 是外部进程向 Agent 统一暴露工具定义和调用接口的协议，不是另一种 Prompt，也不是把仓库自动上传给模型。OCR 按配置以 stdio 启动 MCP Server 子进程，完成 `Connect` 和 `ListTools`，把每个外部工具适配为同一个 `tool.Provider`；实际调用时再经 `CallTool` 把 JSON 参数发给该进程并取回文本结果（`internal/mcp/client.go:13-82`、`internal/mcp/provider.go:13-25`）。

成功发现且注册的 MCP Tool Definition 会同时追加到 Plan 和 Main：Plan 只看到其说明，用来规划；Main 才能产生真实 Tool Call。可配置 allowlist；与内置保留名或已注册工具重名时会告警并跳过，外部工具不能覆盖 `file_read`、`task_done` 等内置行为（`internal/mcp/provider.go:27-64`、`94-114`，`cmd/opencodereview/review_cmd.go:97-99`）。

初始化单个 MCP Server 的 Connect/ListTools 有 30 秒 Context；可选 setup 最多 5 分钟。setup 或启动失败通常只是告警并跳过该 Server，Review 继续使用其余工具（`cmd/opencodereview/review_cmd.go:263-311`）。因此 MCP 扩展了 OCR 可查证的世界，例如静态分析、知识库或内部服务，但其结果和内置工具一样，仍必须作为 Tool Result 进入下一轮，模型才看得到。

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

## 13. 上下文压缩、Token 与缓存统计

**Token** 是模型计费和上下文容量使用的文本单位，不等同于字符或单词。多轮工具调用会反复携带原 Prompt、Assistant Tool Calls 和 Tool Results，历史越长，每次请求的输入越大。OCR 因此在 `internal/llmloop/compression.go` 和 `internal/llmloop/loop.go:432-484` 实现三分区压缩。

### 13.1 三个分区怎样压缩

消息被按完整的“一个 Assistant 消息 + 紧随其后的所有 Tool Result”组成 **round（轮次）**，避免留下没有对应结果的半个 Tool Call。然后分为：

1. **Frozen Zone**：最前面的两条 System/User 初始消息，始终保留；
2. **Compress Zone**：较老的完整轮次，交给独立的 Memory Compression LLM 请求生成摘要；
3. **Active Zone**：在预算内能容纳的最近若干完整轮次，逐字保留。

重建后的历史是“前两条初始消息（摘要附加到第 2 条 User 消息）+ 最近活跃轮次”，实现见 `internal/llmloop/compression.go:74-153`、`205-270`。

阈值策略为：

- 超过 `MAX_TOKENS` 的 60% 但尚未到 80%：基于当前消息快照启动异步后台压缩，尽量不阻塞主循环；
- 达到 80%：取消待处理后台任务并立即同步压缩；
- 同步压缩后仍达到 80%：`addNextMessage()` 返回 `false`，当前文件保护性停止，不能算 `task_done` 成功；
- 调度前若单个 Diff 自身的估算 Token 已超过 80%，先过滤该文件；若全部被过滤，Review 返回 `all diffs filtered out by token size`。即使 Diff 没超限，渲染后的 Main Prompt（还包含规则、计划等）超过 80% 也会在进入 Tool Loop 前跳过该文件（`internal/agent/agent.go:357-361`、`592-603`）。

压缩状态归属于单文件会话而非共享 Runner；文件结束时取消仍在运行的任务，避免并发文件互相应用或取消摘要（`internal/llmloop/compression.go:45-61`、`273-287`）。

### 13.2 压缩会丢掉什么

压缩是有损的：老 Tool Result 的逐字代码、精确行号、搜索结果顺序、失败参数和中间推理不会原样保留，只剩压缩模型认为重要的事实。因此摘要可能漏掉细节或引入概括偏差。OCR 的缓解方式是保留初始 Prompt 和最近完整轮次，并要求按完整 round 切割；但如果后续判断必须依赖旧结果的原文，模型可能需要再次调用工具。

失败时不会用空摘要替换历史：压缩请求报错或返回空内容都会保留原消息，防止为了降 Token 直接丢失全部上下文（`internal/llmloop/compression.go:237-256`）。代价是历史可能仍在 80% 以上，重试压缩后仍无法降下去就停止该文件。

### 13.3 估算 Token 与 API Usage 不是同一个数

阈值判断使用本地 tokenizer 对每条消息的文本做粗略估算；默认按 `cl100k_base`，`o1/o3/o4` 模型名使用 `o200k_base`，加载失败时退化为“字节数 / 4”（`internal/llm/client.go:260-288`、`internal/llmloop/compression.go:63-71`）。这个估算没有完整计算 API 包装和 Tool Schema 开销，所以是保护性近似值，不应当成账单。

运行统计则取自每次 LLM 响应的 `usage`：分别累计 Input/Prompt、Output/Completion、Cache Read 和 Cache Write Token；Main、Plan、压缩、重定位和过滤等 OCR 自己发出的模型请求都会在相应路径计入 Runner（例如 `internal/llmloop/loop.go:190-197`、`compression.go:244-250`、`internal/agent/agent.go:916-923`）。若 Provider 没返回 usage，OCR 无法凭本地估算补齐真实计费统计。

这里的 **Cache Read/Write Token** 是 LLM Provider 在响应 Usage 中报告的 Prompt Cache 指标。OCR 只是兼容解析 Anthropic、OpenAI Responses 及部分代理的字段并累加（`internal/llm/usage_resolver.go:35-60`）；它不表示 OCR 缓存了模型答案，也不同于第 14 节基于 Fingerprint 的 Resume 结果复用。不同 Provider 对 Cache Token 是否已包含在 Prompt/Total Token 中定义不同，`resolveUsage()` 只在缺少 Total 时按来源语义回算，以避免 OpenAI 风格缓存 Token 被重复相加（`internal/llm/usage_resolver.go:71-108`）。

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
