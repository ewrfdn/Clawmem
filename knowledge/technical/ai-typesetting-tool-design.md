# AI 自动排版工具 — 设计方案（归档）

> 来源：workspace/ai-typesetting/方案.md | 日期：2026-09-10 | 作者：Bocchi + Sakana

## 一句话

AI 优先的自动排版工具：AI 生成受约束的"图层树"（JSON，真相源）→ 渲染器编译成 HTML/CSS → headless Chrome 导出为图片/PDF。图层操作像 PS，渲染能力吃浏览器红利。

## 核心结论（调研）

1. **HTML 就是现成的图层系统**：`position:absolute` + z-index = 图层树，`mix-blend-mode`/`mask`/`filter` 对应 PS 混合/蒙版/滤镜，浏览器 compositor = Mercury。免费最强排版引擎，LLM 写 HTML/CSS 质量远高于自定义 DSL。
2. **数据模型与渲染分离**（PS 架构）：真相源 = 图层树 JSON；HTML 只是编译目标，AI 永远不直接碰 HTML。可撤销/可编辑/可控。
3. **没有专门库，方向已被验证**：
   - CreatiPoster（阿里，开源）：LLM 生成可编辑多层图层，已集成剪映 Pippit AI。最接近。
   - PosterO：LLM 输出布局树再渲染。抽象一致。
   - Penpot（51.7K★）：开源 Figma，SVG/CSS/HTML，MCP，完整应用非库。
   - "图层树→HTML→导出"精确搜索返回 0 条 → **真空白**。
   - 零件全现成：html-to-image / html2canvas / Puppeteer / Vivliostyle；AI 受约束 JSON 参考 Vercel json-render（思路最像，面向 UI 组件）。

## 架构

```
AI → 图层树 JSON（受 schema 约束）→ 渲染器(纯函数,HTML/CSS) → headless Chrome → 图/PDF
                                        ↓
                                  图层面板(增删改/undo)
```

## 图层 Schema（v1，2026-09-11 定稿）

- **顶层**：`{ schema:"poster/v1", canvas{width,height,background}, assets[], fonts[], layers[] }`
- **图层类型**（白名单）：`image` / `text` / `rect` / `group`
  - 公共字段：id, name, type, x, y, width, height, zIndex, visible, opacity, blendMode, transform, filter, mask
  - `image`：src, objectFit(cover/contain/fill/none), objectPosition
  - `text`：content(\n→<br>), style{fontFamily,fontSize,lineHeight,fontWeight,letterSpacing,color,align,whiteSpace,italic,decoration}, fill(渐变文字→clipToText), runs(局部富文本,同层多段样式)
  - `rect`：fill{color|gradient|image 可叠加}, borderRadius(支持 50%), border
  - `group`：children[]，子层相对定位，zIndex 组内生效
- **fill 细节**：color / linear-gradient{angle,stops} / bgImage{position,size,repeat}；文字渐变加 clipToText:true→background-clip:text
- **transform**：{rotate, origin, scaleX, scaleY}（超大字号用 fontSize 基数 + scale 放大）
- **约束**：类型/样式白名单，AI 输出经 JSON Schema 校验（`schema.json`）+ 兜底默认值
- 文件：schema.md（规范）/ schema.json（可校验）/ examples/tshirt-poster.json（参考海报完整转换）

**JSON Schema 踩坑**：`allOf` 组合里基类 schema 的 `additionalProperties:false` 会误杀类型子 schema 新增字段（src/objectFit 等）→ 改为**每个图层类型一个完整独立 schema**（自带公共字段 + 类型字段 + `type` const 判别），draft-07 兼容，ajv@8 通过。

## 渲染器（核心增量）

- 纯函数 `render(layerTree) → htmlString`，确定性、无框架依赖、浏览器+Node 双跑
- 每图层 → position:absolute div，z-index 按数组序
- 映射：fill→background-image / background-clip:text；blendMode→mix-blend-mode
- group → 嵌套 div + 相对坐标
- 编辑态：拆单图层函数 renderLayerElement/renderLayerStyle 供实例层挂载/重算

## 编辑内核（v2，2026-09-11）

### 架构：数据流驱动，每帧走数据

```
手势层(事件委托+hit-test) → 改实例数据 → 实例层(id↔element 绑定+Proxy) → 同步层(属性→CSS 单点 patch)
```

- **实例层**：`Map<layerId, {data(响应式), el, children}>`，layer id ↔ DOM element 一一绑定
- **响应式**：Proxy 拦截 set → `syncStyle(id, key, value)` 定向同步（x→left, y→top, width, height, opacity, zIndex, visible→display；视觉类→重算该元素 style）
- **三种变更**：属性级（Proxy→单属性更新，最频繁）/ 结构级（局部 insert/remove/排序）/ 全量 render（初始化/导入/导出才用）
- **比 vdom 更轻**：vdom 是"不知道哪变了 diff 整棵"，本方案"知道改哪个 layer 哪个属性，直接 patch"
- 拖动中每帧改数据（60fps），松手提交 undo（命令式 delta {layerId, prop, before, after}，恢复也走数据流）

### 坐标系与 group 嵌套

- **存储/渲染都用相对直接父坐标**：`layer.x/y` 始终相对画布或直接父 group
- **渲染嵌套 DOM**（group 必嵌套）：CSS absolute 天然相对最近 positioned ancestor，零换算；拖 group 浏览器自动跟随子层
- **不扁平化**：扁平化才需逐层累加成画布绝对坐标，拖 group 要重算全部子层
- **坐标工具函数族**：toAbsolute / toParent / hitTest（编辑与 group 转换共用）
- **ungroup**：子层新坐标 = 父 group 坐标 + 子层相对坐标（例：image(15,15) 相对 B，B(50,50) 相对 A → 相对 A=(65,65)）
- **group**：子层新坐标 = 子层相对父坐标 − 目标 group 相对父坐标（例：C(100,100) 相对 A，D(40,40) 相对 A → C 相对 D=(60,60)）
- **多层级递归**：每提升/下降一层加减一次父坐标；转换目标是"新父级相对坐标"非画布绝对坐标
- **v1 限制**：group 自身不做 transform（rotate/scale 只允许叶子图层），绕开变换矩阵复杂度

### UI 交互层

- **不逐元素绑事件**：canvas 容器事件委托（pointerdown/move/up）+ hitTest 按图层树几何计算命中（透明像素穿透/嵌套/zIndex 可控），不依赖 event.target
- **overlay 层**：选中框/8 resize 手柄/旋转手柄/参考线画在独立浮层，不污染真实图层 DOM
- **手势状态机**：pointerdown 判定手势类型 → pointermove 每帧改数据 → pointerup 提交 undo（一次手势一条干净 diff）
- **图层面板**：树形展示（group 可折叠）、选中双向联动、增删/排序/显隐/混合模式/透明度
- **属性面板**：编辑 x/y/宽/高/颜色/字号 → 同一数据流（改数据=DOM 同步）
- **undo/redo**：命令式 delta 栈（100 条），结构级操作记录结构 diff

## 关键技术点

### 超大字号
- CSS font-size 无硬上限；浏览器光栅化/内存/GPU 贴图有边界（Chrome ~100万px 不渲染；GPU max texture 通常 8192~16384px）
- 推荐：合理基数 + `transform: scale()` 放大，字形只按基数光栅化，内存可控
- 导出用 deviceScaleFactor 超采样

### 文字渐变填充
```css
background-image: linear-gradient(...);
-webkit-background-clip: text;  /* 必须前缀 */
background-clip: text;
-webkit-text-fill-color: transparent;
```
四个坑：必须 `-webkit-` 前缀；必须透明文字；必须 background-image（纯 color 无效）；别用 background 简写。

## 里程碑

- M1: schema（已定稿）+ 渲染器骨架 → 独立 npm 包雏形
- M2: **编辑内核**：实例层 + 数据流驱动 + 坐标工具 + undo → 可交互 demo（选中/拖动/resize）
- M3: 导出管线（PNG/PDF）+ 超大字号/渐变验证
- M4: AI 接入（LLM 函数调用 → 图层树）
- M5: UI 完善：图层面板、属性面板、group/ungroup、对齐参考线/吸附

## 风险与对策

- AI 直接写 HTML 失控 → 只出受约束图层树
- 排版不可预测 → 白名单 + schema 校验 + 确定性渲染
- 编辑时全量重建卡顿 → 数据流驱动 + 定向同步，拖动中只改单元素 style
- 大文件内存爆炸 → scale 替代超大字号 + 受控超采样
- group 嵌套坐标混乱 → 相对坐标存储 + 嵌套 DOM 渲染，group/ungroup 只做一次坐标换算
- 与 CreatiPoster 重复 → 差异化：通用 LLM + 独立库 + 自托管轻量
- 字体版权 → 自托管字体子集化

## 下一步

1. 写 M1：layer-schema + renderer 独立小包（浏览器+Node 双跑）
2. 用"超大字号渐变标题"做验证用例
3. 跑通 M1-M2 后决定是否开源

## canvas 图层 vs HTML 图层：取舍的决策依据（2026-09-20 补）

背景：09-20 Sakana 问「使用这样的系统，用 canvas 图层和用 html 图层取舍是什么」。参考对象是 `yejy53/Editable-Design`（arXiv 2609.04034 的官方实现，三个 Codex Skill 包），它明确选了 HTML 图层并把代价写进 `skills/editable-design/references/editor-pitfalls.md`（38 条坑表）。这份决策依据同样回答我自己的 `poster/v1` 为什么走 HTML 路线。

### 两种模型在争什么
- **Canvas / 场景图**（Figma、Photoshop 式）：图层是自定义数据结构里的节点，x/y/transform/z 是一等公民；渲染、命中、编辑全部由自己的引擎完成。
- **HTML 图层**（Editable-Design、本项目）：设计本身就是一份 DOM 文档，「图层」= 打了 `data-layer-id` 的 DOM 子树；编辑 = 原地变异 DOM，渲染 = 浏览器。

### 决策表
| 维度 | HTML 图层 | Canvas / 场景图 |
|---|---|---|
| 谁在生成 | coding agent 写 CSS——训练语料里最富的媒介；排版引擎（换行/字体度量/基线）免费 | 要求模型精确吐坐标，无布局引擎兜底，生成质量骤降 |
| 文本 | 真文字：contenteditable / IME / 可搜索 / a11y 全白送 | 文本整形、换行、IME 全部自己造 |
| 渲染与验证 | 浏览器是免费且唯一的 ground truth，verify 拿同一渲染器比像素 | 自己写渲染器；自己渲染自己 = 循环论证，保真 bug 会藏住 |
| 图层操作 | 要和文档模型搏斗：margin 残留、塌缩、z-index 丢失、上下文选择器失效 | transform/z 天然一等公民，拖动旋转零副作用 |
| 下游互操作 | DOM 语义显式 → 能桥接到 PPTX 等文档格式 | 只有你自己认识你的场景图 |
| 自由度 | 只能表达文档能表达的；像素级绘画/复杂混合做不了 | 任意绘制、混合模式、逐像素操作 |

### 决定性因素：生成者是 coding agent
整个管线的前提是「agent 写代码 → 脚本确定性验证」。CSS 是 agent **带宽最高**的视觉媒介；换成 Figma JSON 或自定义场景图，等于要求 LLM 闭眼吐精确坐标并自己实现文本换行——把最难的活从引擎搬给模型。第二因素是**验证闭环**（浏览器即生产环境本身，存在外部真值）。第三是**交付语义**（文字可选中可搜索；Editable-Design 的 `_html_to_pptx.py` 约 1669 行 Python，沿 DOM 把每个 span 映射成 PPT 文本框，能表示的就转形状、不能的烘焙成图）。

### 代价写在哪里
`editor-pitfalls.md` 那张 38 条坑表就是 HTML 图层的账单：
- **T1–T11（固化）**：DOM 生来是文档不是图层。把文档流元素提升为可拖动图层后，margin 残留、`bottom` 定位塌陷、宽度收缩、上下文选择器 `.dark-card .label` 失效、字体没加载完量错坐标——每一条都是「文档语义 ≠ 图层语义」的翻译事故。
- **T12–T19（交互）**：和浏览器自己的事件模型打架——pointer capture 劫持 dblclick target、中文组字期 Esc/Enter 语义、粘贴富文本污染。
- **转换税**：html-to-pptx 那一千六百行 + representability 启发式。

### 「HTML 为介质，canvas 为纪律」
关键细节：`layout-typography.md` 规定**画布内所有图层必须绝对定位、全固定 px、坐标显式**。也就是用 `poster.json` 契约 + check-contract 校验，把 HTML 强行约束成一个**伪场景图**——享受 CSS 的生成人体工学和文本引擎，但禁止文档流、禁止隐式布局。这解释了为什么 pptx 转换器可行：它只处理这个受控子集。配合两个逃生舱：表达不了的视觉走栅格资产分层；像素级操作用独立脚本离线处理，不进 DOM。

### 一句话决策规则
**生成端是 coding agent、交付端是文档/可导出格式 → HTML 图层 + 契约约束**（Editable-Design、本项目）；**交互端是重编辑、需要自由绘制/混合/大量图层实时画布，且愿意自建文本与 IME → 场景图**。选 HTML 不是因为它更适合「图层」，而是因为 agent 的生成带宽和浏览器的免费保真在这个体系里是压倒性优势，38 条翻译成本是值得付的固定开销。

**对 `poster/v1` 的直接印证**：v1 的白名单 + schema 校验 + 确定性渲染，与 Editable-Design 的 `poster.json` + `check-contract` 是同一个形状——都是「用契约把 HTML 约束成受控子集」。差别在于他们有三条逃生舱（栅格资产 / 离线像素脚本 / pptx 桥接），v1 目前只定义了纯图层树。这是 v2/M1 值得参考的部分。
