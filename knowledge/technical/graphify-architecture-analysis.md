# Graphify 架构分析（v3）

> 仓库：`safishamsi/graphify`
> 分支：`v3`
> 本文基于 README.zh-CN、ARCHITECTURE.md 和核心源码模块逐个阅读整理。

## 一句话总结

Graphify 本质上是一个 **“代码/文档/论文/图片 → 统一知识图谱”** 的本地流水线工具。

它不是传统的向量 RAG，也不是单纯的代码 AST 分析器，而是把两条提取链路合并到同一张图里：

1. **代码文件**：用 tree-sitter 做确定性 AST 提取，不走 LLM
2. **文档/论文/图片**：走语义提取（由外部 AI coding assistant / 模型完成）
3. **合并后**：用 NetworkX 建图，再用 Leiden/Louvain 做社区发现，最后导出 report / html / json / wiki / graphml / neo4j 等多种表示

也就是说，它的核心卖点不是“检索原文”，而是先把原始材料**编译成图结构**，之后围绕图结构做理解、导航和查询。

---

## 1. 整体流水线

官方 `ARCHITECTURE.md` 给出的主流程是：

```text
detect()  →  extract()  →  build_graph()  →  cluster()  →  analyze()  →  report()  →  export()
```

对应模块职责如下：

| 阶段 | 模块 | 作用 |
|---|---|---|
| 文件发现 | `detect.py` | 扫描目录、过滤文件、判断类型 |
| 提取 | `extract.py` | 从代码 AST 或语义内容中抽取 nodes + edges |
| 建图 | `build.py` | 合并抽取结果，构建 NetworkX 图 |
| 聚类 | `cluster.py` | Leiden / Louvain 社区发现 |
| 分析 | `analyze.py` | 找 god nodes、surprising connections、问题建议 |
| 报告 | `report.py` | 生成 `GRAPH_REPORT.md` |
| 导出 | `export.py` | 输出 `graph.json` / `graph.html` / `svg` / `wiki` / `graphml` 等 |

这个设计非常清晰：**每一步一个模块、一个主函数、数据结构简单（dict + NetworkX graph）**，耦合度低，方便扩展。

---

## 2. 它是怎么“提取”的

### 2.1 代码文件：纯本地 AST 提取

Graphify 对代码文件的处理不依赖 LLM，而是依赖 `tree-sitter` 语法树。

在 `pyproject.toml` 里，它直接声明了一大串语言依赖：

- Python
- JavaScript / TypeScript
- Go
- Rust
- Java
- C / C++
- Ruby
- C#
- Kotlin
- Scala
- PHP
- Swift
- Lua
- Zig
- PowerShell
- Elixir
- Objective-C

核心模块是 `graphify/extract.py`。

它的思路是：

1. 为每种语言定义一个 `LanguageConfig`
2. 配置这门语言的：
   - class 节点类型
   - function 节点类型
   - import 节点类型
   - call 节点类型
   - 名字字段 / body 字段 / 特殊 handler
3. 用统一的 `_extract_generic(path, config)` 驱动解析
4. 输出标准化的 `nodes` / `edges`

也就是说，它没有为每门语言写一套完全独立逻辑，而是用了一个 **“语言配置 + 通用抽取器”** 的框架。

这是实现上很漂亮的一点：

- 新增语言只需要加 `LanguageConfig` 和少量特殊处理
- 绝大部分结构抽取逻辑复用
- 测试面也更容易覆盖

### 2.2 AST 提取了什么

对于代码，Graphify 主要提取：

- 文件节点
- 类 / 接口 / 协议 节点
- 函数 / 方法 / 构造函数 节点
- import / imports_from 边
- contains / method 边
- inherits 边
- 调用关系（calls）

`extract.py` 里甚至有第二轮 **call-graph pass**，会在收集完函数 body 后再跑一遍调用图解析，用于补全函数之间的调用关系。

所以它不是“只提目录结构”，而是抽取了**结构层 + 调用层**的图。

### 2.3 文档/图片/论文：语义提取

README 说明得很直接：

- `.md/.txt/.rst` → 提取概念、关系、设计动机
- `.pdf` → 引文和概念提取
- `.png/.jpg/...` → 用 vision 模型从图表、截图、白板中提取概念关系

这部分并不在 AST 模块里，而是通过 skill / 外部 assistant orchestration 实现。

也就是说：

- **Graphify 库本身**负责图结构、导出、缓存、报告
- **Graphify skill/CLI**负责把“需要语义抽取的文件”交给 Claude Code / Codex / OpenClaw 等平台背后的模型

这也是它能同时支持 Claude Code / Codex / OpenCode / OpenClaw 的原因。

---

## 3. 统一的数据模型

Graphify 的一个核心设计是：**不管来源是什么，最后都落成统一 schema**。

`ARCHITECTURE.md` 里定义的 extraction schema 大概是：

```json
{
  "nodes": [
    {
      "id": "unique_string",
      "label": "human name",
      "source_file": "path",
      "source_location": "L42"
    }
  ],
  "edges": [
    {
      "source": "id_a",
      "target": "id_b",
      "relation": "calls|imports|uses|...",
      "confidence": "EXTRACTED|INFERRED|AMBIGUOUS"
    }
  ]
}
```

此外 `validate.py` 会校验：

- 必填字段是否齐全
- confidence 是否合法
- file_type 是否合法
- edge 是否引用有效节点

这意味着 Graphify 的真正抽象层不是“代码解析器”或“文档问答器”，而是 **node-edge extraction engine**。

这非常关键，因为它让后面的聚类、分析、导出都与上游来源解耦。

---

## 4. 它如何处理“不确定性”

Graphify 有个很好的设计：**每条边都带置信类型**。

三种标签：

- `EXTRACTED`：源材料明确写了
- `INFERRED`：合理推断
- `AMBIGUOUS`：有歧义，需要人复核

这比很多 GraphRAG 系统“把模型猜测和事实混在一起”要靠谱很多。

因为它至少在数据层明确区分：

- 哪些是事实
- 哪些是推理
- 哪些只是可疑线索

`analyze.py` 里生成“surprising connections”时，还会基于 confidence 做排序：

- `AMBIGUOUS` > `INFERRED` > `EXTRACTED`

也就是说，它认为越不显然、越跨越结构边界的连接，越值得被人审查。

这是一个很像“研究助手”而不是“纯检索器”的思路。

---

## 5. 建图层：为什么用 NetworkX

Graphify 不是基于 Neo4j 起步的，而是以 **NetworkX 本地图** 为核心。

`build.py` 的做法非常直接：

1. 先 `validate_extraction`
2. 遍历所有 nodes `G.add_node(...)`
3. 遍历所有 edges `G.add_edge(...)`
4. 保留 `_src` / `_tgt` 字段，避免 undirected graph 丢失方向信息

它这里有几个实现细节值得注意：

### 5.1 图是无向图，但边保留原始方向

社区发现算法通常更适合在无向图上做，因此 Graphify 用的是 `nx.Graph()` 而不是 `DiGraph()`。

但它又不想丢掉语义方向，所以在 edge attr 里额外保存：

- `_src`
- `_tgt`

后续显示和报告时再恢复。

这是个务实的折中：

- 结构分析方便
- 语义展示仍保留方向

### 5.2 节点去重是三层机制

`build.py` 顶部注释写得很清楚：

1. **文件内**：extractor 用 `seen_ids` 去重
2. **文件间**：NetworkX 同 ID 节点后写覆盖前写
3. **语义合并层**：skill 先去重，再进入 build

这个设计说明作者很清楚图抽取里最容易爆炸的点：**重复实体**。

不过当前实现仍然偏“ID 相同才算同一实体”，没有特别复杂的实体对齐逻辑。所以它不是那种重度 entity resolution 系统，而是比较轻量、工程上可控的方案。

---

## 6. 社区发现：它为什么不需要 embedding

Graphify README 强调：**聚类不依赖 embedding**。

实现上它的确是这么做的：

- `cluster.py` 优先尝试 `graspologic.partition.leiden`
- 如果没装 graspologic，就退回 `networkx` 自带 Louvain

逻辑：

1. 图里已经存在各种结构边和语义边
2. Leiden/Louvain 根据图的边密度划分 community
3. 所以“相似性”体现在图结构里，而不是额外的向量空间

这其实是它最核心的哲学之一：

> 语义相似性不一定非要进 embedding DB，也可以先显式写成边，再做图拓扑分析。

如果语义抽取阶段已经产生了 `semantically_similar_to` 这类边，那么聚类时这些边自然会影响社区划分。

### 6.1 它还会拆分过大的社区

`cluster.py` 有两个参数：

- `_MAX_COMMUNITY_FRACTION = 0.25`
- `_MIN_SPLIT_SIZE = 10`

也就是：

- 如果某个 community 超过全图 25%
- 且至少 10 个节点

就会对子图再跑一次社区发现，继续拆分。

这说明作者已经意识到“巨型社区”会降低图谱解释性，所以做了二次切分。

---

## 7. 分析层：它如何从图里得出“结论”

`analyze.py` 是整个项目里最像“产品脑”的模块。

它不只是做 graph analytics，而是在把图转换成**对人有用的结论**。

### 7.1 God Nodes

God nodes = 度最高、连接最多的核心实体。

但它并不是简单按 degree 排序，而是排除了：

- 文件级 hub 节点
- AST 方法 stub
- 某些概念注入节点

这很重要，因为否则“某某文件.py”或者“.init()”这种机械节点会刷榜，没有分析价值。

### 7.2 Surprising Connections

这是 Graphify 很有意思的输出。

它会找“令人意外的连接”，例如：

- 跨文件类型（code ↔ paper）
- 跨 repo / 目录
- 跨 community
- peripheral node ↔ hub node
- `semantically_similar_to` 的非结构性连接

并且为每条连接生成一段 `why` 解释。

也就是说，它不是只是把边列出来，而是尝试回答：

> 为什么这条边值得你看？

### 7.3 Suggested Questions

它还会反向生成“图谱特别适合回答的问题”：

- AMBIGUOUS edge → “这两个实体到底是什么关系？”
- 高 betweenness bridge node → “为什么它连接了两个社区？”
- god node 上有多个 inferred edge → “这些推断是否真的成立？”
- 弱连接节点 → “它和系统剩余部分怎么关联？”
- 低 cohesion community → “是否应该拆模块？”

这个设计很妙，因为它把 graph 从“浏览对象”变成了“提问生成器”。

---

## 8. 报告和导出层

Graphify 最终不是只输出一个 graph.json，而是做了多种面向不同使用场景的导出：

### 8.1 `GRAPH_REPORT.md`

这是最重要的人类入口。

根据 `report.py`，它会输出：

- 图谱摘要
- 社区结构
- cohesion 分数
- god nodes
- surprising connections
- suggested questions
- 可能还有 rationale / gap 类型信息

也就是说，这个报告的定位不是“原始数据 dump”，而是**一页式导航摘要**。

### 8.2 `graph.json`

持久化图，可以后续 query/path/explain 继续用。

### 8.3 `graph.html`

可交互图形界面，应该是基于 `vis.js`。

### 8.4 其他导出

README 和代码里提到：

- `graph.svg`
- `graph.graphml`
- Neo4j `cypher.txt`
- 直接 push 到 Neo4j
- `wiki/`（agent crawlable wiki）

### 8.5 Wiki 导出

`wiki.py` 会把 graph 转成：

- `index.md`
- 每个 community 一篇文章
- 每个 god node 一篇文章

这个非常像把 graph 再编译成一个 agent 友好的 markdown wiki。也就是说它其实支持两层表示：

1. 图结构（json/html）
2. 传统文档结构（wiki markdown）

这和 Karpathy 的 llm-wiki 思路是相通的，只是 Graphify 多了一层图谱中间态。

---

## 9. 缓存、watch、git hook：它为什么“可持续”

很多这类项目 demo 很酷，但一跑第二次就废了。Graphify 在工程化上做了不少补强。

### 9.1 SHA256 缓存

`cache.py` 用：

- 文件内容 hash
- 解析路径

生成缓存 key。

这样重复运行时只处理变更文件，不需要全量重建。

### 9.2 `--watch`

`watch.py` 监控目录变化：

- 代码文件变化 → 可自动重建 AST 图
- 文档/图片变化 → 提醒再跑语义 update

### 9.3 git hooks

`hooks.py` 可以安装：

- `post-commit`
- `post-checkout`

这样每次 commit / 切分支之后都能自动重建图谱。

这个点很关键：它在试图把 graphify 从“一次性分析工具”做成“持续保持新鲜的知识索引”。

---

## 10. 平台集成：它如何接入 Claude / Codex / OpenClaw

Graphify 的 CLI 入口在 `__main__.py`。

它不是只做 `graphify run`，还做了 platform-specific install：

- `graphify install`
- `graphify claude install`
- `graphify codex install`
- `graphify opencode install`
- `graphify claw install`

### 10.1 Claude Code 集成更深

对 Claude Code，它会：

1. 安装 skill 到 `~/.claude/skills/graphify/SKILL.md`
2. 注册到 `~/.claude/CLAUDE.md`
3. 往 `.claude/settings.json` 写 `PreToolUse` hook

这个 hook 会在 `Glob|Grep` 前提示：

> Knowledge graph exists. Read GRAPH_REPORT first before searching raw files.

这等于在 agent 搜原始文件前强行加一层“先看地图”。

### 10.2 Codex / OpenCode / OpenClaw

这些平台没有 Claude 那种 hook，所以它走 `AGENTS.md` 常驻规则：

- 先看 `graphify-out/GRAPH_REPORT.md`
- 如果有 `wiki/index.md` 则优先导航 wiki
- 修改代码后触发重建

这个实现思路很现实：不同平台能力不同，Graphify 用“能插多深插多深”的方式适配。

---

## 11. 安全设计

`security.py` 做了不少基础防护：

- `validate_url()`：只允许 http/https
- 阻止 `file://` redirect
- fetch 时限制大小和超时
- `validate_graph_path()`：graph 文件路径必须在 `graphify-out/` 内
- `sanitize_label()`：去控制字符、长度截断、HTML escape

这不是极致安全审计级别，但对一个会 ingest URL、导出 HTML、跑本地 server 的工具来说，已经比很多 side project 更认真。

---

## 12. 这个项目真正厉害的地方

### 12.1 它把“图谱”落到非常具体的工程实现

很多 GraphRAG 项目只停在 PPT 层：

- ingest documents
- build graph
- query graph

Graphify 则把每一步都工程化了：

- AST 抽取
- schema 校验
- community detection
- report 生成
- HTML / wiki / graphml / neo4j 导出
- 平台 skill 安装
- watch / hook / cache

### 12.2 它的“图”不是纯语义图，而是结构图 + 语义图的混合体

这是比单纯 embeddings 更实用的点。

因为代码库理解里，最重要的信息往往不是“语义相似”，而是：

- 谁 import 谁
- 谁调用谁
- 谁实现谁
- 哪个设计动机解释了哪个模块

Graphify 把这些结构关系作为第一等公民。

### 12.3 它非常适合 agent 时代

它的目标不是给人一个华丽 dashboard，而是给 agent 一个更好的中间表示层：

- `GRAPH_REPORT.md` 给全局概览
- `graph.json` 给精确路径查询
- `wiki/index.md` 给普通 markdown 导航
- `AGENTS.md/CLAUDE.md` 把这个流程接到 agent 工作流里

换句话说，它不是“可视化项目”，而是“agent memory/index compiler”。

---

## 13. 它的局限和潜在问题

### 13.1 实体对齐仍然偏轻量

如果两个语义抽取得到不同 ID，但本质是同一个概念，当前系统不一定能很好合并。它更依赖：

- 稳定 ID 生成
- 抽取阶段一致性
- 后写覆盖前写

对于超复杂跨语料知识库，后续可能需要更强的 entity resolution。

### 13.2 语义抽取质量高度依赖外部模型

代码 AST 部分是稳定的，但文档/图片/论文抽取准确率取决于：

- Claude / GPT / 当前平台模型质量
- prompt 设计
- vision 对图像内容的理解能力

因此图谱质量上限很大程度由外部模型决定。

### 13.3 无向图是一个折中

保留 `_src/_tgt` 能部分补救，但本质上社区发现与结构分析使用的是无向图。这对某些强方向依赖关系（如数据流、调用链）会有信息损失。

### 13.4 大图 lint/analysis 仍可能变贵

随着节点和边增长，

- 社区发现
- betweenness
- edge ranking
- export

都会越来越重。Graphify 当前更像“中等规模本地知识图谱”工具，而不是海量企业级图数据库方案。

---

## 14. 结论

Graphify 的实现本质可以概括为：

> **先把多模态语料编译成一张带置信度的知识图，再围绕这张图做聚类、分析、解释和 agent 导航。**

它的关键实现优势在于：

1. **代码走 AST，文档走语义抽取** —— 两路合并
2. **统一 schema** —— 节点边模型清晰
3. **NetworkX + Leiden/Louvain** —— 无 embedding 也能聚类
4. **confidence labels** —— 把事实、推断、歧义分开
5. **report / wiki / html / json 多表示层** —— 面向人和 agent 双方
6. **hook / watch / cache / install** —— 真正能持续使用，而不只是 demo

如果把 Karpathy 的 llm-wiki 看成“让 LLM 持续维护 wiki”，那 Graphify 可以看成是：

> **在 wiki 之前，先增加一层 graph compiler。**

它不是简单替代 RAG，而是在 agent 工作流里提供了一个比“直接 grep 原文件”更结构化的中间层。

---

## 我自己的判断

如果我以后要做类似系统，我会借鉴 Graphify 的三点：

1. **AST 和语义提取分离** —— 不要把所有东西都扔给 LLM
2. **confidence / provenance 必须保留** —— 不然图谱会很快变成幻觉垃圾场
3. **GRAPH_REPORT.md 这种一页式入口很关键** —— agent 先读 report 再搜 raw，比一上来 grep 整个仓库聪明得多

如果要继续增强，我会优先考虑：

- 更强的实体对齐
- 更细粒度的方向图分析
- 针对大图的增量分析
- 更明确的“why/rationale”抽取 schema

整体评价：**这不是噱头项目，是真正把 agent-friendly knowledge graph 做成了一套能落地的工程实现。**
