# AI Agent 友好的游戏开发调研

> 本文整理了我与 Sakana 连续多轮讨论中，关于 **AI-first / AI agent 友好的 2D 游戏开发** 的核心结论。重点不是“游戏开发的一般常识”，而是：如果未来要让 AI 持续参与设计、编写、修改、验证并迭代完整游戏项目，那么引擎、运行时、地图、UI、素材和工具链应该怎样设计。

---

## 0. 研究目标

本文聚焦的问题是：

1. 什么是 **AI-first 游戏引擎**？
2. 为什么传统引擎（尤其 editor-first）并不天然适合 AI 持续开发？
3. 对一个 **纯 2D、code-first、无重 GUI 编辑器依赖** 的项目来说，什么样的技术栈和项目结构更适合 AI？
4. 地图、Prefab、UI、资源和调试系统应该如何设计，才能让 AI 稳定地产出可运行内容？
5. 对未来 demo → runtime → 小引擎 的演化路线，应该如何安排？

---

## 1. 对“AI-first 游戏引擎”的当前理解

### 1.1 一句话定义

**AI-first 游戏引擎** 不是“传统引擎 + 一个代码补全助手”，而是：

> 一套从一开始就把 AI 当作主要开发者之一来设计的 **运行时 + 内容描述语言 + 验证闭环**。

它必须让 AI 能：
- 理解系统
- 生成内容
- 修改现有内容
- 运行验证
- 根据错误反馈自动修复
- 持续迭代，而不是一次性写出一堆代码后失控

### 1.2 它真正由三部分组成

我目前把 AI-first 引擎理解为三件事的组合：

#### A. Runtime
负责真正运行游戏：
- 渲染
- 输入
- 场景
- 实体
- 碰撞/物理
- 音频
- UI Runtime
- 资源系统

#### B. DSL / Schema
负责让 AI 书写和修改内容：
- 地图格式
- Prefab 格式
- UI 格式
- Trigger / Event 格式
- 任务/交互数据
- 数值配置

#### C. Debug / Validation Loop
负责让 AI 自证正确并修复问题：
- headless mode
- replay
- deterministic simulation
- snapshot / assert
- schema validation
- 结构化日志
- 可修复错误信息

如果缺少 C，它只是“AI 帮忙写代码”；
如果缺少 B，它只是“AI 猜着写玩法”；
如果缺少 A，它甚至不算引擎。

---

## 2. 最大难点不是图形，而是可控性

### 2.1 为什么真正的难点不在渲染

传统引擎开发常把重点放在：
- 图形 API
- 资源系统
- 性能优化
- 多平台部署

但对于 AI-first 项目，更大的难点变成：

> **如何把系统设计得足够明确、稳定、低歧义，让 AI 写出来的东西不会长期跑偏。**

关键问题包括：
- API 是否足够统一
- 生命周期函数是否清楚
- 同一件事是否只有一套推荐写法
- 错误信息是否具有“修复指向性”
- 内容数据是否集中而非散落在 GUI 状态里

### 2.2 AI-first 引擎设计的第一原则：可预测

AI 不是不能处理复杂系统，但它非常怕：
- 隐式初始化
- 隐藏在 Inspector / GUI 中的状态
- 同一行为有多个入口
- 生命周期函数很多但顺序复杂
- 命名不统一
- 编辑器里拖出来的关系没有文本化出口

所以 AI-first 引擎设计更应该偏向：
- 显式 > 隐式
- 统一 > 灵活多变
- 少原语 > 大而全
- 可校验 > 自由格式
- 文本化 > 面板状态

---

## 3. 为什么更适合 code-first / data-first，而不是 editor-first

### 3.1 传统引擎成功的路径

Unity / Godot / Unreal 的主流工作流是：
- 编辑器
- 拖拽
- 面板
- Inspector
- 可视化编辑
- 所见即所得

这对人类开发者非常友好，但对 AI 来说并不天然友好。

### 3.2 AI 更擅长什么

AI 更擅长：
- 写结构化文本
- 填 schema
- 修改 DSL
- 组合模板
- 根据报错修结构
- 批量改数据

所以更适合它的方式是：
- 代码
- YAML / JSON / TOML / TS DSL
- 文本化 scene
- 文本化 prefab
- 文本化 UI
- 可 diff / 可 merge / 可 validate 的资源定义

### 3.3 结论

> **AI-first 引擎更像“可编译的内容系统”，而不是“以可视化编辑器为中心的系统”。**

GUI 工具不是不能有，但应该是辅助层，而不是唯一真相来源。

---

## 4. 2D、2.5D、真 3D：为什么现在更适合先做 2D

### 4.1 当前最适合 AI-first 的不是复杂 3D

对于当前阶段的项目目标：
- code-first
- 无重 GUI 编辑器
- 让 AI 直接写玩法
- 先做最小 demo

我认为最适合的不是复杂 3D，而是：

> **纯 2D Runtime + 2.5D 视觉表达（如果需要空间感）**

### 4.2 为什么 2D 更适合 AI-first

因为它天然更容易：
- DSL 化地图
- Prefab 化对象
- Trigger 化事件
- Headless 测试
- 用文本表达世界结构

而真 3D 会带来：
- 模型导入工作流
- 材质与动画复杂度
- 相机与坐标空间复杂度
- 工具链复杂度成倍上升

### 4.3 对 2.5D 的理解

所谓 2.5D，不是完整 3D，而是：
- 正交俯视 + 高度层
- 屋顶/墙体/台阶/桥/阴影/遮挡
- 用 2D 逻辑表达空间错觉

这一层很适合未来扩展，但不应该成为第一版 runtime 的主要负担。

---

## 5. 技术栈调研与结论

### 5.1 候选底座对比

我们主要比较过：
- LÖVE
- MonoGame
- raylib

#### LÖVE
- Lua 2D 框架
- 上手快
- 极强 code-first
- 适合原型 / jam / 小项目
- 但长期工程性和类型约束较弱

#### raylib
- 极简底层库
- API 小、概念少、很干净
- 很适合自己往上搭 runtime
- 但中层系统要自己补得更多

#### MonoGame
- C# 框架
- 工程化更强
- 强类型
- 更适合长期维护和 AI 稳定写 gameplay 代码
- 很适合作为自定义 runtime / 小引擎的底盘

### 5.2 当前推荐

如果目标是：
> **让 AI 持续参与一个完整 2D 游戏项目，并且未来逐步演进成自己的引擎**

我目前最推荐的底座是：

## **MonoGame**

原因：
- C# 对 AI 写 gameplay / UI / scene 逻辑更稳定
- code-first，不依赖重编辑器
- 适合长期维护
- 已经有成熟商业案例
- 容易在 Runtime / Content / Demo 三层之间分层

### 5.3 关于 MonoGame 的现实判断

- 它与 Unity 没有直接继承关系，更接近 XNA 的开源精神续作
- 能做 3D，但对本项目而言不建议一开始走真 3D
- 适合作为 **2D / 2.5D runtime 底盘**
- Windows 下可以用 DX，跨平台常用 DesktopGL/OpenGL，但后端不是当前核心矛盾

---

## 6. 项目结构建议：先做 Demo，再演进 Runtime

### 6.1 当前最合理的目标

现在不应该一上来就做“完整引擎”，而是：

> **先做一个最小可运行 demo，并从第一天起按未来引擎化的方式组织结构。**

### 6.2 推荐 solution 结构

```text
YourGame/
├─ src/
│  ├─ Game.Runtime/
│  ├─ Game.Content/
│  └─ Game.Demo/
├─ assets/
│  ├─ textures/
│  ├─ audio/
│  ├─ fonts/
│  └─ data/
├─ tests/
├─ docs/
├─ tools/
└─ YourGame.sln
```

#### Game.Runtime
放：
- scene/world/entity
- rendering abstraction
- camera
- input
- collision
- event bus
- animation player
- asset manager
- debug hooks

#### Game.Content
放：
- scene schema
- prefab schema
- tileset schema
- yaml/json 解析
- 数据校验
- 内容导入与转换

#### Game.Demo
放：
- 玩家逻辑
- 敌人逻辑
- demo 场景
- HUD
- demo 规则
- demo 用 content registry

### 6.3 这个结构的意义

- Gameplay 与 Runtime 分离
- Content 格式独立于 Runtime
- 未来可以把 Runtime / Content 抽成真正小引擎
- AI 可主要操作 Demo + assets/data，不需要频繁动 Runtime 核心

---

## 7. 地图系统：最适合 AI 的表示方式

### 7.1 地图不是只能是格子

现代 2D 游戏并不只有纯 tilemap，实际常见的是：
- tile / grid 作为基础地形
- object layer 自由摆放对象
- trigger / nav / spawn 独立图层

### 7.2 最适合 AI 的地图表达

最推荐：

> **声明式 YAML / JSON + 少量 DSL 语义**

而不是：
- 纯自然语言地图描述
- 纯 ASCII 地图
- 直接手写超大数组

### 7.3 推荐的地图信息层

一个 AI-first 地图应能表达：
- size
- tile layers
- region fills
- objects
- triggers
- spawns
- exits
- nav / waypoint（可选）

示例结构：
- `ground`
- `terrain`
- `buildings`
- `npcs`
- `triggers`
- `spawns`

### 7.4 设计原则

地图格式应满足：
- 强 schema
- 图层清晰
- 支持区域描述（AI 更擅长区域，不擅长逐格硬填）
- 支持自由对象
- 支持 prefab 引用
- 可编译成 runtime 格式
- 可被 headless 测试验证

---

## 8. Prefab：为什么它对 AI-first 引擎特别重要

### 8.1 定义

Prefab = **可重复实例化的对象模板**。

它解决的问题是：
- 复用
- 一致性
- 维护性
- 降低 AI 生成复杂对象时的错误率

### 8.2 为什么重要

如果没有 prefab，AI 每次都得从零展开：
- Sprite
- Collider
- Health
- AI
- DropTable
- QuestBehavior

这会非常啰嗦且容易漏字段。

如果有 prefab，AI 地图里只需要写：

```yaml
type: skeleton_archer
```

然后再用 overrides 少量改参数。

### 8.3 在 AI-first 系统里的意义

Prefab 本质上是“地图语言里的词汇表”。
它能极大降低地图、场景和玩法描述的复杂度。

---

## 9. UI：为什么更适合声明式 DSL，而不是一开始做重 GUI 系统

### 9.1 对 MonoGame 的推荐

- 游戏内 UI：**Myra** 可作为底层 runtime 选择
- 调试 UI：**ImGui.NET / Dear ImGui**
- 极简 HUD：可直接自己画

### 9.2 关键判断

很多引擎现在用 HTML-like 描述 UI，这背后的本质不是“变网页”，而是：

> **声明式树结构 + CSS 式布局，本身就很适合描述 UI，也很适合 AI 生成。**

### 9.3 对当前项目的建议

不建议第一版真的嵌浏览器/WebView。
更适合的是：

- HTML-like DSL
- 或 JSX-like / TypeScript DSL
- 底层仍然由 MonoGame + 自己的 UI Runtime 渲染

### 9.4 推荐的 UI 原则

- UI 结构声明式
- 文案/绑定/动作可独立修改
- 不把真正动态文本烘焙进贴图
- 对 AI 来说，UI 也应当是一种 schema，而不是 imperative API 大堆叠

---

## 10. Tiled：作为地图编辑器的合理位置

### 10.1 对 Tiled 的定位

Tiled 不是引擎，而是：

> **一个成熟的 2D 地图编辑器，可以作为 AI-first 引擎早期的地图编辑前端。**

### 10.2 最推荐的使用方式

不是让运行时直接依赖 Tiled 原始格式，而是：

- **Tiled = 编辑器**
- **Importer = 编译器**
- **Runtime Map JSON = 运行时格式**

### 10.3 推荐的数据流

```text
Tiled 编辑 .tmj/.json
    ↓
你的 importer 读取 Tiled JSON
    ↓
转成你自己的 runtime map.json
    ↓
游戏只加载 runtime map.json
```

### 10.4 为什么这很重要

这样可以做到：
- Tiled 与项目独立运行
- 运行时不被 Tiled 数据结构绑死
- 自定义 object 通过 object layer + class/type + properties 表达
- Importer 可做 schema 校验和错误提示

### 10.5 Tiled 中自定义 object 的推荐方式

使用：
- Object Layer
- `class` / `type`
- `properties`
- 可选 object templates

例如：
- NPC：`prefab=npc_blacksmith`
- Door：`target_scene=world_road_01`
- Enemy Spawn：`wave=bandits_small`

这和未来的 prefab / scene schema 非常契合。

---

## 11. 地图预览：MonoGame 的角色不是“编辑器”，而是“运行时预览器”

### 11.1 MonoGame 不擅长开箱即用编辑器式预览

它没有 Unity/Godot 那种现成地图编辑体验。

### 11.2 但它非常适合做运行时预览

只要补上：
- 地图数据加载
- reload 快捷键
- debug overlay
- layer 可视化开关
- 碰撞 / trigger / nav 显示

它就能成为一个很好的地图预览 runtime。

### 11.3 两条现实路线

#### 方案 A：Tiled + MonoGame
- Tiled 画 tile/object/trigger
- MonoGame 负责运行和预览
- 适合快速起步

#### 方案 B：自定义 YAML/JSON + MonoGame
- 更符合长期 AI-first 方向
- 完全 data-first
- 更适合 schema 和 headless validation

---

## 12. 视觉风格：2D 但有 3D 观感

### 12.1 关键结论

2D 引擎完全可以做出明显的 3D 观感，方法包括：
- 等距 / 斜视角
- 高度层
- 屋顶 / 墙体 / 阴影 / 遮挡
- 台阶 / 桥 / 平台规则
- 顶面 vs 侧面区分

### 12.2 对当前项目的建议

未来如果想做“中世纪城市、俯视角、空间感强”，最佳路线不是直接做真 3D，而是：

> **纯 2D 逻辑 + 2.5D 视觉表达**

### 12.3 参考游戏

适合研究的有：
- Hades / Hades II
- Death’s Door
- TUNIC
- Bastion
- Children of Morta
- Moonlighter
- 以及中世纪城市建筑表达参考：Age of Empires II / Stronghold / Diablo II

---

## 13. AI 图像生成与素材生产：对游戏开发的意义

### 13.1 关键结论

如果目标是生成：
- sprites
- props
- UI 元素

那么选择模型的标准不再是“单张图最漂亮”，而是：
- 风格一致性
- 可控性
- 批量迭代能力
- 是否适合透明背景/后处理
- 是否适合 LoRA / inpaint / control 工作流

### 13.2 当前更适合的组合

- **Midjourney / ChatGPT 图像**：定风格、做 moodboard、概念探索
- **SDXL 生态**：更适合卡通/动漫/角色类素材生成
- **FLUX**：更适合 props / 场景物件 / 高质量元素
- **Ideogram**：更适合带字设计 / logo / 标题

### 13.3 对本项目的现实建议

真正可落地的工作流是：
- 闭源模型做风格探索
- 开源模型做可控生产
- 最终靠人工整理、透明背景、切图、9-slice、sprite sheet 等后处理落成游戏资源

### 13.4 2D 素材网站调研结论

对中世纪 / 卡通 / 动漫相关 2D 素材，较实用的站点包括：
- itch.io Game Assets
- OpenGameArt
- CraftPix
- GameArt2D
- Chequered Ink
- Kenney（更适合原型统一风格）

其中：
- **CraftPix / GameArt2D** 更适合非像素、卡通/手绘风
- **itch.io / OpenGameArt** 更适合挖广泛资源与原型素材

---

## 14. 推荐的最小 Demo 范围

### 14.1 不要一上来就做完整引擎

第一阶段只需要验证：
- Scene 加载
- Tile / Object / Trigger 表达
- 玩家移动
- 1 个敌人
- 1 个攻击系统
- 1 个 HUD
- 1 个 headless test
- 1 个地图 reload / 预览流程

### 14.2 推荐场景

- `boot`
- `test_arena`
- `village`

### 14.3 推荐工作流

1. MonoGame 起项目
2. Runtime / Content / Demo 分层
3. Tiled 或 YAML 先跑通地图
4. Prefab / Trigger / UI DSL 逐步抽象
5. Headless test 和 debug overlay 从早期就接入

---

## 15. 当前最重要的设计原则（提炼版）

### AI-first 游戏引擎设计原则
1. 显式优于隐式
2. 少原语优于大而全
3. 数据优于面板
4. schema 优于自由格式
5. 可验证优于“看起来能跑”
6. headless 优于只能手点
7. Runtime 与 Gameplay 必须分层
8. AI 主要写 Gameplay / Content，不碰核心 Runtime
9. 错误信息必须“可修复”
10. 先做 2D / 2.5D，不急着真 3D

---

## 16. 当前推荐路线（结论）

### 16.1 底座
- **MonoGame** 作为当前最推荐的长期底座

### 16.2 内容表达
- Scene / Prefab / UI / Trigger / Map 全部走 schema / DSL 化

### 16.3 地图
- 早期可用 Tiled 作为编辑前端
- 通过 Importer 转为自己的 runtime 格式

### 16.4 素材
- 先用现成 2D 资源 + AI 生成做 demo
- 重点是风格统一与工作流闭环，不是第一天就全原创

### 16.5 最小目标
- 做出一个 **可运行、可验证、可扩展** 的 2D demo
- 再从中抽 Runtime，逐步演进为自己的 AI-first 小引擎

---

## 17. 最终判断

当前我对“AI agent 友好的游戏开发”的最终判断是：

> 真正适合 AI 的不是传统意义上的“强大编辑器引擎”，而是一套 **可编译内容系统**：
> - 运行时足够稳定
> - 内容表达足够结构化
> - 验证和错误反馈足够自动化
>
> 未来这个方向真正的竞争力，不在渲染多先进，而在：
> **AI 能否稳定写、稳定改、稳定测、稳定修。**
