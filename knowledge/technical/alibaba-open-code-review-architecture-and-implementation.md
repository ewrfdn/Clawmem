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

`dispatchSubtasks()` 位于 `internal/agent/agent.go:350-450`。它以**文件审查子任务**为并发单位，用有界 channel 作 Semaphore；`MaxConcurrency <= 0` 时实现取 8。因而“并发 8”是最多同时有 8 个文件执行各自的 Plan、Main Tool Loop 和收尾，**不是**最多 8 次 LLM 请求，也不是 Git 或评论后处理的全局上限。评论 Re-location 另有 WorkerPool（第 11 节），Git 子进程还共享一把默认容量 16、等待可被 context 取消的 Semaphore（`internal/llmloop/pool.go:24-57`；`internal/gitcmd/runner.go:11-38`）。

每个文件拥有独立 Prompt、Plan 结果、LLM Tool Loop、`FileSession`、超时和检查点状态，目的是把上下文、成本与故障域限制在一个文件。最小状态转换可写成：

```text
待调度（仅内存中，尚无 checkpoint）
  ├─ Resume 命中 ─────────────→ review_item_reused（恢复评论，不发 LLM 请求）
  └─ 启动 goroutine → Plan/Main/Filter
                         ├─ 明确 task_done → review_item_done（评论可为空）
                         └─ error / panic / 保护性停止 → review_item_failed
```

这里并不存在一个可任意跳转的 `enum` 状态机；可恢复状态就是 JSONL 中三类终态记录。删除文件直接跳过，不创建这三类检查点；Prompt 超阈值或 Main 未调用 `task_done` 也记为 `failed`，不能伪装成可复用成功（`internal/agent/agent.go:374-447,453-500,592-635`；`internal/agent/agent_test.go:595-727`）。

普通 error 与 panic 都在文件 goroutine 内转成失败记录和 warning；panic 还会 `recover` 并打印堆栈，所以其他文件继续。只有**返回 error 或 panic** 的数量等于已调度文件数时，整体才返回 `all N file review(s) failed`；保护性停止虽写 `review_item_failed`，当前实现不增加这个汇总计数，全部这样停止时未必返回整体错误。这是“检查点失败”和“进程级失败”的重要边界（`internal/agent/agent.go:387-447`；`internal/agent/coverage_test.go:634-656`）。

文件超时 `ConcurrentTaskTimeout` 以分钟计，0 表示不设置；context 在取得文件 Semaphore、进入 goroutine后才创建，覆盖 Plan、Main、工具调用以及 Review Filter 所收到的父 context（`internal/agent/agent.go:93-97,371-413,521-636`）。但它不是硬杀死：排队等待文件槽位的时间不计入，底层 LLM/工具必须合作响应 context；`CommentWorkerPool.AwaitKey()` 本身也没有 context 分支，若后台工作不返回，等待仍可能超过期限（`internal/llmloop/loop.go:274-306`；`internal/llmloop/pool.go:132-147`）。另外模板 `LlmConversation.Timeout` 目前只在 Re-location 被读取并按秒建立更短 context；Plan/Main 的同名字段未在其调用路径消费，不能把它当成阶段级超时（`internal/diff/relocation.go:20-54`；`internal/agent/agent.go:876-906`）。

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

提交结构化 Review Comment。真实 Tool Schema 的顶层不是一条评论，而是 `comments` 数组；一次调用可提交多条：

```json
{
  "comments": [
    {
      "content": "忽略 Load 返回的错误会让后续逻辑使用不完整配置。",
      "existing_code": "cfg, _ := Load(path)",
      "suggestion_code": "cfg, err := Load(path)\nif err != nil { return err }",
      "category": "bug",
      "severity": "high"
    }
  ]
}
```

这里的 `existing_code` 是**变更中已经存在、用于锚定评论的原代码片段**，不是建议如何修改；建议代码另放在可选的 `suggestion_code`。Schema 要求每项都有 `content`、`existing_code`、`category`、`severity`，并明确要求锚点只取新增代码，不包含删除行或未改上下文。执行器还兼容 `comments` 是 JSON 字符串的情况；缺少该字段、空数组或字符串不是合法 JSON 时，错误文本会作为 Tool Result 返回给模型修正。单项不是对象、运行时参数没有顶层 `path`，或单项缺少 `content`，都会被跳过（`internal/config/toolsconfig/tools.json:28-93`；`internal/tool/code_comment.go:34-87`；`internal/tool/code_comment_test.go`）。

初学者可能会问：**既然 GitHub 最后需要行号，为什么不让模型直接输出行号？** 因为 Prompt 中的 Diff 行号、完整文件行号与 PR Head 的新侧坐标不是同一个概念，模型复制或心算很容易受 Hunk、删除行和多轮上下文影响。源码文本比裸数字更容易校验和重新定位，所以模型只表达“问题是什么”和“问题贴在哪段现有代码”，程序再把稳定的文本锚点换算成 `StartLine/EndLine`。另外，模型不能选择目标文件：`executeToolCall()` 会把当前 `newPath` 强制写入顶层 `path`，`ParseComments()` 再把它复制到数组内每条 `LlmComment`，避免幻觉路径把评论贴到其他文件（`internal/llmloop/loop.go:320-374`；`internal/model/review.go:3-18`）。

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

## 10. 从 `existing_code` 到 GitHub 行号

模型提交 `code_comment` 后，执行器先解析数组并注入当前文件路径，再对每条评论调用 `ResolveComment()`；项目最终汇总时还会调用批量入口 `ResolveLineNumbers()` 补做一次解析。两者都不会覆盖已有正行号，也不会凭空处理空 `existing_code`（`internal/llmloop/loop.go:337-375`；`internal/diff/resolver.go:9-69`；`cmd/opencodereview/shared.go:270-277`）。

### 10.1 最小例子：JSON 如何变成 `11..11`

假设当前文件是 `app.go`，Diff 为：

```diff
@@ -10,2 +10,3 @@
 func run() error {
+    cfg, _ := Load(path)
     return use(cfg)
```

上一节 JSON 中的数组项被解析为：

```text
LlmComment{
  Path: "app.go",                         // 执行器注入，不由模型决定
  ExistingCode: "cfg, _ := Load(path)",
  StartLine: 0, EndLine: 0,
  ...
}
```

Resolver 从 Hunk 头得到新侧从第 10 行开始：上下文 `func run()` 是第 10 行，新增锚点是第 11 行，因而写入 `StartLine=11, EndLine=11`。发布层随后生成 `{path:"app.go", line:11, side:"RIGHT"}`。若 `existing_code` 是连续两行，则写入首、末行，GitHub 参数改为 `start_line`、`line`，两端都使用 `RIGHT`（`internal/diff/resolver.go:78-165`；`scripts/github-actions/post-review-comments.js:119-147`）。

### 10.2 Hunk、新旧侧与多行定位

`resolveFromHunk()` 会把每个 Hunk 拆成两个可搜索序列：

- **新侧**：Context + Added，携带新文件行号；
- **旧侧**：Context + Deleted，携带旧文件行号。

它先逐个 Hunk 在新侧做连续滑动窗口匹配，全部失败后才搜索旧侧。每行会 Trim 空白并去掉一个开头的 `+`/`-` Diff 标记；`existing_code` 中的空行会被丢弃，但 Hunk 侧的空行仍占一个窗口位置。因此 Hunk 阶段的多行锚点必须在同一侧的归一化行序列中真正连续，不能跨空行匹配。跨空行匹配是下一节“完整新文件回退”才提供的能力。测试覆盖单行删除侧 `11..11`、两行删除侧 `6..7`，以及完整文件回退时的空行与 CRLF 映射（`internal/diff/resolver.go:72-165,216-237`；`internal/diff/resolver_test.go:18-90,120-190`）。

这里有一个必须区分的**能力边界**：Resolver 的算法确实能算出删除行的旧侧坐标，但 `LlmComment` 没有记录 LEFT/RIGHT 的字段，GitHub 发布脚本又固定发送 `side:"RIGHT"` / `start_side:"RIGHT"`。因此当前端到端契约只可靠支持新侧锚点，Schema 和 Main Prompt 才明确禁止评论删除代码，并要求 `existing_code` 只含新增行。上下文行在 Resolver 中可映射到新侧，但同样不是 Schema 鼓励模型主动选择的锚点。不能仅因单元测试证明旧侧能“算出数字”，就推断删除行一定能正确发布为 Inline Comment（`internal/config/toolsconfig/tools.json:47-50`；`internal/model/review.go:3-18`；`scripts/github-actions/post-review-comments.js:135-146`）。

### 10.3 完整新文件回退、重复片段与关键边界

若所有 Hunk 都未命中，Resolver 扫描 `NewFileContent`。这里的“连续”是相邻**非空**行：空白行不参与比较，但返回范围使用原文件行号，所以 `func foo()` 与 `return` 中间有空行时，范围仍可能是 `3..6`。这可以定位 Hunk 三行上下文之外的新文件代码，但也意味着锚点不一定是 GitHub Diff 中可评论的行，最终 API 可能拒绝并进入发布降级（`internal/diff/resolver.go:167-213`；`internal/diff/resolver_test.go:92-190`）。

重复片段没有语义消歧：算法按 Hunk 顺序、窗口顺序返回第一个匹配；完整文件回退也明确是 first match wins。最实用的规避方式是让 `existing_code` 带上足够短但唯一的相邻新增行，而不是只给常见的 `return nil`。空锚点、全空白、路径找不到或完全不匹配时，行号保持 `0..0`；已有任一正行号时则直接保留，不再重算（`internal/diff/resolver_test.go:193-269`；`internal/diff/relocation_test.go:72-97`）。

### 10.4 LLM Re-location：修锚点，不复核结论

初学者可能会问：**第一次已经是 LLM 生成的，定位失败为何还找第二个 LLM？** 主审模型的职责多，可能把 `existing_code` 抄成近似文本、带入说明或选得太宽；Re-location 是一个更窄的修复任务，只接收当前 Diff、评论内容和原锚点，并要求从 Diff 提取准确代码块。它不是让模型直接猜新行号：只有返回第一个 fenced code block，程序才用该代码块再次运行同一个确定性 `ResolveComment()`。成功才替换锚点并保留新行号；再次匹配失败会恢复原 `existing_code`，行号仍为零（`internal/diff/relocation.go:16-80,83-102`；`internal/diff/relocation_test.go:99-194`）。

Re-location 与 Review Filter 解决的是正交问题：前者回答“这条评论应贴在哪里”，不判断评论是否正确；后者回答“这条评论是否被当前 Diff 明确证伪”，不修改锚点。Re-location 请求使用自己模板的 Timeout，并独立记录 Session、Telemetry 和 Token；请求错误、无 fenced code block 或二次匹配失败都只是定位失败，原评论仍会进入 Collector，而不是在此阶段删除（`internal/llmloop/loop.go:353-374`；`internal/diff/relocation.go:33-80`）。

完整定位链可以读成：

```text
comments[] → 注入当前 path → ParseComments → LlmComment(0..0)
                                      ↓
                         Hunk 新侧 → Hunk 旧侧
                                      ↓ 仍失败
                           完整新文件首个匹配
                                      ↓ 仍失败且已配置
                 Re-location 提取代码块 → 再跑同一 Resolver
                                      ↓
                       成功：正行号；失败：保留 0..0
```

---

## 11. `CommentCollector` 与异步 WorkerPool

`CommentCollector` 是每个 Agent 自己持有的线程安全评论仓库；`Add()`、`Comments()` 和 `CommentsForPath()` 都用互斥锁保护，并返回副本，避免多个文件并行审查时共享切片竞争。它不仅是“最终结果列表”，也是主循环与异步定位、Filter 之间的交接点（`internal/tool/comment_collector.go:9-48`）。

为什么异步？一次 `code_comment` 可能触发额外的 Re-location LLM 网络请求。如果主 Tool Loop 原地等待，模型无法继续搜索或审查该文件。配置 WorkerPool 后，`ParseComments()` 仍同步完成，以便把参数错误立即反馈给模型；耗时的 Resolve/Re-location/Collect 才提交后台。池用有界 semaphore 控制并发（非法或零配置默认 8），主循环立刻得到成功 Tool Result 并继续（`internal/llmloop/loop.go:333-397`；`internal/llmloop/pool.go:24-109`；`internal/llmloop/pool_test.go:14-123`）。

异步不等于“不等待”。Main Loop 结束后，Agent 先调用 `AwaitKey(newPath)`，确认该文件此前提交的所有评论已经进入 Collector，再运行 Review Filter；它不会调用全池 `Await()`，因为其他文件可能仍在 Submit，混用全局 WaitGroup 会产生竞态。按 key 等待只阻塞当前文件，测试专门覆盖了“其他 key 仍并发提交”场景（`internal/agent/agent.go:618-629`；`internal/llmloop/pool.go:132-147`；`internal/llmloop/pool_test.go:126-240`）。

失败语义需要说清：

- `comments` 参数非法：本次不入 Collector，错误 Tool Result 让模型有机会重试；
- 确定性定位和 Re-location 都失败：评论照常入 Collector，只是保持 `0..0`，稍后走 Summary；
- Worker 单元 panic：池会 recover 并记录日志，未执行到 `Add()` 的评论不会出现；等待 API 只等待完成、不返回该错误，因此它们也没有机会进入 Summary。普通 Review 路径提交的闭包本身总是返回 nil error；
- Re-location 网络失败：记录失败 Session 后仍执行 `Add()`，所以评论保留。

这一区分避免把“后处理失败降级”误写成所有异常都无损；panic 隔离保护了进程，却可能损失该工作单元尚未收集的评论（`internal/llmloop/pool.go:87-119`；`internal/llmloop/loop.go:346-394`）。

Collector 还有 `Snapshot()`、`Since()`、`ReplaceSince()`：它们不是 PR Review 流程的隐式同批去重，而是 **Scan 模式**按批次隔离新增评论、等待异步工作后运行可选 LLM Dedup，再只替换该批区间。Dedup 请求失败、JSON/分组非法时保留原批评论；`ReplaceSince()` 对负数按 0 处理，越界按约定 no-op（`internal/tool/comment_collector.go:50-89`；`internal/tool/comment_collector_test.go`；`internal/scan/agent.go:380-425,694-751`）。

---

## 12. Review Filter：保守地删除明确误报

Review Filter 在“当前文件 Worker 已排空”之后、文件任务返回之前执行。输入是当前 Diff 和 Collector 中该路径的全部评论，程序为它们生成稳定的临时 ID `c-0`、`c-1`；模型只能返回待删除 ID 数组，例如 `["c-0", "c-3"]`，程序再按该路径内的索引调用 `RemoveByPathAndIndices()`（`internal/agent/agent.go:618-629,639-710`；`internal/tool/comment_collector.go:91-113`）。

它的 Prompt 有意保守：**只有当前 Diff 自身就能清楚证明评论在事实或逻辑上错误时才删除**；若需要 Diff 之外的信息、存在歧义，或主 Agent 可能通过工具看到更多上下文，都必须保留。它不重写评论、不修行号，也不按严重度打分。这正是它与 Re-location 的边界：Filter 是正确性闸门，Re-location 是位置修复器（`internal/config/template/prompts/review_filter_system_prompt.txt`；`internal/config/template/prompts/review_filter_user_prompt.txt`）。

失败默认偏向“不漏报”：未配置任务、没有评论、LLM 请求错误/超时、响应不是可解析数组、ID 非法或越界时，不删除对应评论；只有解析出的有效 ID 才会移除。测试还验证重复 ID 会合并、合法与非法 ID 混合时只采用合法项（`internal/agent/agent.go:646-710,746-789`；`internal/agent/coverage_test.go`）。

评论在这一段生命周期中的状态因此是：Filter 明确选中 → 从 Collector 删除且不会发布；Filter 无法判断或自身失败 → 保留。它与后面的发布去重也不同：Filter 删除的是“已证伪的问题”，发布层 Incremental 去重跳过的是“历史上已经覆盖的代码范围”，不代表问题判断错误。

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

运行级统计则取自每次 LLM 响应的 `usage`：Runner 用原子计数跨并发文件累计 Input/Prompt、Output/Completion、Cache Read 和 Cache Write Token；Main、Plan、压缩、Re-location 和 Filter 等 OCR 自己发出的模型请求都在各自路径调用同一套累加逻辑，最终进入文本/JSON 结果，供调用者或 CI 看本次运行成本（`internal/llmloop/loop.go:119-131,190-197`；`internal/llmloop/compression.go:244-250`；`internal/agent/agent.go:270-287,916-923`；`cmd/opencodereview/output.go:238-260`）。若 Provider 不返回 usage，Runner 不累加，因而运行汇总不能冒充真实账单。

Session 记录与运行汇总在缺失 usage 时有一个容易忽略的差异：`TaskRecord.SetResponse()` 会用本地 tokenizer 估算该请求的 Prompt/Completion 并写入 JSONL，但 Cache Read/Write 保持 0；这只是便于逐请求诊断的近似值，并不会回填 Runner 汇总（`internal/session/history.go:276-328`）。所以看到 Session 有 token 数、最终 JSON 汇总却为 0 并不矛盾，表示供应商未给可聚合的 Usage。

这里的 **Cache Read/Write Token** 是 LLM Provider 在响应 Usage 中报告的 Prompt Cache 指标。OCR 只是兼容解析 Anthropic、OpenAI Responses 及部分代理的字段并累加（`internal/llm/usage_resolver.go:35-60`）；它不表示 OCR 缓存了模型答案，也不同于第 14 节基于 Fingerprint 的 Resume 结果复用。不同 Provider 对 Cache Token 是否已包含在 Prompt/Total Token 中定义不同，`resolveUsage()` 只在缺少 Total 时按来源语义回算，以避免 OpenAI 风格缓存 Token 被重复相加（`internal/llm/usage_resolver.go:71-108`）。

---

## 14. Session、断点恢复与可观测性

### 14.1 Session 保存什么、何时落盘

`SessionHistory` 是一次 Review 的并发安全运行容器：顶层保存 Session ID、仓库/分支/模型、Review 与 Diff 范围、恢复来源、起止时间、LLM 失败数；其下按路径建立 `FileSession`，再按 Plan、Main、Memory Compression、Re-location、Review Filter 分类保存请求消息、响应、Tool Result、Token 和耗时（`internal/session/history.go:16-88,99-152,221-365`）。这既提供逐请求诊断记录，也承载 Resume 所需的文件终态。

新建 Session 就创建：

```text
$HOME/.opencodereview/sessions/<编码后的仓库绝对路径>/<session-id>.jsonl
```

目录和文件权限分别为 `0700`、`0600`。记录用 `uuid`/`parentUuid` 串成写入链：创建时写 `session_start`；每次请求、响应、错误和 Tool Result 随执行追加；文件结束写 `review_item_done|failed|reused` 并立即 `Flush()`；`Agent.Run()` 正常返回前 `Finalize()` 写 `session_end`、flush 并 close（`internal/session/persist.go:70-128,130-213,215-340`；`internal/agent/agent.go:189-235`）。因此它不是结束时才一次性导出的报告；文件检查点落盘后，即使后续文件失败，也有机会恢复。

边界也要明确：普通 LLM 记录写入缓冲区，不是每条都 flush；创建 writer 失败只打印 warning，Marshal/Write/Flush/Close 错误也没有向 Review 主流程传播。进程被强杀时，尾部缓冲记录或 `session_end` 可能缺失；但已 flush 的文件检查点仍可被逐行重放。JSONL 还包含完整 Prompt、模型响应、工具参数/结果和评论，不受 Telemetry 开关控制，可能含源码或业务上下文，需按敏感运行日志管理（`internal/session/history.go:125-131`；`internal/session/persist.go:120-128,181-213,215-340`）。

### 14.2 Fingerprint / Resume 如何判定可复用

文件 Fingerprint 是下列四段以 `NUL` 分隔后做 SHA-256：

```text
Review Mode + Old Path + New Path + 原始 Diff 文本
```

实现位于 `internal/agent/agent.go:509-511`。恢复前先校验 Review Mode 和对应 Diff 范围（range 的 from/to、commit 的 commit）；不兼容就拒绝加载。随后只把旧 JSONL 的 `review_item_done` 和 `review_item_reused` 建入 fingerprint 索引，`review_item_failed` 不可复用（`internal/session/resume.go:67-95,114-161`；`internal/session/persist_test.go:274-344`）。

最小场景：首次审查 `a.go` 成功、`b.go` 因 API 错误失败；第二次用该 Session 恢复，若 `a.go` 的四段输入相同，就把旧评论放回 Collector，在新 Session 写一条带 `sourceSessionId` 的 `review_item_reused`；`b.go` 因无成功索引项重新走 Plan/Main。若 `a.go` 的路径或 Diff 改变，fingerprint miss，也重新审查（`internal/agent/agent.go:453-500`）。

这个键**不包含模型、规则文件、Prompt 模板、背景说明、工具配置或 OCR 版本**。测试明确允许旧 Anthropic 模型结果被新 OpenAI 模型运行复用（`internal/agent/agent_test.go:446-485`）。所以“代码没变”只说明代码侧命中：模型或规则改变时仍会复用旧评论，不会自动失效。需要让新策略重新判断时，应不使用该 Resume Session（或另起一次完整 Review），而不能把 Fingerprint 当成语义缓存键。

### 14.3 Telemetry 给谁看、发送到哪里

Telemetry 面向运行者、CI/平台维护者和接收 OTLP 的可观测系统，用于回答“哪一阶段慢、哪类请求失败、调用了多少工具、消耗多少 Token”。它默认关闭，只有 `OCR_ENABLE_TELEMETRY=1` 才初始化；默认 exporter 是本地 console，配置 `OCR_OTLP_ENDPOINT` 后改用 OTLP，并可通过 `OCR_OTLP_PROTOCOL` 选 `grpc` 或 `http`。CLI 退出时最多用 5 秒 shutdown（`internal/telemetry/config.go:11-50`；`internal/telemetry/provider.go:19-68`；`cmd/opencodereview/main.go:15-27`）。

开启后，代码建立 Review/Diff/Plan/Main/LLM/Tool/Re-location/Filter 等 Span，并记录 Review 时长、文件数、评论数、LLM 请求次数/耗时/总 Token、工具调用次数/耗时与错误事件；指标 API 在未启用或记录失败时直接返回，不让观测故障中断 Review，属于 best-effort（`internal/telemetry/metrics.go:16-208`；`internal/telemetry/events.go:13-45`；`internal/telemetry/span.go:10-75`）。属性会包含模型名、工具名、错误、文件路径、仓库目录等元数据，配置外部 OTLP 前仍需评估隐私。

`OCR_TELEMETRY_LOG_CONTENT` 虽被配置层解析并保存在 Provider，但当前源码没有调用 `ContentLogging()` 来把 Prompt/Response 内容写入 Telemetry；因此不能承诺打开它就会导出正文（`internal/telemetry/config.go:23-48`；`internal/telemetry/provider.go:69-81`）。反过来，关闭此开关也不会阻止前述 Session JSONL 保存正文。Token 指标同样只接受 Provider Usage 的 `TotalTokens`；供应商不返回 Usage 时该次 Telemetry Token 为 0，不能据此断言请求没有成本（例如 `internal/agent/agent.go:901-923`）。

---

## 15. GitHub Action 发布流程

GitHub Action 是仓库中可复用的复合 Action，入口为 `action.yml`。先定义两个容易混淆的 PR 术语：**Base** 是 PR 准备合入的目标分支（例如 `main`），**Head** 是贡献者提交所在分支的最新 Commit；**Merge Base** 是 Base 与 Head 最近的共同祖先。审查 `Merge Base..Head`，关注的正是这个 PR 相对共同起点引入的改动，而不是 Base 后续新增但 PR 尚未合并的变化。

### 15.1 为什么取 Head 的对象，却不 Checkout Head

仓库示例使用 `pull_request_target`，因为它在目标仓库的 Base 上下文运行，可读取 LLM Secret，并给 `GITHUB_TOKEN` 写 PR 评论的能力。这个触发器权限较高，所以关键安全边界是：工作流和 Action 来自可信 Base，工作树也 Checkout Base；随后只用 `git fetch origin "pull/<PR>/head"` 取得 Head 的 Git Objects，让 `ocr` 能读取 Blob 和 Diff，但**不把 Head 物化为当前工作树，更不运行其中的脚本、构建步骤或安装清单**。因此恶意 PR 不能仅靠修改自身 workflow、`package.json` 等文件让本次高权限 Job 执行这些改动（`.github/workflows/ocr-review.yml:24-49`；`action.yml:167-207`）。

这不是“PR 内容完全可信”或“绝对安全”：Head 的源码和 Diff 仍会被解析并发送给配置的 LLM，可能包含敏感内容或提示注入文本；`ocr`、外部 Action 与 LLM 服务本身仍属于供应链/出站信任面。`ocr_version` 默认还是 `latest`，示例远程 Action 使用 `@main`，生产环境若重视可复现性，应固定经过审核的版本或 Commit。若自行扩展 workflow，也不能在 `pull_request_target` 下对 Head 做 Checkout 后执行测试、安装依赖或运行 PR 提供的命令（`action.yml:49-52,182-215`；`examples/github_actions/ocr-review.yml:56-68,113-119`）。此外，Base Fetch 失败被 `|| true` 忽略，Merge Base 算不出时会回退为 Head 自身；此时 `Head..Head` 很可能表现成无改动而不是显式报错，是可用性上的保守失败盲点，不应误读为“确实没有问题”（`action.yml:201-207`）。

**最小权限是什么？** 示例显式给 `contents: read`（Checkout、Fetch Base/Head）和 `pull-requests: write`（读取 PR 上下文并创建 Review/Inline/PR Summary）；`github_token` 默认取 `${{ github.token }}`。LLM 凭据另外以 Secrets 传入，不应写入仓库。评论触发的重审还先限制为非 Bot 且 `MEMBER/OWNER/COLLABORATOR`，避免任意外部评论消耗 LLM 配额。权限不足时 Review 或 Summary API 会失败，发布器不会神奇地绕过仓库/分支/组织策略（`action.yml:45-48`；`examples/github_actions/ocr-review.yml:65-68,73-93`）。

### 15.2 CLI JSON 怎样变成网页上的 Inline 与 Summary

Action 计算 Merge Base 后执行：

```bash
ocr review --from "${MERGE_BASE}" --to "${HEAD_SHA}" --format json
```

stdout 保存为 `/tmp/ocr-result.json`，stderr 单独保存；非零退出码时可先上传两者为 Artifact，然后 Job 失败，不进入评论发布。成功时 `actions/github-script` 加载 `scripts/github-actions/post-review-comments.js`（`action.yml:227-305`）。CLI JSON 顶层包含 `status/message/summary/tool_calls/comments/warnings/...`；每个 `comments[]` 的输出模型包含 `path`、`content`、`start_line`、`end_line`，并可带 `existing_code`、`suggestion_code`、`category`、`severity`。发布器用路径与行号定位、用 `content` 生成正文；只有 `existing_code` 与 `suggestion_code` 同时存在时才追加 GitHub suggestion/Before-After 块，当前发布格式不展示 `category/severity`（`cmd/opencodereview/output.go:225-317`；`internal/model/review.go:3-17`；`scripts/github-actions/post-review-comments.js:1013-1044`）。

转换规则如下：

1. `start_line`、`end_line` 至少一个为正，才尝试 **Inline Comment**（挂在 Files changed 的具体路径/行上）；单行发送 `line + side: RIGHT`，多行发送 `start_line + line + start_side/side: RIGHT`，并绑定当前 PR Head SHA。
2. 两个行号都无效时，不猜位置，而把原评论和 `No line information provided` 原因放进 **Summary**（PR 会话中的普通 Issue Comment）。
3. 有合法行号但 GitHub 因 Diff 已变化、该行不在可评论范围等返回 422 时，逐条发布仍失败，原评论及 API 错误也进入 Summary。
4. `warnings` 和“无发现/跳过”等状态同样写进 Summary；Action 还输出 `comments_total/inline/skipped/failed` 与 `summary_comment_url`，供后续 Step 判断（`action.yml:103-118`；`scripts/github-actions/post-review-comments.js:75-165,411-466`）。

这里的 `RIGHT` 指 Diff 的新侧。因此第 10 节所述定位即使能找到旧侧删除行，当前发布层也没有构造 `LEFT` 评论；“内部保留了发现”不等于“一定能挂到 GitHub 行内”。

### 15.3 一次 PR 运行的时序，以及失败怎样降级

以“3 条发现：A 可定位、B 无行号、C 行号已过期”为例：

1. `pull_request_target` 在可信 Base workflow 中启动，解析 Base/Head，Checkout Base、Fetch Head Objects，计算 Merge Base。
2. `ocr` 读取 `Merge Base..Head` 并输出 JSON；A/C 进入待发 Inline，B 进入 Summary-only 集合。
3. 发布器先创建或找到一个 **Summary Anchor**（占位 Summary），再提交一次 `pulls.createReview` 批量发布 A/C。先放 Anchor 是为了让首次运行的 Summary 在 PR 时间线上位于 Review 之前，最终统计出来后再原地更新（`scripts/github-actions/post-review-comments.js:167-213,508-594`）。
4. 若批量成功，A/C 都显示在代码行旁，Summary 解释 B。若批量因一条坏位置整体失败，脚本降级为逐条 `createReview`：A 成功；C 的 422 属于不可重试错误，于是 C 连同原因进入 Summary。最终 Summary 显示 Inline=1、Summary(no line)=1、Failed=1。
5. 若 GitHub 的 Summary 读取不可用，脚本无法确认 Anchor 是否已存在时会暂缓创建；Finalize 再读仍失败则返回空 Summary URL，避免盲目制造重复。若 Summary 的创建/更新写请求本身失败，该异常仍可能使发布 Step 失败。故“失败评论会进入 Summary”是正常降级路径，不是 GitHub API 整体故障时的交付保证（`scripts/github-actions/post-review-comments.js:414-458,533-594`；`scripts/github-actions/post-review-comments.test.js:422-459,703-742`）。

### 15.4 Sticky、Incremental、历史去重分别解决什么

- **Sticky Summary（默认开启）**：用隐藏标记 `<!-- ocr-summary -->` 查找这个 Bot 先前的 Summary，后续运行更新同一条，而不是让每次重审都新增一条总览。关闭后每次 Run 有自己的 Summary，但同一 Run 的重试仍按 run tag 复用，解决的是“总览刷屏/时间线位置”，不控制 Inline。
- **Incremental（默认关闭）**：重审时只追加未被历史 Bot Inline 覆盖的新位置，且不删除旧评论。它解决 synchronize/re-run 时重复轰炸同一片代码的问题。路径必须相同且历史侧为 `RIGHT`；单行只按同一行判断，单行与多行永不互相去重，多行才按行区间 IoU 严格大于阈值判断，默认阈值 `0.6`。它不比较正文，所以同一位置的新结论也可能被跳过；若历史读取失败则降级为空历史，可能重新发布。历史查询只取最新优先的最多 1,000 条，超大 PR 也可能漏掉更老覆盖（`action.yml:69-89`；`scripts/github-actions/post-review-comments.js:596-713`）。
- **历史评论去重**在这里特指 Incremental 的“位置重叠过滤”，不要与模型当前批次去重或网络重试幂等混为一谈。普通 PR Review 不会把同批 `path + line + content` 相同的两条折叠；随机 ID 正是为了保留它们作为两个发现。只有 Scan 模式可选的 LLM Dedup 才处理当前扫描批次的近重复内容。

### 15.5 重试会不会重复发评论

发布器首先尝试一批 Review；失败后最多按默认 3 次重试配置逐条发送，并根据 `Retry-After`、`x-ratelimit-reset` 或指数退避等待。429/明确限流视为请求未落地，可等待后重试；5xx、408、网络断开则存在“GitHub 已创建，但客户端没收到响应”的不确定性（`scripts/github-actions/post-review-comments.js:201-405,746-813`）。

为降低重复风险，批 Review 带 `runId-runAttempt` 隐藏 tag，每条 Inline 带同一 Run 内随机且稳定的隐藏 ID。遇到可能已落地的错误时，脚本先列出现有 Reviews/Review Comments：找到 ID 就计为成功，只补缺失项；逐条检查读失败时返回“未知”，宁可把该项记为失败，也不再次发送（`scripts/github-actions/post-review-comments.js:54-65,934-1008`）。

但这只是 **best-effort 幂等**，不是 exactly-once：

- 批量请求可能已落地，而“查询批 Review”本身最终失败时，当前实现明确降级为逐条发送全部评论，接受重复风险；
- 幂等查询最多读取 50×100 条，ID 若落在截断之外会被误判为未发布；
- Incremental 历史读取失败或超过 1,000 条上限，也可能漏掉旧位置；
- Sticky 只去重 Summary，Incremental 只去重历史位置，都不能替代传输幂等。

测试覆盖了批量部分落地后只补缺失项、逐条 5xx 已落地不重复、读 API 未知时停止重试、429 后恢复、422 转 Summary，以及批幂等读取失败时接受重复风险等分支（`scripts/github-actions/post-review-comments.test.js:573-668,862-1168`）。

### 15.6 从模型发现到 GitHub 最终状态

把发布层放回整条链路后，“内部保留评论”和“最终显示为 Inline”不是同一保证：

| 阶段 | 条件 | 结果 |
|---|---|---|
| `ParseComments` | `comments` 缺失/为空/JSON 非法 | 本次不收集，错误 Tool Result 可回传模型 |
| `ParseComments` | 单项非对象、缺少运行时 `path` 或 `content` | 该单项静默跳过，其他合法项继续 |
| Resolver/Re-location | 都定位失败 | 评论保留为 `0..0` |
| Review Filter | 当前 Diff 可明确证伪且返回有效 ID | 从 Collector 删除且不发布 |
| Review Filter | 不确定、报错或超时 | 评论保留 |
| GitHub 分流 | 无正行号 | 带原因进入 Summary |
| Incremental | 与历史范围重叠 | 跳过新 Inline，计入 `skipped` |
| Inline API | 最终发布失败 | 带 API 错误进入 Summary |
| Summary API | 无法安全 upsert | 不冒险重复创建，Summary URL 为空 |

因此最终结果可能是 Inline、Summary、Incremental Skip、Filter 删除或可观察的发布失败；“OCR 找到了问题”本身不承诺 GitHub 一定展示一条行内评论。

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
| `code_comment` 解析 | `internal/tool/code_comment.go:34` |
| Comment Collector | `internal/tool/comment_collector.go:9` |
| 评论行号定位 | `internal/diff/resolver.go:57` |
| LLM Re-location | `internal/diff/relocation.go:16` |
| LLM Tool Loop | `internal/llmloop/loop.go:143` |
| Tool Call 分发 | `internal/llmloop/loop.go:270` |
| Comment 异步定位 | `internal/llmloop/loop.go:333` |
| Comment WorkerPool | `internal/llmloop/pool.go:24` |
| 上下文压缩 | `internal/llmloop/compression.go` |
| Session 内存模型与 Token 记录 | `internal/session/history.go` |
| Session JSONL 持久化 | `internal/session/persist.go` |
| Resume 加载与兼容校验 | `internal/session/resume.go` |
| Telemetry 配置与 Provider | `internal/telemetry/config.go`、`provider.go` |
| Telemetry 指标与事件 | `internal/telemetry/metrics.go`、`events.go` |
| 工具 Schema | `internal/config/toolsconfig/tools.json` |
| Prompt | `internal/config/template/prompts/` |
| Rule Resolver | `internal/config/rules/system_rules.go:252` |
| GitHub Action | `action.yml` |
| CLI JSON 输出模型 | `cmd/opencodereview/output.go:225`、`internal/model/review.go:3` |
| PR 评论发布 | `scripts/github-actions/post-review-comments.js` |
| PR 发布测试 | `scripts/github-actions/post-review-comments.test.js` |
| GitHub Workflow 示例 | `examples/github_actions/ocr-review.yml` |

## 20. 验证说明

本报告基于 Commit `3355baea0e83b3be7653e6f422c83242541f77c0` 的实际源码调用链整理，不仅依据 README。分析时源码仓库状态干净。此前轮次已交叉阅读 `internal/tool`、`internal/diff`、`internal/llmloop`、`internal/agent`、`internal/session`、`internal/telemetry` 及对应 Go 测试；本轮又逐项核对 `action.yml`、GitHub Workflow 示例、CLI JSON 输出模型、`scripts/github-actions/post-review-comments.js` 及其测试，并重新运行 `npm run test:github-actions`：评论发布与翻译同步两组 JavaScript 测试全部通过。当前分析环境未安装 Go，无法执行 `go test ./...`（`go: command not found`），因此 Go 侧结论来自只读源码与测试用例交叉核对，而非本机执行结果。
