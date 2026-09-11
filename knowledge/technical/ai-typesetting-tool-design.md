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
- 图层树可 diff → 增量更新 + undo/redo

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

- M1: schema + 渲染器骨架（rect/text/image/group）→ 独立 npm 包雏形
- M2: 浏览器实时预览 + diff 更新 + undo
- M3: 导出管线（PNG/PDF）+ 超大字号/渐变验证
- M4: AI 接入（LLM 函数调用 → 图层树）
- M5: 图层面板 UI

## 风险与对策

- AI 直接写 HTML 失控 → 只出受约束图层树
- 排版不可预测 → 白名单 + schema 校验 + 确定性渲染
- 大文件内存爆炸 → scale 替代超大字号 + 受控超采样
- 与 CreatiPoster 重复 → 差异化：通用 LLM + 独立库 + 自托管轻量
- 字体版权 → 自托管字体子集化

## 下一步

1. 写 M1：layer-schema + renderer 独立小包（浏览器+Node 双跑）
2. 用"超大字号渐变标题"做验证用例
3. 跑通 M1-M2 后决定是否开源
