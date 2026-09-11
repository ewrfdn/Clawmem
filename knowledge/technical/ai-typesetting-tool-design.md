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
