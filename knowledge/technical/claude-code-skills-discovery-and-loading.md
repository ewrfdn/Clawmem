# Claude Code Skills 的发现、加载、搜索与上下文注入

> 记录时间：2026-07-12  
> 来源：Claude Code 本地源码快照、官方文档与 Anthropic GitHub issue 的对照分析  
> 本地源码：`/home/azureuser/.openclaw/workspace/claude-code`  
> 适用范围：当前可见源码快照；Claude Code 核心实现并未完全开源，版本差异和内部服务实现需要保留不确定性。

## 0. 核心结论

Claude Code 的普通 skills 工作流可以概括为：

```text
发现 skill 文件
  ↓
解析成独立 Command
  ↓
生成 skill metadata listing
  ↓
以内部 meta user message + <system-reminder> 注入上下文
  ↓
模型根据 metadata 判断是否使用 skill
  ↓
模型调用通用 Skill tool
  ↓
本地 runtime 加载完整 SKILL.md
  ↓
inline：正文进入当前上下文
fork：正文进入独立 subagent
  ↓
模型依据完整 skill 继续执行
```

最重要的区分是：

```text
skill metadata ≠ 完整 SKILL.md
skill listing ≠ tools 数组中的 1000 个独立工具
skill search ≠ 已被当前公开源码完全证明的固定 top-K 语义检索
```

---

## 1. 一个 skill 在 Claude Code 中是什么

本地代码会把 skill 解析为独立的 `Command` 对象。多个 skills 不会先被编译或合并为一个新 skill：

```text
Skill A → 独立 Command
Skill B → 独立 Command
Skill C → 独立 Command
```

最终模型通常只看到一个通用的 `Skill` tool：

```text
Skill({ skill: string, args?: string })
```

不会因为存在 `pdf`、`testing`、`database` 三个 skills，就产生三个独立的 API tools：

```text
不是：PdfSkillTool、TestingSkillTool、DatabaseSkillTool
而是：一个 Skill tool + 一组可按名称加载的 skill commands
```

相关源码：

- `src/commands.ts`
- `src/tools/SkillTool/prompt.ts`
- `src/tools/SkillTool/SkillTool.ts`

---

## 2. 新会话如何发现 skills

当前源码会从多种来源建立 skill command 集合，主要包括：

```text
bundled skills
builtin plugin skills
managed skills
user skills
project .claude/skills
--add-dir 指定目录
legacy commands
plugin commands / plugin skills
MCP skills（单独的 loader/builder 路径）
```

普通目录的读取阶段可以并行进行，但合并后仍有确定的来源顺序。当前代码中普通 skills 目录大致按以下顺序合并：

```text
managed → user → project → additional → legacy
```

同一个 prompt skill 文件会通过 `getFileIdentity()` 做 resolved file identity 去重，规则是 order-dependent 的 first-wins。它能处理：

- 同一个文件通过多个路径出现
- symlink 指向相同文件
- 重复父目录扫描

但这不是完整的“按 skill 名称全局去重”。不同文件但同名时，最终通常由 command 数组顺序和 `findCommand()` 的 first-match 行为决定。

相关源码：

- `src/skills/loadSkillsDir.ts`
- `src/commands.ts`

### 文件读取与模型上下文读取不是一回事

启动时 runtime 可能已经从磁盘读取并解析了 `SKILL.md` 的 frontmatter、路径和描述，用于建立 command registry；这不代表完整正文已经进入模型上下文。

应区分：

```text
runtime 从磁盘读取文件
≠
完整 skill 正文注入 LLM prompt
```

---

## 3. metadata 什么时候进入模型上下文

普通模式下，Claude Code 会生成 `skill_listing` attachment。listing 主要包含：

```text
skill name
简短 description
调用 Skill tool 的提示
```

完整正文通常不在 listing 中。

当前源码对 listing 有预算控制：

```ts
SKILL_BUDGET_CONTEXT_PERCENT = 0.01
DEFAULT_CHAR_BUDGET = 8_000
MAX_LISTING_DESC_CHARS = 250
```

超过预算时，系统会：

```text
先尝试完整描述
  ↓
截短非 bundled skill 的描述
  ↓
极端情况下只保留非 bundled skill 的名字
```

### metadata 不是直接进入 tools 数组

这点需要精确表述。`Skill` 工具本身会进入 API 的 `tools` 数组，但每个 skill 的 metadata 不会各自成为一个 tool definition。

`skill_listing` 被转换为：

```ts
createUserMessage({
  content: `The following skills are available for use with the Skill tool:\n\n${content}`,
  isMeta: true,
})
```

然后包裹为：

```text
<system-reminder>
The following skills are available for use with the Skill tool:

- testing: ...
- database: ...
</system-reminder>
```

所以它在语义上是系统自动附加的内部上下文，但从消息构造路径看，是 `isMeta: true` 的 user message，而不是 API 原生 `system` role。

相关源码：

- `src/utils/attachments.ts:2661-2751`
- `src/utils/messages.ts:3097-3133`
- `src/utils/messages.ts:3728-3738`

准确说法：

> skill metadata 通过内部 attachment 转为 meta user message，并用 `<system-reminder>` 表达系统级语义；它不直接进入 tools 数组，也不是普通 API `system` prompt 的一段原生 system message。

---

## 4. 普通 inline skill 的完整执行流程

### 4.1 用户任务进入第一轮模型调用

初始请求大致包含：

```text
system prompt
项目配置 / CLAUDE.md
用户请求
skill_listing metadata（若有）
通用 Skill tool schema
其他可用工具 schema
```

模型进行第一次 LLM 调用：

```text
LLM #1：判断任务是否需要某个 skill
```

如果不需要 skill，可以直接回答，或者调用普通工具。

### 4.2 模型调用通用 Skill tool

模型可能返回：

```json
{
  "name": "Skill",
  "input": {
    "skill": "testing"
  }
}
```

这一步只是模型选择了一个 skill。Skill tool 本身由本地 runtime 执行，通常不算一次新的 LLM 调用。

### 4.3 runtime 读取完整正文

inline 路径会执行类似：

```ts
command.getPromptForCommand(args, context)
```

随后处理：

- `$ARGUMENTS`
- `!command` 动态命令展开
- frontmatter 属性
- hooks
- 允许的工具
- skill 资源路径

然后把完整 skill 内容作为新的上下文消息返回。

### 4.4 第二轮模型调用

Skill tool 返回后，runtime 需要把新增消息交给模型：

```text
LLM #2：模型第一次真正依据完整 SKILL.md 工作
```

因此一个最简单的 inline skill 流程至少是：

```text
LLM #1：选择 skill
本地 Skill tool：加载完整正文
LLM #2：使用完整正文回答
```

如果之后还需要 Read、Edit、Bash 等普通工具，每一次工具结果后通常还会有新的 LLM 调用：

```text
LLM #2 → Read
工具结果
LLM #3 → Edit
工具结果
LLM #4 → 测试 / 最终总结
```

### 4.5 最少 LLM 调用次数

| 场景 | 最少 LLM 调用 |
|---|---:|
| 不使用 skill，直接回答 | 1 |
| 使用 inline skill，加载后直接回答 | 2 |
| inline skill 后再调用一个普通工具 | 至少 3 |
| 使用 fork skill | 主 agent 至少 2 + fork agent 至少 1 |
| 用户直接输入 `/skill-name` | 可能绕过模型选择阶段，具体取决于 slash command 路径 |

---

## 5. 同一个 skill 重复调用时会怎样

当前源码中可以看到 `invokedSkills` 状态，但它主要用于 compact 后恢复 skill 指令，不是一个通用的运行时正文缓存/去重门禁。

因此不能假设：

```text
第一次 Skill("testing") 后
第二次 Skill("testing") 会自动只返回一个引用
```

更安全的模型是：

```text
第一次调用 → 完整正文进入上下文
第二次调用 → 可能再次生成正文消息
```

`invokedSkills` 会按 agent 和 skill name 保存状态，后一次记录可能覆盖前一次记录；但它不会撤回已经进入对话的旧正文。

这会带来：

- token 消耗增加
- 上下文膨胀
- 更容易触发 compact
- 模型注意力分散

此前公开 issue 也报告过类似重复注入现象：

- `anthropics/claude-code#17140`
- `anthropics/claude-code#21891`（duplicate）

---

## 6. `context: fork` 与 inline 的区别

skill frontmatter 可以声明：

```yaml
context: fork
```

当前源码会把它解析为：

```ts
executionContext: 'fork'
```

执行时，Skill tool 不把完整正文直接追加到主 agent，而是：

```text
主 agent
  ↓ Skill tool
创建独立 subagent
  ↓
在独立上下文加载完整 SKILL.md
  ↓
独立执行工具和 LLM 调用
  ↓
提取结果
  ↓
把结果返回主 agent
```

fork skill 具有：

- 独立消息上下文
- 独立工具执行范围
- 独立 token budget
- 主上下文主要接收结果，而不是完整内部 transcript

nested fork 的上下文传播不能过度假设。公开 issue `anthropics/claude-code#17351` 报告过 nested skill + `context: fork` 的返回路径异常。

适合使用 fork 的场景：

- 大型代码扫描
- 安全审计
- 研究和资料汇总
- 不希望把大量中间结果污染主上下文的任务

---

## 7. 1000 个 skills 时，默认机制如何优化

如果有 1000 个 skills，默认 listing 路径不是把 1000 份完整 `SKILL.md` 全部塞入上下文，而是：

```text
读取/解析大量 skill 文件
  ↓
生成 metadata listing
  ↓
按照 listing budget 截短 description
  ↓
极端情况下，非 bundled skills 只保留名字
```

这解决了“完整正文一次性进入上下文”的问题，但不等于解决了“模型如何从 1000 个候选中选择”的问题。

默认机制目前明确提供：

- listing context budget
- description 截断
- 极端 names-only fallback
- 同一 agent 生命周期内避免重复发送已发送的 skill names
- resume 时避免重新发送 transcript 中已有的 listing

`sentSkillNames` 逻辑位于 `src/utils/attachments.ts`：

```text
第一次：发送初始 listing
后续：只发送还没发送过的新 skills
没有新增：不发送新的 listing
```

这是“避免重复发送”的优化，不是“首次从 1000 个里做语义 top-K”的保证。

### 默认路径的缺点

如果没有启用 skill search，1000 个 skill 仍可能造成：

- 初始 listing 很大
- 描述被压缩到难以判断
- 只剩名字后，模型选择困难
- 相似命名产生歧义
- metadata token 成本和注意力成本上升

---

## 8. skill search / discovery 的优化路径

当前源码有 feature-gated 的实验性路径：

```ts
feature('EXPERIMENTAL_SKILL_SEARCH')
```

启用后，初始静态 listing 不再无差别展示所有长尾 skills，而是优先保留：

```text
bundled skills
MCP skills
```

用户、项目和插件 skills 被视为长尾，交给后续 discovery/search 按需发现。

源码中有一个静态 listing 保护阈值：

```ts
FILTERED_LISTING_MAX = 30
```

它的真实含义是：

```text
bundled + MCP 合计不超过 30：保留两类
超过 30：退化为只保留 bundled
```

这不是搜索结果 top 30，也不是所有 skill 的全局 top-K。

### discovery 结果如何进入上下文

`skill_discovery` attachment 最终会被格式化为：

```text
Skills relevant to your task:

- skill-a: ...
- skill-b: ...
- skill-c: ...

These skills encode project-specific conventions.
Invoke via Skill("<name>") for complete instructions.
```

然后同样通过 `isMeta: true` 的 user message 和 `<system-reminder>` 注入。

相关源码：

- `src/utils/attachments.ts`
- `src/utils/messages.ts:3503-3519`
- `src/query.ts` 中的 prefetched skill discovery 采集逻辑

---

## 9. search 命中多个 skills 时，是否排序、取多少个

这是当前分析中必须保留边界的部分。

### 能确认的事实

`skill_discovery` attachment 的结构是：

```ts
skills: {
  name: string
  description: string
  shortId?: string
}[]
```

注入时使用：

```ts
attachment.skills.map(s => `- ${s.name}: ${s.description}`)
```

这说明注入阶段：

- 不重新排序
- 不显式 `slice(0, N)`
- 直接使用 discovery 模块返回的数组顺序

### 不能从当前可见源码确认的事实

目前不能严谨地声称：

```text
search 结果固定按相关性排序
search 结果固定取 top 3 / top 5 / top 10
所有版本都使用相同的 ranking 算法
```

排序和截取如果存在，可能发生在 feature-gated 的 skill search / prefetch 模块或内部搜索服务中；当前源码快照中这些模块的完整实现不可见，不能据此编造具体 top-K。

### 不要混淆的两个数字

#### `top 5`

`src/utils/suggestions/commandSuggestions.ts` 中确实有：

```ts
// Take top 5 recently used skills
```

但它属于用户输入 `/` 时的命令补全建议，排序依据是 skill 使用频率和最近使用时间，不是任务语义相关性。

#### `FILTERED_LISTING_MAX = 30`

这是初始 bundled/MCP 静态 listing 的保护阈值，不是 discovery 搜索结果 top 30。

### 最严谨的结论

> skill search 会根据用户输入发现相关 skills，并把搜索模块返回的候选数组注入上下文。当前公开可见的注入代码不负责排序或截断，也没有证明固定 top-K；实际 ranking 和数量上限需要查看完整的 skill search 实现或对应内部服务。

---

## 10. Agent 显式预加载与 CLI 自动发现不同

Agent definition / Agent SDK 可以显式配置：

```yaml
skills:
  - database
  - testing
  - security
```

这条路径不是：

```text
metadata listing → 模型选择 → Skill tool
```

而是：

```text
agent 启动
  ↓
解析指定 skills
  ↓
并行调用 getPromptForCommand()
  ↓
完整正文加入 agent 初始 messages
  ↓
第一次 agent LLM 调用时已经看到正文
```

因此：

```text
CLI 普通模式：metadata → 模型选择 → 按需加载正文
Agent 显式预加载：配置指定 → 启动时加载完整正文 → LLM
```

当前源码没有明显证明 `agentDefinition.skills` 会按名称做全局去重；重复配置相同 skill 需要避免。

---

## 11. 推荐的 1000-skill 设计方案

### 11.1 优先启用 skill search / discovery

如果当前版本和运行环境支持，优先采用：

```text
少量高价值 skills 静态展示
长尾 skills 按任务动态发现
```

但 `EXPERIMENTAL_SKILL_SEARCH` 是 feature-gated；源码中存在不等于所有部署默认启用。

### 11.2 分层而不是平铺

不推荐：

```text
1000 个 skill 直接平铺
```

推荐：

```text
frontend
  ├── react
  ├── css
  ├── accessibility
  └── component-testing
backend
  ├── api
  ├── database
  └── queues
infra
  ├── docker
  ├── kubernetes
  └── terraform
```

可以让少量领域入口 skill 做路由，再决定是否调用叶子 skill。

### 11.3 metadata 写成检索标签，不写成教程

不推荐：

```text
migration-helper: database stuff
```

推荐：

```text
 db-migration-review: 审查 SQL schema migration；修改表结构、索引或数据迁移脚本时使用
```

metadata 应包含：

```text
领域 + 触发条件 + 主要产出
```

但不要把完整流程塞入 description。

### 11.4 保持 SKILL.md 短小

把大型资料拆到：

```text
references/
examples/
templates/
scripts/
```

`SKILL.md` 只保留：

- 什么时候使用
- 核心执行步骤
- 必要边界条件
- 需要读取哪些 reference
- 输入和输出约定

### 11.5 减少重叠和同名

合并高度重叠的 skills，采用命名空间，并保留 canonical skill。避免让模型在这些相似项之间选择：

```text
react-testing
react-test
react-test-helper
frontend-testing
component-testing
```

### 11.6 大型探索任务考虑 `context: fork`

把大型扫描、审计、研究任务放到独立上下文，减少主 agent 的中间结果污染；主 agent 只接收总结结果。

---

## 12. 证据等级与未确认边界

### 当前源码直接证明

- skills 是独立 command，不自动合并
- 普通 skills 有多来源加载和 resolved file identity 去重
- listing 有预算、描述截断和 names-only fallback
- metadata 以 meta user message + `<system-reminder>` 注入
- 通用 `Skill` tool 负责按名称加载正文
- inline/fork 是不同执行路径
- 同一 agent 会抑制重复 listing 发送
- skill search feature 会过滤初始 bundled/MCP listing
- `FILTERED_LISTING_MAX` 当前为 30
- discovery 注入阶段直接使用返回数组顺序

### 公开 issue / 官方资料反映

- 某些版本或场景下重复 skill 调用可能造成正文重复注入：`#17140`、`#21891`
- nested fork skill 的上下文返回路径存在已报告异常：`#17351`
- Agent SDK 支持显式预加载多个 skills

### 当前不能确认

- 所有版本的具体排序算法
- skill search 是否始终使用语义相关性排序
- discovery 的固定 top-K 数值
- 私有/feature-gated search 后端的完整实现
- 所有部署是否默认开启 `EXPERIMENTAL_SKILL_SEARCH`
- 不同发行版本是否具有完全相同的 listing 和 discovery 行为

---

## 13. 一句话记忆卡

> Claude Code 的 skills 采用渐进式披露：runtime 可以先读取并索引大量 skill 文件，但模型通常先看到受预算限制的 metadata listing；listing 通过内部 meta user message 和 `<system-reminder>` 注入，而不是把每个 skill 放进 tools 数组。模型选择后，通用 Skill tool 才加载完整 SKILL.md。面对 1000 个 skills，默认机制主要靠预算截断和避免重复发送；实验性的 skill search 会把长尾 skills 延迟到 discovery，但当前公开源码不能证明统一的排序算法或固定 top-K。

## 参考

- Claude Code 官方 Skills 文档：<https://code.claude.com/docs/en/skills>
- Agent SDK Subagents 文档：<https://code.claude.com/docs/en/agent-sdk/subagents>
- 重复 skill 内容：<https://github.com/anthropics/claude-code/issues/17140>
- 相关 duplicate：<https://github.com/anthropics/claude-code/issues/21891>
- nested fork skill：<https://github.com/anthropics/claude-code/issues/17351>
- 本地源码关键路径：
  - `src/skills/loadSkillsDir.ts`
  - `src/commands.ts`
  - `src/tools/SkillTool/prompt.ts`
  - `src/tools/SkillTool/SkillTool.ts`
  - `src/utils/attachments.ts`
  - `src/utils/messages.ts`
  - `src/query.ts`
  - `src/tools/AgentTool/runAgent.ts`
